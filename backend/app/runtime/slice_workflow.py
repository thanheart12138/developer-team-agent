"""按真实实现反馈逐业务切片规划、开发和验证。"""

import hashlib
import json
from pathlib import Path
import re
import shlex
import uuid

from ..models import Step, StepStatus, TaskStatus
from .contracts import ToolCall, ToolResult
from .prompt_registry import load_prompt
from .tools import TOOL_SCHEMAS, ToolRuntime
from .tracing import safe_record_trace
from .unit_workflow import RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA, UnitTools, file_hashes, test_passed


MAX_SLICES = 12
SLICE_ID = re.compile(r"^[a-z][a-z0-9-]{1,48}$")


def _parse_object(text: str) -> dict:
    """解析模型返回的单个 JSON 对象。"""
    value = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
    if not isinstance(value, dict):
        raise ValueError("slice_planner_json_object_required")
    return value


def _string_list(value, name: str, allow_empty: bool = False) -> list[str]:
    """校验非空字符串列表，避免不可执行的空卡片。"""
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"slice_{name}_required")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"slice_{name}_invalid")
    return value


def validate_card(card: dict, completed_ids: set[str]) -> dict:
    """校验一张执行卡的标识、范围、测试和必要业务字段。"""
    if not isinstance(card, dict) or not SLICE_ID.fullmatch(str(card.get("id", ""))):
        raise ValueError("slice_invalid_id")
    if card["id"] in completed_ids:
        raise ValueError("slice_duplicate_completed_id")
    for field in ("goal", "reason"):
        if not isinstance(card.get(field), str) or not card[field].strip():
            raise ValueError(f"slice_{field}_required")
    for field in ("owners", "interfaces", "acceptance"):
        _string_list(card.get(field), field, allow_empty=field == "interfaces")
    implementation = _string_list(card.get("implementation_files"), "implementation_files")
    tests = _string_list(card.get("test_files"), "test_files")
    paths = implementation + tests
    if len(paths) != len(set(paths)):
        raise ValueError("slice_duplicate_file")
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts or not path.startswith("product/"):
            raise ValueError("slice_invalid_file_path")
    if any(not path.endswith((".test.js", ".test.cjs", ".test.mjs")) for path in tests):
        raise ValueError("slice_invalid_test_file")
    forbidden = ("test", "verification", "document", "docs", "setup", "scaffold")
    if any(word in card["id"].lower() for word in forbidden):
        raise ValueError("slice_non_business_id")
    return card


def ensure_delivery_plan(db, task, run, tools) -> None:
    """为新架构创建只绑定上游版本的增量交付入口，不预生成全部单元。"""
    from . import worker as w
    root = w.workspace_for(task)
    target = root / "docs/delivery-plan.json"
    payload = {
        "workflow": "slice-v1",
        "product_hash": w.content_hash((root / "docs/product.md").read_text(encoding="utf-8")),
        "architecture_hash": w.content_hash((root / "docs/architecture.md").read_text(encoding="utf-8")),
        "max_slices": MAX_SLICES,
    }
    if target.is_file() and json.loads(target.read_text(encoding="utf-8")) == payload:
        return
    w.write_json_atomic(target, payload)
    safe_record_trace(db, task, run, "transition_decision", "succeeded", "逐业务切片入口",
                      "不预生成完整开发单元", payload)
    db.commit()


def load_delivery_plan(root: Path) -> dict:
    """读取切片入口并拒绝上游变化后的旧执行状态。"""
    from . import worker as w
    plan = json.loads((root / "docs/delivery-plan.json").read_text(encoding="utf-8"))
    if plan.get("workflow") != "slice-v1":
        raise ValueError("slice_workflow_version_invalid")
    if plan.get("product_hash") != w.content_hash((root / "docs/product.md").read_text(encoding="utf-8")):
        raise ValueError("slice_product_changed_requires_design")
    if plan.get("architecture_hash") != w.content_hash((root / "docs/architecture.md").read_text(encoding="utf-8")):
        raise ValueError("slice_architecture_changed_requires_design")
    return plan


def _progress(root: Path, plan: dict) -> dict:
    """加载与上游哈希绑定的切片进度，失配时从空进度开始。"""
    target = root / "evidence/slice-progress.json"
    value = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
    signature = {"workflow": plan["workflow"], "product_hash": plan["product_hash"],
                 "architecture_hash": plan["architecture_hash"]}
    if any(value.get(key) != item for key, item in signature.items()):
        value = {**signature, "slices": [], "complete": False}
    return value


def _save_progress(root: Path, value: dict) -> None:
    """原子保存切片卡片、测试状态和恢复依据。"""
    from . import worker as w
    w.write_json_atomic(root / "evidence/slice-progress.json", value)


