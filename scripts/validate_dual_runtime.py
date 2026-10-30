"""Real-model runtime continuation after manually checking the fictional fixtures.

Reviewed 2026-10-30: rules 2/4/8/9 match the complete original fixture texts;
all six basic knowledge cards are faithful statements/methods from those texts.
The expression-style rule remains a candidate. Temporary QA publications are
withdrawn at the end; no existing user asset is published by this script.
"""

import json
from pathlib import Path

from dotenv import dotenv_values
from validate_dual_distillation import ROOT, request, save, state, wait_job


def main():
    folder = Path(dotenv_values(ROOT / ".env.local").get("MINDCHIME_DATA_DIR") or ROOT / "data")
    if not folder.is_absolute():
        folder = ROOT / folder
    accounts = json.loads((folder / "local-accounts.json").read_text())
    admin = next(a for a in accounts if a["username"] == "admin")
    user = next(a for a in accounts if a["username"] == "user")
    request("POST", "/auth/login", json=admin)
    result = request("GET", "/distillations/" + state["knowledge_result_id"])
    cards = result["cards"]
    for card in cards:
        request(
            "POST",
            "/reviews/" + card["id"],
            json={
                "version": card["version"],
                "decision": "verified",
                "note": "原创验收资料逐项核对：内容与逐字引用一致。",
            },
        )
    profile = request("GET", "/cognitive-profiles/" + state["cognitive_profile_id"])
    approved = {"rule-2", "rule-4", "rule-8", "rule-9"}
    if profile["status"] != "active" or not all(
        r["review_status"] == "verified" for r in profile["data"]["rules"] if r["id"] in approved
    ):
        profile = request(
            "PATCH",
            "/cognitive-profiles/" + profile["id"],
            json={
                "rules": [
                    {
                        "id": r["id"],
                        "review_status": "verified",
                        "review_note": "逐项对照原创虚构资料；仅确认有证据的规则及其边界。",
                    }
                    for r in profile["data"]["rules"]
                    if r["id"] in approved
                ],
                "status": "active",
            },
        )
    state["review"] = {
        "thought_rules": sorted(approved),
        "retained_candidate": "rule-1",
        "knowledge_cards": len(cards),
        "note": "实际逐项核对原创材料；不将模型自评作为人工审核。",
    }
    save()
    source = request("GET", "/sources/" + state["sources"][0])["source"]
    if source["data"].get("active_distillation_id") != state["knowledge_result_id"]:
        request("POST", "/distillations/" + state["knowledge_result_id"] + "/activate", json={})
    qa_publications = []
    for sid in state["sources"]:
        source = request("GET", "/sources/" + sid)["source"]
        required = profile["data"]["source_versions"][sid]
        request("POST", "/publications/" + sid + "?version=" + str(required), json={})
        if source["version"] != required:
            request("POST", "/publications/" + sid, json={})
        qa_publications.append(sid)
    for id in (state["person_id"], state["knowledge_result_id"], profile["id"], state["thought_result_id"]):
        request("POST", "/publications/" + id, json={})
        qa_publications.append(id)
    definitions = {
        "knowledge": {
            "source_ids": [state["sources"][0]],
            "distillation_ids": {state["sources"][0]: state["knowledge_result_id"]},
        },
        "thought": {"cognitive_profile_id": profile["id"], "cognitive_profile_version": profile["version"]},
        "combined": {
            "source_ids": [state["sources"][0]],
            "distillation_ids": {state["sources"][0]: state["knowledge_result_id"]},
            "cognitive_profile_id": profile["id"],
            "cognitive_profile_version": profile["version"],
        },
    }
    state.setdefault("runtime_agents", {})
    for kind, data in definitions.items():
        if kind not in state["runtime_agents"]:
            a = request(
                "POST",
                "/agents",
                json={
                    "title": "原创验收 " + kind,
                    "data": {
                        **data,
                        "purpose": "根据原创虚构测试材料解释小尝试、真实观察与适用边界。",
                        "general_knowledge": False,
                    },
                },
            )
            assert a["data"]["agent_type"] == kind
            state["runtime_agents"][kind] = a["id"]
            save()
        aid = state["runtime_agents"][kind]
        if aid != state.get("deleted_qa_agent_id"):
            request("POST", "/publications/" + aid, json={})
            qa_publications.append(aid)
    method_cards = [c["id"] for c in cards if c["data"]["type"] in {"method", "boundary"}]
    skill_result = wait_job(
        "independent_skill_generate",
        "/skills/generate",
        {
            "card_ids": method_cards,
            "purpose": "用三步记录法完成一次小练习，明确代价可承受、可停止的边界；步骤简短，不绑定人物。",
        },
    )
    skill_id = skill_result["skill_id"]
    state["independent_skill_id"] = skill_id
    save()
    skill = request("GET", "/skills/" + skill_id)
    assert not skill["data"].get("agent_id")
    request("POST", "/publications/" + skill_id, json={})
    qa_publications.append(skill_id)
    request("POST", "/auth/login", json=user)
    state.setdefault("runtime_conversations", {})
    state.setdefault("runtime_answers", {})
    for kind, aid in state["runtime_agents"].items():
        if kind not in state["runtime_conversations"]:
            conv = request(
                "POST",
                "/conversations",
                json={"title": "原创验收 " + kind + " 对话", "data": {"mode": "single", "agent_ids": [aid]}},
            )
            state["runtime_conversations"][kind] = conv["id"]
            save()
        cid = state["runtime_conversations"][kind]
        wait_job(
            "chat_" + kind,
            "/conversations/" + cid + "/messages",
            {"text": "根据材料，小尝试适用于什么情境？请区分资料观点和你对新问题的模拟分析。"},
        )
        detail = request("GET", "/conversations/" + cid)
        assistant = next(m for m in reversed(detail["messages"]) if m["data"].get("role") == "assistant")
        assert assistant["data"].get("references"), "Expected genuine source citations for " + kind
        state["runtime_answers"][kind] = {
            "message_id": assistant["id"],
            "basis": assistant["data"].get("basis"),
            "references": len(assistant["data"]["references"]),
            "text": assistant["data"]["text"],
        }
        save()
    if "runtime_run_id" not in state:
        run = request(
            "POST",
            "/skills/" + skill_id + "/runs",
            json={
                "inputs": {
                    name: "做一次五分钟阅读练习，记录卡住的位置，代价可承受且随时可停止。"
                    for name in skill["data"].get("inputs", [])
                }
            },
        )
        assert "agent_id" not in run["data"]
        state["runtime_run_id"] = run["id"]
        save()
    request("POST", "/auth/login", json=admin)
    if "deleted_qa_agent_id" not in state:
        aid = state["runtime_agents"]["thought"]
        request("DELETE", "/agents/" + aid)
        state["deleted_qa_agent_id"] = aid
        save()
    request("POST", "/auth/login", json=user)
    wait_job(
        "independent_guidance_after_agent_delete",
        "/runs/" + state["runtime_run_id"] + "/advance",
        {
            "answer": "我准备先做五分钟练习，记录卡住的位置；不把结果外推到不能撤回的重大决定。",
            "use_ai": True,
        },
    )
    run = request("GET", "/runs/" + state["runtime_run_id"])
    assert run["data"]["step_index"] == 1 and run["data"]["results"][0]["guidance"].strip()
    state["practice_verification"] = {
        "step_index": run["data"]["step_index"],
        "guidance": run["data"]["results"][0]["guidance"],
        "agent_binding_absent": not run["data"].get("agent_id"),
        "deleted_agent_did_not_block": True,
    }
    save()
    # Withdraw only the exact, newly-created QA publications; admin can still inspect them.
    request("POST", "/auth/login", json=admin)
    for id in qa_publications:
        request("DELETE", "/publications/" + id)
    state["temporary_publications_withdrawn"] = True
    save()
    print(
        json.dumps(
            {
                "verified_types": list(state["runtime_answers"]),
                "skill_guidance_after_agent_delete": True,
                "temporary_publications_withdrawn": True,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
