"""Local AI-only persistence; private request payloads and credentials are encrypted."""

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet

TERMINAL = {"completed", "failed", "cancelled", "interrupted", "acknowledged"}


def now():
    return datetime.now(UTC).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ConflictError(ValueError):
    pass


@contextmanager
def single_instance(directory):
    """Cross-platform process guard, separate from the writable request database."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "service.lock.sqlite3"
    connection = sqlite3.connect(path, timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError:
        connection.close()
        raise RuntimeError(
            "同一 AI 数据目录已有服务运行；请先停止旧实例，不要使用多个 Uvicorn worker。"
        ) from None
    os.chmod(path, 0o600)
    try:
        yield
    finally:
        connection.rollback()
        connection.close()


class Store:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "ai.sqlite3"
        self.lock = threading.RLock()
        key_path = self.directory / "encryption.key"
        if not key_path.exists():
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(Fernet.generate_key())
            except FileExistsError:
                pass
        self.cipher = Fernet(key_path.read_bytes())
        os.chmod(key_path, 0o600)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, body TEXT NOT NULL,
                    credential_id TEXT, deleted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_versions (
                    id TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL,
                    credential_id TEXT, created_at TEXT NOT NULL, PRIMARY KEY(id, version)
                );
                CREATE TABLE IF NOT EXISTS credentials (
                    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, encrypted TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_tests (
                    id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
                    checked_at TEXT NOT NULL, error_code TEXT, PRIMARY KEY(id,version)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                    profile_id TEXT NOT NULL, profile_version INTEGER NOT NULL,
                    operation TEXT NOT NULL, payload TEXT, result TEXT, error TEXT,
                    usage TEXT, finish_reason TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
                    event TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_request ON events(request_id,id);
                CREATE INDEX IF NOT EXISTS requests_status ON requests(status);
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        with self.lock:
            conn = sqlite3.connect(self.path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("PRAGMA secure_delete=ON")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    def encrypt(self, value):
        return self.cipher.encrypt(canonical(value).encode()).decode()

    def decrypt(self, value):
        return json.loads(self.cipher.decrypt(value.encode())) if value else None

    def _public_profile(self, row, conn):
        profile = json.loads(row["body"])
        has_key = bool(
            row["credential_id"]
            and conn.execute("SELECT 1 FROM credentials WHERE id=?", (row["credential_id"],)).fetchone()
        )
        test = conn.execute(
            "SELECT * FROM profile_tests WHERE id=? AND version=?", (row["id"], row["version"])
        ).fetchone()
        return {
            **profile,
            "id": row["id"],
            "version": row["version"],
            "configured": profile["protocol"] == "ollama" or has_key,
            "has_api_key": has_key,
            "created_at": row["created_at"],
            "test_status": test["status"] if test else "untested",
            "last_test_at": test["checked_at"] if test else None,
            "last_test_error": test["error_code"] if test else None,
        }

    def record_test(self, profile_id, version, success, error_code=None):
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO profile_tests VALUES (?,?,?,?,?)
                ON CONFLICT(id,version) DO UPDATE SET status=excluded.status,
                checked_at=excluded.checked_at,error_code=excluded.error_code""",
                (profile_id, version, "passed" if success else "failed", now(), error_code),
            )

    def profiles(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM profiles WHERE deleted=0 ORDER BY created_at,id").fetchall()
            return [self._public_profile(row, conn) for row in rows]

    def profile(self, profile_id, version=None, private=False):
        with self.connection() as conn:
            if version is None:
                row = conn.execute(
                    "SELECT * FROM profiles WHERE id=? AND deleted=0", (profile_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM profile_versions WHERE id=? AND version=?", (profile_id, version)
                ).fetchone()
            if not row:
                return None
            profile = self._public_profile(row, conn)
            if private:
                secret = conn.execute(
                    "SELECT encrypted FROM credentials WHERE id=?", (row["credential_id"],)
                ).fetchone()
                profile["api_key"] = self.decrypt(secret["encrypted"]) if secret else None
            return profile

    def profile_versions(self, profile_id):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM profile_versions WHERE id=? ORDER BY version DESC", (profile_id,)
            ).fetchall()
            return [self._public_profile(row, conn) for row in rows]

    def save_profile(self, data, profile_id=None, expected_version=None):
        data = dict(data)
        api_key = data.pop("api_key", ...)
        supplied_id = data.pop("id", None)
        profile_id = profile_id or supplied_id or str(uuid.uuid4())
        timestamp = now()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
            if old and old["deleted"]:
                raise ConflictError("该配置编号已经删除，请使用新编号")
            if expected_version is not None and (not old or old["version"] != expected_version):
                raise ConflictError("模型配置已修改，请刷新后重试")
            version = old["version"] + 1 if old else 1
            body = {**json.loads(old["body"]), **data} if old else data
            credential_id = old["credential_id"] if old else None
            if api_key is not ...:
                credential_id = None
                if api_key:
                    credential_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO credentials VALUES (?,?,?)",
                        (credential_id, profile_id, self.encrypt(api_key)),
                    )
            serialized = canonical(body)
            conn.execute(
                """INSERT INTO profiles VALUES (?,?,?,?,0,?,?)
                ON CONFLICT(id) DO UPDATE SET version=excluded.version,body=excluded.body,
                credential_id=excluded.credential_id,updated_at=excluded.updated_at""",
                (profile_id, version, serialized, credential_id, timestamp, timestamp),
            )
            conn.execute(
                "INSERT INTO profile_versions VALUES (?,?,?,?,?)",
                (profile_id, version, serialized, credential_id, timestamp),
            )
        return self.profile(profile_id)

    def delete_profile(self, profile_id):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT id FROM requests WHERE profile_id=? AND status IN ('queued','running')", (profile_id,)
            ).fetchall()
            if active:
                raise ConflictError("该配置仍有未完成 AI 请求，请先结束相关任务")
            conn.execute("UPDATE profiles SET deleted=1,updated_at=? WHERE id=?", (now(), profile_id))
            conn.execute("DELETE FROM credentials WHERE profile_id=?", (profile_id,))

    @staticmethod
    def fingerprint(payload):
        return hashlib.sha256(canonical(payload).encode()).hexdigest()

    def find_request(self, request_id, fingerprint=None):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row and fingerprint and row["fingerprint"] != fingerprint:
                raise ConflictError("request_id 已用于不同内容，请为新请求使用新编号")
            return self._request(row) if row else None

    def _request(self, row):
        result = {
            key: row[key]
            for key in (
                "id",
                "status",
                "profile_id",
                "profile_version",
                "operation",
                "finish_reason",
                "created_at",
                "updated_at",
            )
        }
        for key in ("result", "error", "usage"):
            result[key] = (
                self.decrypt(row[key]) if key == "result" else (json.loads(row[key]) if row[key] else None)
            )
        return result

    def create_request(self, payload, profile_version, fingerprint):
        request_id = payload["request_id"]
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ConflictError("request_id 已用于不同内容，请使用新编号")
                return self._request(old), False
            timestamp = now()
            payload = {**payload, "profile_version": profile_version}
            conn.execute(
                """INSERT INTO requests
                (id,fingerprint,status,profile_id,profile_version,operation,payload,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    request_id,
                    fingerprint,
                    "queued",
                    payload["profile_id"],
                    profile_version,
                    payload["operation"],
                    self.encrypt(payload),
                    timestamp,
                    timestamp,
                ),
            )
        return self.find_request(request_id), True

    def payload(self, request_id):
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM requests WHERE id=?", (request_id,)).fetchone()
            return self.decrypt(row["payload"]) if row else None

    def _event(self, conn, request_id, event, data):
        conn.execute(
            "INSERT INTO events(request_id,event,payload,created_at) VALUES (?,?,?,?)",
            (request_id, event, self.encrypt(data), now()),
        )

    def emit(self, request_id, event, data):
        with self.connection() as conn:
            row = conn.execute("SELECT status FROM requests WHERE id=?", (request_id,)).fetchone()
            if row and row["status"] not in TERMINAL:
                self._event(conn, request_id, event, data)

    def transition(self, request_id, status, *, result=None, error=None, usage=None, finish_reason=None):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM requests WHERE id=?", (request_id,)).fetchone()
            if not row or row["status"] in TERMINAL:
                return False
            conn.execute(
                """UPDATE requests SET status=?,result=?,error=?,usage=?,finish_reason=?,updated_at=?
                WHERE id=?""",
                (
                    status,
                    self.encrypt(result) if result is not None else None,
                    canonical(error) if error else None,
                    canonical(usage) if usage else None,
                    finish_reason,
                    now(),
                    request_id,
                ),
            )
            event = "started" if status == "running" else "failed" if status == "interrupted" else status
            self._event(
                conn,
                request_id,
                event,
                {
                    "id": request_id,
                    "status": status,
                    "result": result,
                    "error": error,
                    "usage": usage,
                    "finish_reason": finish_reason,
                },
            )
            return True

    def events(self, request_id, after=0):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE request_id=? AND id>? ORDER BY id LIMIT 500", (request_id, after)
            ).fetchall()
            return [
                {"id": row["id"], "event": row["event"], "data": self.decrypt(row["payload"])} for row in rows
            ]

    def interrupt_pending(self):
        with self.connection() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM requests WHERE status IN ('queued','running')"
                ).fetchall()
            ]
        for request_id in ids:
            self.transition(
                request_id,
                "interrupted",
                error={
                    "code": "service_interrupted",
                    "message": "AI 服务已中断；已完成结果保留，此请求不会自动重发，请在业务任务中确认恢复。",
                    "retryable": False,
                },
            )
        return len(ids)

    def acknowledge(self, request_id):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                return False
            if row["status"] not in TERMINAL:
                raise ConflictError("AI 请求尚未结束，不能确认清除")
            conn.execute(
                """UPDATE requests SET status='acknowledged',payload=NULL,result=NULL,
                error=NULL,updated_at=? WHERE id=?""",
                (now(), request_id),
            )
            conn.execute("DELETE FROM events WHERE request_id=?", (request_id,))
            self._event(conn, request_id, "acknowledged", {"id": request_id, "status": "acknowledged"})
        return True