def plan_next_slice(db, task, run, tools, plan: dict, progress: dict,
                    blocker: str | None = None, current_card: dict | None = None) -> dict | None:
    """依据真实已通过切片和当前文件规划下一片，或等待真正的业务澄清。"""
    from . import worker as w
    root = w.workspace_for(task)
    completed = [entry for entry in progress["slices"] if entry.get("status") == "passed"]
    if len(completed) >= MAX_SLICES:
        raise RuntimeError("slice_limit_exceeded")
    manifest = [{"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in w.product_files(root)]
    context = {
        "approved_product": (root / "docs/product.md").read_text(encoding="utf-8"),
        "architecture": (root / "docs/architecture.md").read_text(encoding="utf-8"),
        "project_constraints": w.FIXED_PRODUCT_CONSTRAINTS,
        "passed_slices": [{"card": entry["card"], "test": entry.get("test")} for entry in completed],
        "current_product_manifest": manifest,
        "missing_product_entries": w.missing_product_files(root),
        "latest_test_result": completed[-1].get("test") if completed else None,
        "replan_blocker": blocker,
        "current_card": current_card,
    }
    feedback = None
    for attempt in range(3):
        response = w.model_tool_loop(db, task, run, load_prompt("slice-planner"),
            "选择当前下一张业务切片。", {**context, "validation_feedback": feedback}, tools,
            tool_schemas=[], history_key=f"slice-plan:{len(completed) + 1}:{attempt + 1}")
        try:
            decision = _parse_object(response)
            action = decision.get("action")
            if action == "implement":
                card = validate_card(decision.get("card"), {entry["card"]["id"] for entry in completed})
                if current_card and card["id"] != current_card["id"]:
                    raise ValueError("slice_replan_id_changed")
                return {"action": action, "card": card}
            if (action == "clarify" and feedback is None and blocker is None
                    and isinstance(decision.get("question"), str) and decision["question"].strip()):
                run.status, task.status = StepStatus.waiting_user, TaskStatus.waiting_user
                w.add_message(db, task, "assistant", decision["question"].strip())
                db.commit()
                return None
            if action == "clarify":
                raise ValueError("slice_internal_validation_cannot_clarify")
            if action == "complete":
                _string_list(decision.get("coverage_summary"), "coverage_summary")
                missing = w.missing_product_files(root)
                if missing:
                    raise ValueError("slice_complete_missing_product_entries:" + ",".join(missing))
                return {"action": action, "coverage_summary": decision["coverage_summary"]}
            raise ValueError("slice_action_invalid")
        except (ValueError, TypeError, KeyError) as exc:
            instruction = "只修正结构错误，返回完整 JSON；这是内部工程校验，不得向用户 clarify。"
            if str(exc) == "slice_non_business_id":
                instruction += (" 不要创建独立测试、文档或浏览器验证切片；系统在切片完成后另有全局浏览器验证。"
                                "若固定入口文件尚缺，把它们并入完成可运行产品的 app-delivery 业务切片。")
            if str(exc).startswith("slice_complete_missing_product_entries:"):
                instruction += (" 当前仍缺少固定交付入口，不能宣布 complete。"
                                "请创建一张 app-delivery 业务切片补齐 missing_product_entries，"
                                "并以可运行产品交付为业务目标。")
            feedback = {"error": str(exc), "instruction": instruction}
    raise RuntimeError("slice_plan_validation_failed")


def _write_index(root: Path, progress: dict) -> None:
    """写入精简切片索引，供 API、恢复和实现血缘使用。"""
    lines = ["# 逐业务切片执行索引", "", "详细范围以结构化执行卡和真实测试证据为准。", ""]
    for index, entry in enumerate(progress["slices"], 1):
        lines.append(f'- {index:03d} {entry["card"]["goal"]}：{entry["card_path"]}；状态：{entry["status"]}')
    (root / "docs/dev-design.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_card(root: Path, progress: dict, card: dict) -> dict:
    """保存下一张不可覆盖的结构化执行卡并加入进度。"""
    from . import worker as w
    number = len(progress["slices"]) + 1
    path = f'docs/slices/{number:03d}-{card["id"]}.json'
    w.write_json_atomic(root / path, card)
    entry = {"card": card, "card_path": path, "status": "planned", "attempt": 0}
    progress["slices"].append(entry)
    _save_progress(root, progress)
    _write_index(root, progress)
    return entry


def handle_design(db, task, run, tools) -> None:
    """Dev Design 只规划第一张切片，不生成全项目设计文档。"""
    from . import worker as w
    root = w.workspace_for(task)
    plan = load_delivery_plan(root)
    progress = _progress(root, plan)
    if not progress["slices"]:
        decision = plan_next_slice(db, task, run, tools, plan, progress)
        if decision is None:
            return
        if decision["action"] == "complete":
            raise RuntimeError("slice_complete_before_implementation")
        _append_card(root, progress, decision["card"])
    _write_index(root, progress)
    run.output_path = "docs/dev-design.md"
    w.finish_step(db, task, run, Step.develop)


def handle_develop(db, task, run, tools: ToolRuntime) -> None:
    """实现当前切片并在真实测试通过后再规划下一张切片。"""
    from . import worker as w
    root = w.workspace_for(task)
    plan = load_delivery_plan(root)
    progress = _progress(root, plan)
    while True:
        pending = next((entry for entry in progress["slices"] if entry.get("status") != "passed"), None)
        if pending is None:
            decision = plan_next_slice(db, task, run, tools, plan, progress)
            if decision is None:
                return
            if decision["action"] == "complete":
                if w.missing_product_files(root):
                    raise RuntimeError("slice_complete_missing_product_entries")
                progress["complete"] = True
                progress["coverage_summary"] = decision["coverage_summary"]
                _save_progress(root, progress)
                _write_index(root, progress)
                w.write_json_atomic(root / "evidence/implementation-lineage.json", {
                    "design_source": "docs/dev-design.md", "workflow": "slice-v1",
                    "product_hash": plan["product_hash"], "architecture_hash": plan["architecture_hash"],
                    "slice_count": len(progress["slices"]),
                    "dev_design_hash": w.content_hash((root / "docs/dev-design.md").read_text(encoding="utf-8")),
                })
                run.output_path = "product/implementation.md"
                w.finish_step(db, task, run, Step.test)
                return
            pending = _append_card(root, progress, decision["card"])
        card = pending["card"]
        completed = [entry for entry in progress["slices"] if entry.get("status") == "passed"]
        prior_tests = [path for entry in completed for path in entry["card"]["test_files"]]
        all_scope = list(dict.fromkeys([str(path.relative_to(root)) for path in w.product_files(root)]
                                       + card["implementation_files"] + card["test_files"]))
        current_tests = list(dict.fromkeys(prior_tests + card["test_files"]))
        command = "node --test " + " ".join(shlex.quote(str(Path(path).relative_to("product"))) for path in current_tests)
        feedback = pending.get("test") if pending.get("status") == "failed" else None
        start = int(pending.get("attempt", 0)) + 1
        for attempt in range(start, w.MAX_NO_CHANGE_CORRECTIONS + 2):
            scoped = UnitTools(root, card["implementation_files"] + card["test_files"],
                               all_scope + [pending["card_path"], "docs/product.md", "docs/architecture.md"],
                               submission_files=card["implementation_files"] + card["test_files"],
                               self_test_files=all_scope, test_files=current_tests)
            pending.update(status="developing", attempt=attempt)
            _save_progress(root, progress)
            response = w.model_tool_loop(db, task, run, load_prompt("slice-developer"),
                json.dumps(card, ensure_ascii=False), {
                    "card": card, "owned_files": card["implementation_files"] + card["test_files"],
                    "unit": {"id": card["id"]}, "unit_file_scope": all_scope,
                    "require_unit_submission": True, "unit_test_feedback": feedback,
                    "passed_slices": [{"id": entry["card"]["id"], "acceptance": entry["card"]["acceptance"]}
                                      for entry in completed],
                }, scoped, tool_schemas=[schema for schema in TOOL_SCHEMAS
                                         if schema["function"]["name"] in {"read", "write"}]
                    + [RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA],
                stop_when=lambda: scoped.submitted_hashes is not None,
                history_key=f'slice:{card["id"]}:{attempt}')
            stripped = response.strip()
            if stripped.startswith("REPLAN:"):
                decision = plan_next_slice(db, task, run, tools, plan, progress,
                                           stripped.removeprefix("REPLAN:").strip(), card)
                if decision is None:
                    return
                if decision["action"] != "implement":
                    raise RuntimeError("slice_replan_must_implement")
                card = decision["card"]
                pending["card"] = card
                w.write_json_atomic(root / pending["card_path"], card)
                pending.update(status="planned", attempt=0)
                _save_progress(root, progress)
                _write_index(root, progress)
                break
            if stripped.startswith("BLOCKED:"):
                question = stripped.removeprefix("BLOCKED:").strip()
                if not question:
                    raise ValueError("slice_blocked_question_missing")
                run.status, task.status, task.cur_step = StepStatus.waiting_user, TaskStatus.waiting_user, Step.dev_design
                w.add_message(db, task, "assistant", question)
                db.commit()
                return
            if scoped.submitted_hashes is None:
                raise RuntimeError("slice_submission_required")
            before = file_hashes(root, all_scope)
            result = w.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
                {"action": "run", "command": command}), history_key=f'slice_test:{card["id"]}')
            after = file_hashes(root, all_scope)
            passed = test_passed(result, before, after)
            feedback = {"slice_id": card["id"], "attempt": attempt, "command": command,
                        "expectations": card["acceptance"], "result": result.__dict__,
                        "file_hashes_before": before, "file_hashes_after": after, "passed": passed}
            report = f'evidence/slices/{len(completed) + 1:03d}-{card["id"]}-attempt-{attempt}.json'
            w.write_json_atomic(root / report, feedback)
            pending.update(status="passed" if passed else "failed", test=feedback,
                           report=report, file_hashes=after)
            _save_progress(root, progress)
            _write_index(root, progress)
            safe_record_trace(db, task, run, "validation", "succeeded" if passed else "failed",
                              f'{card["goal"]}测试', command, feedback)
            db.commit()
            if passed:
                break
        else:
            raise RuntimeError(f'slice_tests_failed:{card["id"]}')
        if pending.get("status") == "planned":
            continue
