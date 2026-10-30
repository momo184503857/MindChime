"""Bounded, resumable real-model checks with explicitly fictional original sources.

Intentionally incurs configured model usage. No networking research is enabled.
Check generated rules/cards manually before running review/publish tests.
"""

import json
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / ".runtime" / "dual-live.json"
OUTPUT = ROOT / "docs" / "validation" / "dual-distillation-live.json"
state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {"sources": [], "jobs": {}}
client = httpx.Client(base_url="http://127.0.0.1:8765/api/v1", timeout=90, trust_env=False)


def request(method, path, **kwargs):
    r = client.request(method, path, **kwargs)
    if not r.is_success:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:500]}")
    return r.json()


def save():
    CHECKPOINT.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def wait_job(name, path, payload):
    if name not in state["jobs"]:
        job = request(
            "POST", path, json={**payload, "request_id": "dual-validation:" + name + ":" + state["person_id"]}
        )
        state["jobs"][name] = {"id": job["id"]}
        save()
    jid = state["jobs"][name]["id"]
    previous = ""
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        job = request("GET", "/jobs/" + jid)
        stage = job["data"].get("stage", "")
        if stage != previous:
            print(name, job["status"], stage, flush=True)
            previous = stage
        if job["status"] in {"completed", "waiting_error", "failed", "partial", "interrupted", "cancelled"}:
            state["jobs"][name] = {
                "id": jid,
                "status": job["status"],
                "result": job["data"].get("result"),
                "error": job["data"].get("error"),
                "calls": [
                    {
                        "step": key,
                        "profile_id": value.get("profile_id"),
                        "profile_version": value.get("profile_version"),
                        "usage": value.get("usage"),
                    }
                    for key, value in job["data"].get("steps", {}).items()
                ],
            }
            save()
            if job["status"] != "completed":
                raise RuntimeError(
                    name + " requires review; no automatic retry: " + str(job["data"].get("error"))
                )
            return job["data"]["result"]
        time.sleep(1)
    raise RuntimeError("Timed out; task remains inspectable, not automatically retried")


def main():
    folder = Path(dotenv_values(ROOT / ".env.local").get("MINDCHIME_DATA_DIR") or ROOT / "data")
    if not folder.is_absolute():
        folder = ROOT / folder
    account = next(
        a for a in json.loads((folder / "local-accounts.json").read_text()) if a["username"] == "admin"
    )
    request("POST", "/auth/login", json=account)
    state["research_config"] = request("GET", "/research/config")
    state["allow_network"] = False
    if "person_id" not in state:
        person = request(
            "POST",
            "/persons",
            json={
                "title": "原创验收人物：林澄（虚构）",
                "data": {"description": "仅用于软件验收的虚构人物，不对应真实人物。"},
            },
        )
        state["person_id"] = person["id"]
        save()
    texts = [
        (
            "原创验收：林澄的记录方法",
            "第一章 活动筹备\n林澄是用于软件测试的虚构人物。组织小型读书活动时，林澄说：先写下要回答的问题，再记录实际观察，最后根据记录决定下一步。他先邀请两位朋友试读，收集不理解的句子，再调整活动说明。\n第二章 学习练习\n面对新的学习任务，林澄仍说：先写下要回答的问题，再记录实际观察，最后根据记录决定下一步。他做一次五分钟练习，记录卡住的位置，再选择下一次练习。林澄强调，小尝试只适用于代价可承受、能够停止的情境，不适用于不能撤回的重大决定。",
        ),
        (
            "原创验收：与林澄的问答",
            "第一章 原创问答\n问：如果记录不支持原来的想法，你会怎么办？\n林澄答：保留与原想法不一致的记录，改变下一步的尝试，不把反例删掉。\n问：你能预测所有事情吗？\n林澄答：资料没有覆盖的问题，我不知道；这套办法也不能保证结果。\n问：你如何表达建议？\n林澄答：我通常先说结论，再给一个具体观察，最后说明不能外推的条件。\n第二章 失败边界\n林澄不把失败归因于别人不努力。他先检查问题是否清楚、观察是否真实、尝试的代价是否可接受。他不会为了让记录支持自己而修改已经发生的事实。",
        ),
    ]
    for index, (title, text) in enumerate(texts):
        if len(state["sources"]) <= index:
            value = request(
                "POST",
                "/sources/paste",
                json={
                    "title": title,
                    "text": text,
                    "duplicate_action": "copy",
                    "author": "MindChime 原创虚构验收资料",
                },
            )
            state["sources"].append(value["source"]["id"])
            save()
    result = wait_job(
        "knowledge",
        "/distillations",
        {
            "distillation_type": "knowledge",
            "source_ids": [state["sources"][0]],
            "method_id": "basic",
            "prompt": "只提炼有原文依据的小步观察方法及其适用边界，不添加外部信息。",
        },
    )
    state["knowledge_result_id"] = result.get("distillation_id")
    save()
    result = wait_job(
        "thought",
        "/distillations",
        {
            "distillation_type": "thought",
            "person_id": state["person_id"],
            "source_ids": state["sources"],
            "allow_network": False,
            "prompt": "这是明确标注的虚构测试人物。只提炼三条证据清楚的决策启发式，包含触发、行为和边界。其余维度资料不足则留空；不要编造真实人物事迹或凑数量。",
        },
    )
    state["cognitive_profile_id"] = result["cognitive_profile_id"]
    state["thought_result_id"] = result["distillation_id"]
    save()
    profile = request("GET", "/cognitive-profiles/" + state["cognitive_profile_id"])
    print(
        json.dumps(
            {
                "profile_id": profile["id"],
                "rules": len(profile["data"]["rules"]),
                "research_configured": state["research_config"]["configured"],
                "report": str(OUTPUT),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
