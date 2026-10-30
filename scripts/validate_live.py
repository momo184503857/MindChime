"""Bounded live validation using only the PRD's explicitly original demo texts.

Talks to local business HTTP endpoints; never reads or prints provider keys.
Resumable checkpoints avoid re-running completed paid steps.
"""
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / ".runtime/live-validation.json"
OUTPUT = ROOT / "docs/validation/live-results.json"
client = httpx.Client(base_url="http://127.0.0.1:8765/api/v1", timeout=60, trust_env=False)
state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {"run_id": str(uuid.uuid4()), "steps": {}}


def save():
    CHECKPOINT.parent.mkdir(exist_ok=True)
    CHECKPOINT.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def request(method, path, **kwargs):
    result = client.request(method, path, **kwargs)
    if result.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {result.status_code} {result.text[:1200]}")
    return result.json()


def job_step(name, path, payload):
    existing = state["steps"].get(name)
    if existing and existing.get("status") == "completed":
        return existing
    if existing and existing.get("job_id"):
        job = request("GET", f"/jobs/{existing['job_id']}")
        if job["status"] in {"failed", "waiting_error", "interrupted", "partial"}:
            if "--resume" in sys.argv:
                print(f"Explicit recovery of {name}; existing AI requests are reconciled first", flush=True)
                job = request("POST", f"/jobs/{job['id']}/retry", json={})
            else:
                raise RuntimeError(f"{name} needs explicit review/retry: {job['id']} {job['status']} {job['data'].get('error')}")
    else:
        payload = {**payload, "request_id": f"validation:{state['run_id']}:{name}"}
        job = request("POST", path, json=payload)
        state["steps"][name] = {"job_id": job["id"], "status": job["status"]}
        save()
    print(f"{name}: {job['id']}", flush=True)
    deadline = time.monotonic() + 900
    last_stage = None
    while time.monotonic() < deadline:
        job = request("GET", f"/jobs/{job['id']}")
        stage = job["data"].get("stage")
        if stage != last_stage:
            print(f"  {job['status']}: {stage}", flush=True)
            last_stage = stage
        if job["status"] in {"completed", "partial", "failed", "waiting_error", "interrupted", "cancelled"}:
            usages = [s.get("usage") for s in job["data"].get("steps", {}).values() if s.get("usage")]
            result = {"job_id": job["id"], "status": job["status"], "result": job["data"].get("result"),
                      "error": job["data"].get("error"), "usage": usages}
            state["steps"][name] = result
            save()
            if job["status"] != "completed":
                raise RuntimeError(f"{name}: {job['status']} {job['data'].get('error')}")
            return result
        time.sleep(1)
    raise RuntimeError(f"{name}: waiting exceeded 15 minutes; task remains visible, no automatic replay")


def main():
    from dotenv import dotenv_values
    data_dir = Path(dotenv_values(ROOT / ".env.local").get("MINDCHIME_DATA_DIR") or ROOT / "data")
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    account = next(a for a in json.loads((data_dir / "local-accounts.json").read_text()) if a["username"] == "admin")
    request("POST", "/auth/login", json=account)
    profiles = request("GET", "/profiles")
    state["profiles"] = [{k: p.get(k) for k in ("id", "model", "configured", "version", "capabilities")} for p in profiles]
    for id in ("deepseek-default", "dashscope-embedding"):
        if not any(p["id"] == id and p.get("configured") for p in profiles):
            raise RuntimeError(f"{id} is not configured")
    request("PATCH", "/profiles/deepseek-default", json={"capabilities": {
        "stream": True, "vision": True, "json": True, "embedding": False, "context_tokens": 128000},
        "parameters": {"thinking": {"type": "disabled"}}})
    request("PATCH", "/settings", json={"default_profile_id": "deepseek-default", "purpose_profiles": {
        **{p: "deepseek-default" for p in ("chat", "distill", "agent", "summary", "memory", "ocr", "moderator")},
        "embedding": "dashscope-embedding"}})
    if "connections" not in state:
        state["connections"] = {id: request("POST", f"/profiles/{id}/test", json={})
                                for id in ("deepseek-default", "dashscope-embedding")}
        save()
        print("Provider connection tests passed", flush=True)
    sources = request("POST", "/demo/load", json={})["sources"]
    state["sources"] = [{"id": s["id"], "title": s["title"]} for s in sources]
    save()
    for index, source in enumerate(sources):
        detail = request("GET", f"/sources/{source['id']}")
        selected = [c["id"] for c in detail["chapters"] if c["data"].get("text", "").strip() and len(c["data"]["text"]) > 60]
        job_step(f"distill_{index}", f"/sources/{source['id']}/distill", {
            "chapter_ids": selected, "model_profile_id": "deepseek-default"})
    agent_ids = []
    roles = [(0, [sources[0]["id"]], "将模糊目标转成可逆的小步实验"),
             (1, [sources[1]["id"]], "审视行动代价和边界"),
             (2, [s["id"] for s in sources], "比较两种方法的适用前提，保留分歧")]
    for index, ids, purpose in roles:
        result = job_step(f"agent_{index}", "/agents/generate", {"source_ids": ids, "purpose": purpose,
                          "count": 1, "model_profile_id": "deepseek-default"})
        agent = result["result"]["agents"][0]
        request("PATCH", f"/agents/{agent['id']}", json={"status": "available"})
        agent_ids.append(agent["id"])
    state["agent_ids"] = agent_ids
    if "conversation_id" not in state:
        conversation = request("POST", "/conversations", json={"title": "原创资料 · 三方方法讨论", "data": {
            "mode": "group", "agent_ids": agent_ids, "background": "工作之外想做新项目，但时间有限，担心三分钟热度也担心一直准备。"}})
        state["conversation_id"] = conversation["id"]
        save()
    job_step("discussion", f"/conversations/{state['conversation_id']}/discussions", {
        "topic": "面对工作外的新项目，应该先做小步尝试，还是先想清楚目标和边界？请回应彼此的具体观点。",
        "mode": "ordered", "rounds": 3, "summary": True})
    conversation = request("GET", f"/conversations/{state['conversation_id']}")
    messages = [m for m in conversation["messages"] if m["data"].get("role") == "assistant"]
    state["discussion_checks"] = {"assistant_messages": len(messages), "expected_max": 9,
        "citations": sum(len(m["data"].get("references", [])) for m in messages),
        "responding_messages": sum(bool(m["data"].get("response_to")) for m in messages),
        "rounds": sorted({m["data"].get("round", 0) for m in messages})}
    assert len(messages) == 9, "Expected exactly nine completed member replies"
    assert all(m["data"].get("response_to") for m in messages if m["data"].get("round", 0) > 1)
    if "single_id" not in state:
        state["single_id"] = request("POST", "/conversations", json={"title": "原创资料 · 无依据反向测试", "data": {
            "mode": "single", "agent_ids": agent_ids[:1]}})["id"]
        save()
    job_step("negative_question", f"/conversations/{state['single_id']}/messages", {
        "text": "资料A的作者曾经在哪个大学做过这项研究？请给我研究年份。"})
    negative = request("GET", f"/conversations/{state['single_id']}")
    state["negative_answer"] = [m["data"] for m in negative["messages"] if m["data"].get("role") == "assistant"]
    state["status"] = "core_live_passed_requires_human_quality_review"
    save()
    print("Core live validation complete; see docs/validation/live-results.json", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        state["last_error"] = str(exc)
        save()
        raise
