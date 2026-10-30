"""Local accounts and opaque seven-day sessions; never included in asset exports."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response

from .access import identity
from .db import db

router = APIRouter(prefix="/auth")
COOKIE = "mindchime_session"
TTL = 7 * 24 * 3600


def connection():
    return sqlite3.connect(db.path, timeout=30)


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def initialize():
    """Idempotent; must run before worker/API start, on a stopped legacy database."""
    with connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS local_users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS local_sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS asset_reviews (record_id TEXT NOT NULL, version INTEGER NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL, reviewer TEXT NOT NULL, reviewed_at TEXT NOT NULL, PRIMARY KEY(record_id,version))"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS app_migrations (id TEXT PRIMARY KEY)")
        credentials = []
        for username, role in [("admin", "admin"), ("user", "user")]:
            # Login names may change; the stable identity owns history and tasks.
            account_id = f"local-{role}"
            if not conn.execute("SELECT 1 FROM local_users WHERE id=?", (account_id,)).fetchone():
                password, salt = secrets.token_urlsafe(15), secrets.token_hex(16)
                conn.execute(
                    "INSERT INTO local_users VALUES (?,?,?,?,?)",
                    (account_id, username, role, salt, password_hash(password, salt)),
                )
                credentials.append({"username": username, "password": password, "role": role})
        if not conn.execute("SELECT 1 FROM app_migrations WHERE id='accounts-v1'").fetchone():
            conn.execute(
                "UPDATE records SET owner_user_id='local-admin' WHERE owner_user_id IS NULL AND kind IN ('conversation','message','artifact','run','memory','job','import_preview')"
            )
            rows = conn.execute("SELECT id,kind,data,status FROM records").fetchall()
            for rid, kind, raw, status in rows:
                data = json.loads(raw)
                changed = False
                if kind == "distillation":
                    data.setdefault("distillation_type", "knowledge")
                    changed = True
                if kind in {"skill", "run"} and (data.get("agent_id") or data.get("agent_snapshot")):
                    # Preserve historical snapshots; the live execution path never loads them.
                    data["legacy_agent_binding"] = {
                        k: data.get(k) for k in ("agent_id", "agent_version", "agent_snapshot") if data.get(k)
                    }
                    for key in ("agent_id", "agent_version", "agent_snapshot"):
                        data.pop(key, None)
                    data["migration_notice"] = (
                        "此实践已迁移为独立方法；已完成步骤保留，后续使用通用 AI 引导。"
                    )
                    changed = True
                if kind == "job" and status in {
                    "queued",
                    "running",
                    "paused",
                    "pause_requested",
                    "waiting_error",
                    "interrupted",
                }:
                    data["stage"] = "账号迁移完成，请明确恢复；旧人物关联的 Skill 任务请重新提交"
                    if data.get("kind") in {"skill_generate", "skill_step"}:
                        data["legacy_requires_restart"] = True
                    conn.execute("UPDATE records SET status='interrupted' WHERE id=?", (rid,))
                    changed = True
                if changed:
                    conn.execute(
                        "UPDATE records SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), rid)
                    )
            conn.execute("INSERT INTO app_migrations VALUES ('accounts-v1')")
        # Historical private revisions acquire their record owner, without rewriting content.
        conn.execute("DELETE FROM local_sessions WHERE expires_at < ?", (time.time(),))
    if credentials:
        account_file = Path(os.getenv("MINDCHIME_ACCOUNTS_FILE", str(db.path.parent / "local-accounts.json")))
        account_file.parent.mkdir(parents=True, exist_ok=True)
        previous = json.loads(account_file.read_text()) if account_file.exists() else []
        fd = os.open(account_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(account_file, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(previous + credentials, stream, ensure_ascii=False, indent=2)


def actor_for_token(token):
    if not token:
        return None
    with connection() as conn:
        row = conn.execute(
            "SELECT u.id,u.username,u.role FROM local_users u JOIN local_sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()
    return dict(zip(("id", "username", "role"), row)) if row else None


@router.post("/login")
def login(body: dict, response: Response):
    username, password = str(body.get("username", "")), str(body.get("password", ""))
    if len(username) > 128 or len(password) > 1024:
        raise HTTPException(401, "账号或密码不正确")
    with connection() as conn:
        row = conn.execute(
            "SELECT id,username,role,salt,password_hash FROM local_users WHERE username=?", (username,)
        ).fetchone()
        salt = row[3] if row else "00" * 16
        calculated = password_hash(password, salt)
        if not row or not hmac.compare_digest(calculated, row[4]):
            raise HTTPException(401, "账号或密码不正确")
        token = secrets.token_urlsafe(48)
        conn.execute(
            "INSERT INTO local_sessions VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), row[0], time.time() + TTL),
        )
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite="lax", path="/")
    return dict(zip(("id", "username", "role"), row[:3]))


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, "")
    with connection() as conn:
        conn.execute(
            "DELETE FROM local_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)
        )
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return request.state.actor


# Explicit capability allowlist. Every new endpoint is admin-only until reviewed.
USER_READ = {
    "dashboard",
    "sources",
    "cards",
    "evidence",
    "agents",
    "conversations",
    "jobs",
    "events",
    "search",
    "skills",
    "runs",
    "memories",
    "artifacts",
    "graph",
    "distillations",
    "persons",
    "cognitive-profiles",
    "distillation-methods",
    "export",
}
USER_WRITE = {"conversations", "messages", "runs", "memories", "artifacts", "jobs"}


def allowed_user_request(method, path):
    parts = path.strip("/").split("/")
    head = parts[0] if parts else ""
    if method == "GET":
        return head in USER_READ and not (head == "sources" and parts[-1] == "impact")
    if head in USER_WRITE:
        return True
    return head == "skills" and len(parts) == 3 and parts[2] == "runs" and method == "POST"


def install(app):
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def authentication(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/v1/") or path == "/api/v1/health" or request.method == "OPTIONS":
            return await call_next(request)
        relative = path[len("/api/v1/") :]
        # Cookie-authenticated browser requests are accepted only from this local web app.
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            allowed_ports = {
                int(os.getenv("MINDCHIME_WEB_PORT", "5173")),
                int(os.getenv("MINDCHIME_API_PORT", "8765")),
            }
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"localhost", "127.0.0.1"}
                or parsed.port not in allowed_ports
            ):
                return JSONResponse({"detail": "请求来源不受信任"}, status_code=403)
        if relative == "auth/login":
            return await call_next(request)
        actor = actor_for_token(request.cookies.get(COOKIE))
        if not actor:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        request.state.actor = actor
        if (
            actor["role"] != "admin"
            and relative not in {"auth/me", "auth/logout"}
            and not allowed_user_request(request.method, relative)
        ):
            return JSONResponse({"detail": "仅管理员可以执行此操作"}, status_code=403)
        if (
            actor["role"] != "admin"
            and request.method in {"POST", "PATCH", "PUT"}
            and request.headers.get("content-type", "").startswith("application/json")
        ):
            try:
                body = await request.json()
            except ValueError:
                body = {}
            data = body.get("data", {}) if isinstance(body, dict) else {}
            forbidden = {
                "model_profile_id",
                "model_id",
                "profile_id",
                "owner_user_id",
                "agent_snapshots",
                "cognitive_profile_id",
                "trial",
                "general_knowledge_overrides",
            }
            if isinstance(body, dict) and (
                forbidden.intersection(body) or (isinstance(data, dict) and forbidden.intersection(data))
            ):
                return JSONResponse({"detail": "普通账号不能覆盖模型、身份或知识策略"}, status_code=403)
        with identity(actor):
            return await call_next(request)
