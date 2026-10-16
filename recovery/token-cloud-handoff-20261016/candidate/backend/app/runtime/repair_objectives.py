"""保留原始验收缺陷，并以真实运行和独立脚本审查核销。"""

import json
from pathlib import Path

from .prompt_registry import load_prompt


PATH = "evidence/repair-objectives.json"


def load(root: Path) -> dict:
    """读取独立目标账本，不从最新错误报告反推原始目标。"""
    path = root / PATH
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"items": []}


def capture(root: Path, triage: dict) -> None:
    """按验收事件保存原始目标和失败证据，重复消费时保持原文。"""
    from . import worker as w
    if triage.get("classification") not in {
            "implementation_defect", "dev_design_defect", "architecture_defect"}:
        return
    ledger = load(root)
    event_id = triage["event_id"]
    if any(item["event_id"] == event_id for item in ledger["items"]):
        return
    changes = triage.get("changes") or [{}]
    report = root / "evidence/verification-report.md"
    for index, change in enumerate(changes, 1):
        ledger["items"].append({
            "id": f"E{event_id}-{index}", "event_id": event_id, "status": "open",
            "original_feedback": triage["user_feedback"],
            "current_behavior": change.get("current_behavior"),
            "expected_behavior": change.get("expected_behavior"),
            "reproduction_examples": change.get("acceptance_examples", []),
            "original_verification_report": report.read_text(encoding="utf-8") if report.is_file() else "",
        })
    w.write_json_atomic(root / PATH, ledger)


def pending(task) -> list[dict]:
    """产品或脚本变化后重新暴露已关闭目标，防止复用旧版本证明。"""
    from . import worker as w
    hashes = w.product_code_hashes(task)
    return [item for item in load(w.workspace_for(task))["items"]
            if item["status"] != "closed" or item.get("verified_hashes") != hashes]


def record_blocker(task, reason: str) -> None:
    """保存最新阻塞并保留每次失败，不覆盖原始验收目标。"""
    from . import worker as w
    root = w.workspace_for(task)
    ledger = load(root)
    if not ledger["items"]:
        return
    ledger.setdefault("blockers", []).append({"repair_round": task.repair_round, "reason": reason})
    w.write_json_atomic(root / PATH, ledger)


def accept_by_user(task, event_id: int) -> None:
    """仅用户已批准的当前提交关闭原始目标，保留历史模型审查记录。"""
    from . import worker as w
    root = w.workspace_for(task)
    ledger = load(root)
    hashes = w.product_code_hashes(task)
    # 用户批准覆盖当前待确认目标，记录明确来源，不伪造模型覆盖结果。
    for item in ledger['items']:
        if item['status'] != 'closed' or item.get('verified_hashes') != hashes:
            item.update(status='closed', verified_hashes=hashes,
                        verification_source='user_acceptance', acceptance_event_id=event_id)
    w.write_json_atomic(root / PATH, ledger)


def verify(db, task, run, tools, browser_result) -> bool:
    """真实浏览器成功后，独立核对每个原始目标的操作与断言依据。"""
    from . import worker as w
    objectives = pending(task)
    if not objectives:
        return True
    if not w.browser_validation_passed(browser_result):
        return False
    root = w.workspace_for(task)
    script = (root / "product/verify_product.py").read_text(encoding="utf-8")
    hashes = w.product_code_hashes(task)
    from .repair_runtime import load as load_repair
    repair = load_repair(root)
    test_diff = {}
    if repair and repair.get('submission_ref'):
        # 审查同时看到原测试差异，避免只凭修改后的通过结果核销目标。
        test_diff = json.loads((root / repair['submission_ref']).read_text()).get('test_diff', {})
    response = w.model_tool_loop(
        db, task, run, load_prompt("repair-objective-reviewer"),
        "核对原始验收目标是否在这次实际执行的浏览器脚本中得到验证。",
        {"objectives": objectives, "browser_script": script,
         "actual_browser_result": browser_result.__dict__, 'test_diff_from_original': test_diff}, tools, tool_schemas=[],
        history_key=f"repair-objectives:{run.id}:{w.content_hash(script)[:12]}")
    try:
        review = json.loads(response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        results = review["results"]
        ids = {item["id"] for item in objectives}
        if not isinstance(results, list) or len(results) != len(ids) \
                or {item["id"] for item in results} != ids:
            raise ValueError("repair_objective_review_ids_invalid")
        for item in results:
            if not isinstance(item["covered"], bool) or not isinstance(item.get("reason"), str):
                raise ValueError("repair_objective_review_invalid")
            if item["covered"] and (not isinstance(item.get("operation_quote"), str)
                    or not item["operation_quote"].strip() or item["operation_quote"] not in script
                    or not isinstance(item.get("assertion_quote"), str)
                    or not item["assertion_quote"].strip() or item["assertion_quote"] not in script):
                raise ValueError("repair_objective_review_quote_invalid")
        if hashes != w.product_code_hashes(task):
            raise ValueError("repair_objective_code_changed")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        results = [{"id": item["id"], "covered": False, "reason": str(exc)} for item in objectives]
    # 每个目标分别记录结果，未覆盖目标继续存在，其他测试成功不得替代它。
    ledger = load(root)
    by_id = {item["id"]: item for item in results}
    for item in ledger["items"]:
        if item["id"] in by_id:
            item["latest_review"] = by_id[item["id"]]
            item["status"] = "closed" if by_id[item["id"]]["covered"] else "open"
            item["verified_hashes"] = hashes if item["status"] == "closed" else None
    w.write_json_atomic(root / PATH, ledger)
    passed = all(item["covered"] for item in results)
    w.safe_record_trace(db, task, run, "repair_objectives", "succeeded" if passed else "failed",
                        "原始验收目标复核", "已核对" if passed else "仍有未闭合目标", {"results": results})
    db.commit()
    return passed
