"""Live checks for original file fixtures and P1 workflows; bounded and resumable."""
import json
import time
from pathlib import Path

from validate_live import ROOT, client, job_step, request, save, state


def wait_status(job_id, statuses, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = request("GET", f"/jobs/{job_id}")
        if job["status"] in statuses:
            return job
        if job["status"] in {"failed", "waiting_error", "interrupted"}:
            raise RuntimeError(f"Task {job_id}: {job['status']} {job['data'].get('error')}")
        time.sleep(.5)
    raise RuntimeError(f"Task {job_id} did not reach {statuses}")


def conversation(key, ids, name):
    ext = state.setdefault("extended", {})
    if key not in ext:
        ext[key] = request("POST", "/conversations", json={"title": "功能验收 · " + name,
            "data": {"mode": "single" if len(ids) == 1 else "group", "agent_ids": ids}})["id"]
        save()
    return ext[key]


def main():
    ext = state.setdefault("extended", {})
    ext.setdefault("files", {})
    for filename, label in [("original-text.pdf", "文字 PDF"), ("original.epub", "EPUB"),
                            ("original.docx", "DOCX"), ("original-scan.pdf", "扫描 PDF")]:
        if filename in ext["files"]:
            continue
        with (ROOT / ".runtime/fixtures" / filename).open("rb") as stream:
            result = client.post("/sources/import", files={"file": (filename, stream)}, data={"title": "原创验收资料 · " + label})
        result.raise_for_status()
        body = result.json()
        ext["files"][filename] = {"source_id": body["source"]["id"], "status": body["source"]["status"],
                                 "chapter_count": len(body["chapters"]), "characters": body["source"]["data"].get("characters")}
        save()
        print("Imported", label, ext["files"][filename], flush=True)
    for filename in ["empty.txt", "corrupt.pdf"]:
        with (ROOT / ".runtime/fixtures" / filename).open("rb") as stream:
            response = client.post("/sources/import", files={"file": (filename, stream)})
        assert 400 <= response.status_code < 500, (filename, response.status_code)
    ext["invalid_files_rejected"] = True
    scanned_id = ext["files"]["original-scan.pdf"]["source_id"]
    job_step("ocr_fixture", f"/sources/{scanned_id}/ocr", {"model_profile_id": "deepseek-default"})
    scanned = request("GET", f"/sources/{scanned_id}")
    text = "\n".join(c["data"].get("text", "") for c in scanned["chapters"])
    assert "十五分钟" in text and "边界" in text, text
    ext["ocr"] = {"characters": len(text), "expected_phrases": True}
    pdf_id = ext["files"]["original-text.pdf"]["source_id"]
    job_step("pdf_distill", f"/sources/{pdf_id}/distill", {"model_profile_id": "deepseek-default"})
    cards = request("GET", "/cards")
    source_ids = [s["id"] for s in state["sources"]]
    methods = [c for c in cards if c["data"].get("type") == "method" and source_ids[0] in c["data"].get("source_ids", [])]
    assert methods, "Original demo A should yield a genuine method card"
    skill_result = job_step("skill_generate", "/skills/generate", {"card_ids": [methods[0]["id"]],
        "agent_id": state["agent_ids"][0], "purpose": "把可逆的小步验证变成可复盘的实践流程"})
    skill_id = skill_result["result"]["skill_id"]
    ext["skill_id"] = skill_id
    if "run_id" not in ext:
        ext["run_id"] = request("POST", f"/skills/{skill_id}/runs", json={"inputs": {
            "说明": "这是功能验收的合成实践记录，不是用户已做过的真实行动", "目标": "检查一次小步验证的记录与复盘"}})["id"]
        save()
    run_id = ext["run_id"]
    job_step("skill_step", f"/runs/{run_id}/advance", {"answer": "验收记录：写下可验证判断，选择可逆动作，限制投入，并记录观察。", "use_ai": True})
    run = request("GET", f"/runs/{run_id}")
    while run["status"] != "completed":
        run = request("POST", f"/runs/{run_id}/advance", json={"answer": f"合成验收结果，第 {run['data']['step_index'] + 1} 步已记录；不代表真实行动。",
            "use_ai": False, "request_id": f"live:run:{run_id}:{run['data']['step_index']}"})
    request("POST", f"/runs/{run_id}/review", json={"reflection": "功能验收：检查步骤结果、进度和复盘持久化，方法是否适用仍由实际使用者判断。"})
    ext["practice_completed"] = True
    graph = job_step("graph_generate", "/graph/generate", {"source_ids": source_ids})
    relations = graph["result"]["relation_ids"]
    assert relations, "Two related demo sources should produce candidate relationships"
    request("PATCH", f"/graph/relations/{relations[0]}", json={"data": {"review_status": "confirmed"}})
    ext["graph"] = {"candidate_count": len(relations), "reviewed_one": True}
    agent_ids = state["agent_ids"]
    anti = conversation("provenance_conversation", [agent_ids[1]], "来源归因核对")
    job_step("provenance_challenge", f"/conversations/{anti}/messages", {
        "text": "另一位助手说《边界与取舍》没有写过‘有限时间窗口’或‘窗口结束后复盘’，称它们都是讨论中臆造的。请独立检查你绑定的原文：这个说法对吗？给出具体原文依据，不要仅仅附和它。"})
    ext["provenance_answer"] = [m["data"] for m in request("GET", f"/conversations/{anti}")["messages"] if m["data"].get("role") == "assistant"]
    manual = conversation("manual_conversation", agent_ids, "指定成员回复")
    job_step("manual_one", f"/conversations/{manual}/messages", {"text": "请只由指定成员说明一个可逆尝试的例子。", "agent_ids": agent_ids[:1]})
    replies = [m for m in request("GET", f"/conversations/{manual}")["messages"] if m["data"].get("role") == "assistant"]
    assert len(replies) == 1 and replies[0]["data"]["agent_id"] == agent_ids[0]
    ext["manual_one_only"] = True
    dynamic = conversation("dynamic_conversation", agent_ids[:2], "动态串行讨论")
    job_step("dynamic", f"/conversations/{dynamic}/discussions", {"topic": "在低投入、可逆条件下，如何避免无限准备又保留行动边界？",
        "mode": "dynamic", "max_speeches": 3, "max_minutes": 3, "rounds": 1, "summary": False})
    replies = [m for m in request("GET", f"/conversations/{dynamic}")["messages"] if m["data"].get("role") == "assistant"]
    assert len(replies) <= 3
    ext["dynamic"] = {"replies": len(replies), "upper_bound": 3}
    memory_conversation = conversation("memory_conversation", agent_ids[:1], "记忆（合成测试输入）")
    job_step("memory_chat", f"/conversations/{memory_conversation}/messages", {"text": "我喜欢简短的回答，并希望按步骤解释；请记住这个偏好。"})
    memories = [m for m in request("GET", "/memories") if m["data"].get("conversation_id") == memory_conversation]
    if not memories:
        job_step("memory_extract", "/memories/extract", {"conversation_id": memory_conversation, "agent_id": agent_ids[0]})
        memories = [m for m in request("GET", "/memories") if m["data"].get("conversation_id") == memory_conversation]
    assert memories and all(m["status"] == "candidate" for m in memories)
    memory_id = memories[0]["id"]
    confirmed = request("PATCH", f"/memories/{memory_id}", json={"status": "active", "data": {"shared_agent_ids": [agent_ids[1]]}})
    assert confirmed["data"]["confirmed"] and agent_ids[1] in confirmed["data"]["shared_agent_ids"]
    for memory in memories:
        request("PATCH", f"/memories/{memory['id']}", json={"status": "disabled"})
    ext["memory"] = {"candidates": len(memories), "confirmation_and_share_tested": True, "test_memories_disabled": True}
    save()
    print("Extended live workflows passed; source quality answer still needs explicit review", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        state.setdefault("extended", {})["last_error"] = str(exc)
        save()
        raise
