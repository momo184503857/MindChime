#!/usr/bin/env python3
"""Start, stop and inspect only the processes owned by this workspace."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import time
import urllib.request
from urllib.error import URLError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
PIDS = RUNTIME / "processes.json"


def environment():
    from dotenv import dotenv_values
    env = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env.local").items() if v is not None}}
    data = Path(env.get("MINDCHIME_DATA_DIR") or ROOT / "data")
    if not data.is_absolute():
        data = ROOT / data
    data.mkdir(parents=True, exist_ok=True)
    env["MINDCHIME_DATA_DIR"] = str(data.resolve())
    token_path = data / ".service-token"
    if not env.get("MINDCHIME_AI_TOKEN"):
        if not token_path.exists():
            fd = os.open(token_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(48))
        env["MINDCHIME_AI_TOKEN"] = token_path.read_text().strip()
    env["PYTHONPATH"] = str(ROOT / "services")
    env["PYTHONUNBUFFERED"] = "1"
    env["MINDCHIME_API_PORT"] = env.get("MINDCHIME_API_PORT") or "8765"
    env["MINDCHIME_AI_PORT"] = env.get("MINDCHIME_AI_PORT") or "8766"
    env["MINDCHIME_WEB_PORT"] = env.get("MINDCHIME_WEB_PORT") or "5173"
    env["MINDCHIME_AI_URL"] = f"http://127.0.0.1:{env['MINDCHIME_AI_PORT']}"
    env["VITE_API_TARGET"] = f"http://127.0.0.1:{env['MINDCHIME_API_PORT']}"
    return env


def records():
    try:
        return json.loads(PIDS.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def alive(item):
    if not item:
        return False
    try:
        os.kill(item["pid"], 0)
        # Avoid stopping an unrelated process after a PID has been reused.
        command = subprocess.check_output(["ps", "-p", str(item["pid"]), "-o", "command="], text=True).strip()
        return item["marker"] in command and not command.startswith("<defunct>")
    except (OSError, subprocess.SubprocessError):
        return False


def healthy(url):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2) as response:
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


def status():
    env = environment()
    current = records()
    result = {name: {"running": alive(item), "pid": item["pid"]} for name, item in current.items()}
    result["health"] = {"api": healthy(f"http://127.0.0.1:{env['MINDCHIME_API_PORT']}/api/v1/health"),
                        "ai": healthy(f"http://127.0.0.1:{env['MINDCHIME_AI_PORT']}/health"),
                        "web": healthy(f"http://127.0.0.1:{env['MINDCHIME_WEB_PORT']}")}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return all(result["health"].values()) and alive(current.get("worker"))


def stop():
    current = records()
    for name in ("worker", "api", "ai", "web"):
        item = current.get(name)
        if not alive(item):
            continue
        os.killpg(item["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while alive(item) and time.monotonic() < deadline:
            time.sleep(.2)
        if alive(item):
            os.killpg(item["pid"], signal.SIGKILL)
        print(f"Stopped {name}")
    PIDS.unlink(missing_ok=True)


def start():
    import shutil
    env = environment()
    if any(alive(item) for item in records().values()):
        print("已有本项目进程运行。请先运行 status，或 stop 后重新 start。")
        return 1
    for key in ("MINDCHIME_API_PORT", "MINDCHIME_AI_PORT", "MINDCHIME_WEB_PORT"):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", int(env[key])))
            except OSError as exc:
                if isinstance(exc, PermissionError):
                    print(f"当前执行环境禁止监听本机端口 {env[key]}，请允许本地服务运行。")
                else:
                    print(f"端口 {env[key]} 不可用，请检查占用或修改 .env.local 中的 {key}。")
                return 1
    python = ROOT / ".venv/bin/python"
    pnpm = shutil.which("pnpm")
    if not python.exists() or not pnpm or not (ROOT / "web/node_modules").exists():
        print("请先运行 uv sync 和 pnpm --dir web install。")
        return 1
    RUNTIME.mkdir(parents=True, exist_ok=True)
    migration = subprocess.run([str(python), "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=False)
    if migration.returncode:
        print("数据库迁移失败，服务尚未启动。")
        return migration.returncode
    commands = {
        "ai": ([str(python), "-m", "uvicorn", "ai_service.app:app", "--host", "127.0.0.1", "--port", env["MINDCHIME_AI_PORT"]], "ai_service.app:app"),
        "api": ([str(python), "-m", "uvicorn", "mindchime.main:app", "--host", "127.0.0.1", "--port", env["MINDCHIME_API_PORT"]], "mindchime.main:app"),
        "worker": ([str(python), "-m", "mindchime.worker"], "mindchime.worker"),
        "web": ([pnpm, "--dir", str(ROOT / "web"), "dev", "--host", "127.0.0.1", "--port", env["MINDCHIME_WEB_PORT"], "--strictPort"], str(ROOT / "web")),
    }
    current = {}
    for name, (command, marker) in commands.items():
        with (RUNTIME / f"{name}.log").open("ab") as logfile:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=logfile, stderr=logfile, start_new_session=True)
        current[name] = {"pid": process.pid, "marker": marker, "started_at": time.time()}
        PIDS.write_text(json.dumps(current))
        os.chmod(PIDS, 0o600)
        if name in {"ai", "api"}:
            url = f"http://127.0.0.1:{env['MINDCHIME_AI_PORT']}/health" if name == "ai" else f"http://127.0.0.1:{env['MINDCHIME_API_PORT']}/api/v1/health"
            deadline = time.monotonic() + 20
            while not healthy(url) and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.25)
            if not healthy(url):
                print(f"{name} 启动失败，请查看 .runtime/{name}.log")
                stop()
                return 1
    deadline = time.monotonic() + 20
    while not healthy(f"http://127.0.0.1:{env['MINDCHIME_WEB_PORT']}") and time.monotonic() < deadline:
        time.sleep(.25)
    print(f"MindChime: http://127.0.0.1:{env['MINDCHIME_WEB_PORT']}")
    return 0 if status() else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status", "restart"])
    args = parser.parse_args()
    if args.action in {"stop", "restart"}:
        stop()
    if args.action in {"start", "restart"}:
        raise SystemExit(start())
    if args.action == "status":
        raise SystemExit(0 if status() else 1)
