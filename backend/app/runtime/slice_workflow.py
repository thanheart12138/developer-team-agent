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
from .scaffold_workflow import remaining_todo_files


MAX_SLICES = 12
SLICE_ID = re.compile(r"^[a-z][a-z0-9-]{1,48}$")
CONTROL_SIGNAL = re.compile(r"(?:^|\n)(REPLAN|BLOCKED):\s*(.+)", re.DOTALL)
REQUEST_REPLAN_SCHEMA = {"type": "function", "function": {
    "name": "request_slice_replan",
    "description": "当前卡缺少未实现模块的公共接口或文件范围时，立即请求 Planner 扩大或调整同一业务切片。",
    "parameters": {"type": "object", "properties": {
        "reason": {"type": "string", "maxLength": 1000},
    }, "required": ["reason"], "additionalProperties": False},
}}


class SliceTools(UnitTools):
    """在单元文件工具之外提供可立即终止循环的结构化重规划信号。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.replan_reason: str | None = None

    def _request_slice_replan(self, reason: str) -> dict:
        """记录重规划原因，交给 Runtime 调用 Planner，不修改产品文件。"""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("slice_replan_reason_required")
        self.replan_reason = reason.strip()
        return {"replan": True, "reason": self.replan_reason}

    def execute(self, call: ToolCall) -> ToolResult:
        """允许当前切片使用结构化重规划工具，其余权限继续沿用 UnitTools。"""
        if call.tool_name == "request_slice_replan":
            return ToolRuntime.execute(self, call)
        return super().execute(call)


def _parse_object(text: str) -> dict:
    """解析模型返回的单个 JSON 对象。"""
    value = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
    if not isinstance(value, dict):
        raise ValueError("slice_planner_json_object_required")
    return value


def _control_signal(text: str) -> tuple[str | None, str]:
    """从独立行提取开发控制信号，容忍模型在信号前给出分析。"""
    match = CONTROL_SIGNAL.search(text.strip())
    return (match.group(1), match.group(2).strip()) if match else (None, text.strip())


def _slice_history_key(prefix: str, card_id: str, attempt: int, generation: int = 0) -> str:
    """为显式重试生成新历史，同时保持首次执行的既有键格式。"""
    suffix = f":g{generation}" if generation else ""
    return f"{prefix}:{card_id}{suffix}:{attempt}"


def _string_list(value, name: str, allow_empty: bool = False) -> list[str]:
    """校验非空字符串列表，避免不可执行的空卡片。"""
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"slice_{name}_required")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"slice_{name}_invalid")
    return value


def _interface_coverage(interfaces: list[str]) -> set[str]:
    """把组合接口展开成操作名，用于比较验收映射是否覆盖所需接口。"""
    coverage: set[str] = set()
    for interface in interfaces:
        operations = re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", interface)
        coverage.update(operations or [interface])
    return coverage


def _validate_coverage_summary(value) -> list:
    """校验完成报告，接受逐项需求及一个或多个已通过切片的来源。"""
    if not isinstance(value, list) or not value:
        raise ValueError("slice_coverage_summary_invalid")
    for item in value:
        if isinstance(item, str) and item.strip():
            continue
        if not isinstance(item, dict):
            raise ValueError("slice_coverage_summary_invalid")
        requirement = item.get("requirement") or item.get("acceptance")
        sources = item.get("covered_by")
        if (isinstance(requirement, str) and requirement.strip()
                and ((isinstance(sources, str) and sources.strip())
                     or (isinstance(sources, list) and sources
                         and all(isinstance(source, str) and source.strip() for source in sources)))):
            continue
        raise ValueError("slice_coverage_summary_invalid")
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
    required_interfaces = _string_list(card.get("required_interfaces"), "required_interfaces", allow_empty=True)
    mappings = card.get("acceptance_interfaces")
    if not isinstance(mappings, list) or len(mappings) != len(card["acceptance"]):
        raise ValueError("slice_acceptance_interfaces_required")
    mapped_criteria: set[str] = set()
    mapped_interfaces: set[str] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict) or mapping.get("acceptance") not in card["acceptance"]:
            raise ValueError("slice_acceptance_interface_invalid")
        if mapping["acceptance"] in mapped_criteria:
            raise ValueError("slice_acceptance_interface_duplicate")
        mapped_criteria.add(mapping["acceptance"])
        mapped_interfaces.update(_string_list(mapping.get("interfaces"), "acceptance_interface", allow_empty=True))
    if mapped_criteria != set(card["acceptance"]):
        raise ValueError("slice_acceptance_interface_coverage")
    required_coverage = _interface_coverage(required_interfaces)
    mapped_coverage = _interface_coverage(list(mapped_interfaces))
    declared_coverage = _interface_coverage(card["interfaces"])
    if mapped_coverage != required_coverage or not mapped_coverage <= declared_coverage:
        raise ValueError("slice_required_interfaces_mismatch")
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


def validate_card_dependencies(card: dict, scaffold: dict | None, completed: list[dict]) -> None:
    """拒绝依赖尚未交付模块却未把其实现和测试纳入当前卡的计划。"""
    if not scaffold:
        return
    modules = {module["id"]: module for module in scaffold.get("modules", [])}
    exact_owners: dict[str, set[str]] = {}
    operation_owners: dict[str, set[str]] = {}
    for module_id, module in modules.items():
        for interface in module.get("interfaces", []):
            exact_owners.setdefault(interface, set()).add(module_id)
            # 一个契约可以合并列出多个公共操作，例如
            # `listTopics() / getTopic(id)`；每个操作都应能被依赖卡单独引用。
            for operation in re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", interface):
                operation_owners.setdefault(operation, set()).add(module_id)
    delivered_modules = {module_id for module_id, module in modules.items()
                         if any(set(module.get("implementation_files", [])) <= set(entry["card"]["implementation_files"])
                                and module.get("test_file") in entry["card"]["test_files"]
                                for entry in completed)}
    current_files = set(card["implementation_files"])
    current_tests = set(card["test_files"])
    unavailable = []
    for interface in card["required_interfaces"]:
        candidates = exact_owners.get(interface)
        if candidates is None:
            candidates = operation_owners.get(interface.split("(", 1)[0])
        if not candidates:
            raise ValueError(f"slice_required_interface_unknown:{interface}")
        if len(candidates) != 1:
            scoped_candidates = {module_id for module_id in candidates
                                 if set(modules[module_id].get("implementation_files", [])) <= current_files
                                 and modules[module_id].get("test_file") in current_tests}
            current_candidates = candidates.intersection(card["owners"])
            delivered_candidates = candidates.intersection(delivered_modules)
            if len(scoped_candidates) == 1:
                candidates = scoped_candidates
            elif len(current_candidates) == 1:
                candidates = current_candidates
            elif not current_candidates and len(delivered_candidates) == 1:
                candidates = delivered_candidates
            else:
                raise ValueError(f"slice_required_interface_ambiguous:{interface}")
        owner = next(iter(candidates))
        module = modules[owner]
        included = (set(module.get("implementation_files", [])) <= current_files
                    and module.get("test_file") in current_tests and owner in card["owners"])
        if owner not in delivered_modules and not included:
            unavailable.append(interface)
    if unavailable:
        raise ValueError("slice_required_interfaces_unavailable:" + ",".join(unavailable))


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


def prepare_architecture_delivery(db, task, run, tools) -> None:
    """架构正式化后先生成受限代码骨架，再创建逐切片交付入口。"""
    from . import worker as w
    from .acceptance_standard import ensure_standard
    from .scaffold_workflow import ensure_scaffold
    root = w.workspace_for(task)
    # 只为已正式批准产品且尚未创建交付入口的新架构建立标准；旧修订任务不迁移。
    if ((run.attempt == 1 or not (root / "docs/architecture-v1.md").is_file())
            and (root / "docs/product-v1.md").is_file()
            and not any((root / path).is_file() for path in
                        ("docs/delivery-plan.json", "docs/development-plan.json"))):
        ensure_standard(db, task, run, tools)
    if run.attempt == 1 and not any((root / "product").rglob("*")):
        ensure_scaffold(db, task, run, tools)
    ensure_delivery_plan(db, task, run, tools)


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
    from .acceptance_standard import load_standard, review_coverage, validate_card_ids
    root = w.workspace_for(task)
    standard = load_standard(root)
    from .repair_objectives import pending
    triage = w.active_bug_triage(task) or {}
    # 新设计缺陷必须交付对应事件的返修卡，旧卡通过不能充当新目标证据。
    repair_required = (triage.get("classification") == "dev_design_defect"
                       and not any(entry.get("repair_event_id") == triage.get("event_id")
                                   and entry.get("status") == "passed"
                                   for entry in progress["slices"]))
    completed = [entry for entry in progress["slices"] if entry.get("status") == "passed"]
    if len(completed) >= MAX_SLICES:
        raise RuntimeError("slice_limit_exceeded")
    manifest = [{"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in w.product_files(root)]
    context = {
        "approved_product": (root / "docs/product.md").read_text(encoding="utf-8"),
        "architecture": (root / "docs/architecture.md").read_text(encoding="utf-8"),
        "project_constraints": w.FIXED_PRODUCT_CONSTRAINTS,
        "verification_execution_contract": w.VERIFICATION_EXECUTION_CONTRACT,
        "passed_slices": [{"card": entry["card"], "test": entry.get("test")} for entry in completed],
        "current_product_manifest": manifest,
        "missing_product_entries": w.missing_product_files(root),
        "scaffold_contract": (json.loads((root / "docs/scaffold-contract.json").read_text(encoding="utf-8"))
                              if (root / "docs/scaffold-contract.json").is_file() else None),
        "remaining_todo_files": remaining_todo_files(root),
        "latest_test_result": completed[-1].get("test") if completed else None,
        "replan_blocker": blocker,
        "current_card": current_card,
        "acceptance_standard": standard["items"] if standard else None,
        "current_acceptance_feedback": triage,
        "pending_repair_objectives": pending(task),
        "design_repair_required": repair_required,
    }
    feedback = None
    replan_suffix = (f":replan:{hashlib.sha256(blocker.encode('utf-8')).hexdigest()[:12]}"
                     if blocker else "")
    for attempt in range(3):
        response = w.model_tool_loop(db, task, run, load_prompt("slice-planner"),
            "选择当前下一张业务切片。", {**context, "validation_feedback": feedback}, tools,
            tool_schemas=[], history_key=f"slice-plan:{len(completed) + 1}:{attempt + 1}{replan_suffix}")
        try:
            decision = _parse_object(response)
            action = decision.get("action")
            if action == "implement":
                card = validate_card(decision.get("card"), {entry["card"]["id"] for entry in completed})
                if standard:
                    validate_card_ids(card, standard)
                validate_card_dependencies(card, context["scaffold_contract"], completed)
                remaining = set(remaining_todo_files(root))
                if remaining and not remaining.intersection(card["test_files"]):
                    raise ValueError("slice_card_ignores_scaffold_todos")
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
                if repair_required:
                    raise ValueError("slice_design_repair_not_delivered")
                _validate_coverage_summary(decision.get("coverage_summary"))
                if remaining_todo_files(root):
                    raise ValueError("slice_complete_scaffold_todos_remaining")
                missing = w.missing_product_files(root)
                if missing:
                    raise ValueError("slice_complete_missing_product_entries:" + ",".join(missing))
                if standard:
                    coverage = review_coverage(db, task, run, tools, standard, completed)
                    if not coverage["complete"]:
                        raise ValueError("slice_acceptance_coverage_missing:" +
                                         json.dumps(coverage["issues"], ensure_ascii=False))
                return {"action": action, "coverage_summary": decision["coverage_summary"]}
            raise ValueError("slice_action_invalid")
        except (ValueError, TypeError, KeyError) as exc:
            instruction = "只修正结构错误，返回完整 JSON；这是内部工程校验，不得向用户 clarify。"
            if str(exc) == "slice_design_repair_not_delivered":
                instruction += " 当前验收设计缺陷尚未交付，必须依据 current_acceptance_feedback 和 pending_repair_objectives 生成返修业务卡，包含需要修改的实现与验证文件。"
            if str(exc) == "slice_coverage_summary_invalid":
                instruction += (" coverage_summary 必须是非空数组；每项写非空文字，或写"
                                " {requirement/acceptance: 非空文字, covered_by: 非空文字或非空文字数组}。")
            if str(exc) == "slice_non_business_id":
                instruction += (" 不要创建独立测试、文档或浏览器验证切片；系统在切片完成后另有全局浏览器验证。"
                                "若固定入口文件尚缺，把它们并入完成可运行产品的 app-delivery 业务切片。")
            if str(exc).startswith("slice_complete_missing_product_entries:"):
                instruction += (" 当前仍缺少固定交付入口，不能宣布 complete。"
                                "请创建一张 app-delivery 业务切片补齐 missing_product_entries，"
                                "并以可运行产品交付为业务目标。")
            if str(exc) in {"slice_card_ignores_scaffold_todos", "slice_complete_scaffold_todos_remaining"}:
                instruction += (" 必须优先选择 remaining_todo_files 对应的业务模块，并在该业务切片中把 todo"
                                " 改成真实断言；仍有 todo 时不得 complete。")
            if str(exc).startswith("slice_required_interfaces_unavailable:"):
                instruction += (" 当前卡依赖尚未交付的公共接口。必须把这些接口所属模块的全部骨架实现文件和测试文件"
                                "加入当前卡，并把所属模块加入 owners；不得把缺口留给 Developer。")
            if str(exc).startswith(("slice_required_interface_unknown:", "slice_required_interface_ambiguous:",
                                    "slice_acceptance_interface_",
                                    "slice_required_interfaces_mismatch")):
                instruction += (" 按 scaffold_contract 公共接口逐条修正 required_interfaces 和 acceptance_interfaces；"
                                "每条 acceptance 必须映射其真实需要的全部公共接口。")
            feedback = {"error": str(exc), "instruction": instruction}
    raise RuntimeError("slice_plan_validation_failed")


def _write_index(root: Path, progress: dict) -> None:
    """写入精简切片索引，供 API、恢复和实现血缘使用。"""
    lines = ["# 逐业务切片执行索引", "", "详细范围以结构化执行卡和真实测试证据为准。", ""]
    for index, entry in enumerate(progress["slices"], 1):
        lines.append(f'- {index:03d} {entry["card"]["goal"]}：{entry["card_path"]}；状态：{entry["status"]}')
    (root / "docs/dev-design.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_card(root: Path, progress: dict, card: dict, repair_event_id=None) -> dict:
    """保存下一张不可覆盖的结构化执行卡并加入进度。"""
    from . import worker as w
    number = len(progress["slices"]) + 1
    path = f'docs/slices/{number:03d}-{card["id"]}.json'
    w.write_json_atomic(root / path, card)
    entry = {"card": card, "card_path": path, "status": "planned", "attempt": 0}
    if repair_event_id is not None:
        entry["repair_event_id"] = repair_event_id
    progress["complete"] = False
    progress["slices"].append(entry)
    _save_progress(root, progress)
    _write_index(root, progress)
    return entry


def handle_design(db, task, run, tools) -> None:
    """规划首张业务卡或当前验收事件的新返修卡，保留旧交付证据。"""
    from . import worker as w
    root = w.workspace_for(task)
    plan = load_delivery_plan(root)
    progress = _progress(root, plan)
    triage = w.active_bug_triage(task) or {}
    repair_event_id = (triage.get("event_id")
                       if triage.get("classification") == "dev_design_defect" else None)
    needs_repair = (repair_event_id is not None and not any(
        entry.get("repair_event_id") == repair_event_id for entry in progress["slices"]))
    if not progress["slices"] or needs_repair:
        decision = plan_next_slice(db, task, run, tools, plan, progress)
        if decision is None:
            return
        if decision["action"] == "complete":
            raise RuntimeError("slice_complete_before_implementation")
        _append_card(root, progress, decision["card"], repair_event_id)
    _write_index(root, progress)
    run.output_path = "docs/dev-design.md"
    w.finish_step(db, task, run, Step.develop)


def handle_develop(db, task, run, tools: ToolRuntime) -> None:
    """实现当前切片并在真实测试通过后再规划下一张切片。"""
    from . import worker as w
    from .acceptance_standard import load_standard
    root = w.workspace_for(task)
    standard = load_standard(root)
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
        generation = int(pending.get("generation", 0))
        for attempt in range(start, w.MAX_NO_CHANGE_CORRECTIONS + 2):
            scoped = SliceTools(root, card["implementation_files"] + card["test_files"],
                               all_scope + [pending["card_path"], "docs/product.md", "docs/architecture.md"],
                               submission_files=card["implementation_files"] + card["test_files"],
                               self_test_files=all_scope, test_files=current_tests)
            pending.update(status="developing", attempt=attempt)
            _save_progress(root, progress)
            response = w.model_tool_loop(db, task, run, load_prompt("slice-developer"),
                "实现 context.card 中的当前切片，按真实自测结果修复并显式提交。", {
                    "card": card, "owned_files": card["implementation_files"] + card["test_files"],
                    "unit": {"id": card["id"]}, "unit_file_scope": all_scope,
                    "require_unit_submission": True, "unit_test_feedback": feedback,
                    "acceptance_standard_items": [item for item in standard["items"]
                                                  if item["id"] in card.get("acceptance_ids", [])]
                    if standard else [],
                    "passed_slices": [{"id": entry["card"]["id"], "acceptance": entry["card"]["acceptance"]}
                                      for entry in completed],
                }, scoped, tool_schemas=[schema for schema in TOOL_SCHEMAS
                                         if schema["function"]["name"] in {"read", "write", "replace"}]
                    + [RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA, REQUEST_REPLAN_SCHEMA],
                stop_when=lambda: scoped.submitted_hashes is not None or scoped.replan_reason is not None,
                history_key=_slice_history_key("slice", card["id"], attempt, generation))
            signal, detail = _control_signal(response)
            if scoped.replan_reason is not None:
                signal, detail = "REPLAN", scoped.replan_reason
            if signal == "REPLAN":
                decision = plan_next_slice(db, task, run, tools, plan, progress,
                                           detail, card)
                if decision is None:
                    return
                if decision["action"] != "implement":
                    raise RuntimeError("slice_replan_must_implement")
                card = decision["card"]
                pending["card"] = card
                w.write_json_atomic(root / pending["card_path"], card)
                pending.update(status="planned", attempt=0, generation=generation + 1)
                _save_progress(root, progress)
                _write_index(root, progress)
                break
            if signal == "BLOCKED":
                question = detail
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
                {"action": "run", "command": command}),
                history_key=_slice_history_key("slice_test", card["id"], attempt, generation))
            after = file_hashes(root, all_scope)
            passed = test_passed(result, before, after)
            unresolved = set(remaining_todo_files(root))
            if unresolved.intersection(card["test_files"]):
                passed = False
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


def _repair_failure_excerpt(stdout: str) -> str:
    """优先保留 Node 失败定位与断言，避免长应用流水挤掉实际／期望值。"""
    # spec 的末尾失败区包含完整错误；不用前面的重复失败名和成功测试流水。
    detail = stdout.split("✖ failing tests:", 1)[-1]
    blocks = re.split(r"(?m)(?=^test at |^\s*(?:not ok|ok) \d+)", detail)
    failures = [block for block in blocks if block.lstrip().startswith(("test at ", "not ok "))]
    if not failures:
        # 非标准测试错误仍提供末尾输出，完整报告继续作为定位依据。
        return detail[-1200:]
    excerpts = []
    for block in failures:
        lines = []
        for line in block.splitlines():
            stripped = line.strip()
            # 应用操作流水及 Node 内部栈不提供业务断言位置，留在完整报告查询。
            if (not stripped or stripped.startswith(("[step]", "[pass]", "✔ ", "ℹ ", "# Subtest:"))
                    or (stripped.startswith("at ") and "node:" in stripped)):
                continue
            line = re.sub(r"(?<=: )\[step\].*", "[应用步骤见完整报告]", line)
            lines.append(line)
        important = [line for line in lines if re.match(
            r"\s*(?:test at |✖ |not ok |at |(?:[\w.]*Error)(?: \[[^]]+\])?:|"
            r"(?:code|error|failureType|location|actual|expected|operator):|assert[.(])", line)]
        # 先放定位／断言字段，再用剩余空间提供错误上下文；截断不删除原报告。
        ordered = important + [line for line in lines if line not in important]
        text = "\n".join(line if len(line) <= 400 else line[:400] + " [该行完整内容见报告]" for line in ordered)
        excerpts.append(text if len(text) <= 2000 else text[:2000] + "\n[其余错误详情见完整报告]")
    text = "\n\n".join(excerpts)
    return text if len(text) <= 6000 else text[:6000] + "\n[其余失败项见完整报告]"


def _repair_diagnostic(db, task, run, scoped: SliceTools) -> dict:
    """返修先取得固定范围的真实诊断，恢复仅复用本 Run 的同版本结果，不授予自测资格。"""
    from . import worker as w
    command = scoped.self_test_command()
    before = scoped.self_test_versions()
    # 每个固定命令／版本保留独立报告，回到已测版本时也不重复执行。
    version_key = hashlib.sha256(json.dumps({"command": command, "versions": before}, sort_keys=True).encode()).hexdigest()[:16]
    relative_path = f"evidence/slice-repair-diagnostic-{run.id}-{version_key}.json"
    path = scoped.workspace / relative_path
    report = None
    self_test = scoped.self_test
    if (self_test and self_test.get("command") == command
            and self_test.get("file_hashes_before") == before and self_test.get("file_hashes_after") == before
            and all(value is not None for value in before.values())):
        # 同批已主动自测时复用其真实结果，不再发起一次程序诊断。
        report = self_test
        w.write_json_atomic(path, report)
    elif path.is_file():
        # 缺文件或测试期间版本不稳定的结果不能作为恢复缓存。
        saved = json.loads(path.read_text(encoding="utf-8"))
        if (saved.get("command") == command and saved.get("file_hashes_before") == before
                and saved.get("file_hashes_after") == before
                and all(value is not None for value in before.values())):
            report = saved
    if report is None:
        missing = [name for name, digest in before.items() if digest is None]
        # 由程序执行固定测试并记录真实 Trace，与模型 run_unit_tests 的证据独立。
        result = w.execute_tool(db, task, run, ToolRuntime(scoped.workspace),
            ToolCall(str(uuid.uuid4()), "exec", {"action": "run", "command": command}),
            history_key=f"slice-repair-diagnostic:{run.id}",
            blocked_error="unit_files_missing:" + ",".join(missing) if missing else None)
        after = scoped.self_test_versions()
        report = {"command": command, "result": result.__dict__, "file_hashes_before": before,
                  "file_hashes_after": after, "passed": test_passed(result, before, after)}
        w.write_json_atomic(path, report)
    # 模型按需读取完整报告，默认只提供失败项和汇总，避免重复携带大段成功日志。
    result = report["result"]
    output = result.get("output", {})
    stdout = output.get("stdout", "")
    excerpt = _repair_failure_excerpt(stdout)
    return {key: value for key, value in report.items() if key != "result"} | {
        "failure_report": "\n".join(filter(None, [result.get("error"), output.get("stderr", "")[:1000], excerpt])),
        "exit_code": output.get("exit_code"), "timed_out": output.get("timed_out", False),
        "detail_path": relative_path,
        "instruction": "程序诊断仅提供当前真实错误，不算开发自测。按错误位置读取必要范围并修复，同时完成原始验收目标；仍须主动 run_unit_tests，通过后显式提交。"}


def _repair_history_key(run, card_id: str, failure_key: str) -> str:
    # 同 Run、同责任卡和同失败恢复已有循环 ID，不随完成动作数变化而丢失历史。
    prefix = f"slice-repair:{card_id}:{failure_key}:"
    checkpoint = Path(run.checkpoint_path) if run.checkpoint_path else None
    if checkpoint and checkpoint.is_file():
        entries = json.loads(checkpoint.read_text(encoding="utf-8"))
        for entry in reversed(entries):
            key = entry.get("history_key", "")
            if key.startswith(prefix):
                return key
    return prefix + str(run.last_completed_action_index)


def handle_repair(db, task, run, tools: ToolRuntime) -> None:
    """把集成失败路由给拥有失败入口的已交付切片，并在提交后立即复跑原验证。"""
    from . import worker as w
    from .acceptance_standard import load_standard
    from .repair_objectives import capture, pending
    root = w.workspace_for(task)
    triage = w.active_bug_triage(task)
    if triage.get("event_id"):
        capture(root, triage)
    objectives = pending(task)
    standard = load_standard(root)
    progress = _progress(root, load_delivery_plan(root))
    completed = [entry for entry in progress["slices"] if entry.get("status") == "passed"]
    report_path = root / "evidence/verification-report.md"
    verification_failure = report_path.is_file() and bool(task.result_url)
    owner_path = "product/verify_product.py" if verification_failure else None
    owner = next((entry for entry in reversed(completed)
                  if owner_path and owner_path in entry["card"]["implementation_files"]), None)
    if owner is None:
        owner = completed[-1] if completed else None
    if owner is None:
        raise RuntimeError("slice_repair_owner_missing")

    card = owner["card"]
    owned_files = card["implementation_files"] + card["test_files"]
    all_scope = [str(path.relative_to(root)) for path in w.product_files(root)]
    failure = report_path.read_text(encoding="utf-8") if report_path.is_file() else "集成验证失败"
    # 保存不可变的本轮原报告，后续请求用可读取引用，不能被最新诊断覆盖。
    failure_key = hashlib.sha256(failure.encode("utf-8")).hexdigest()[:12]
    failure_reference = f"evidence/slice-repair-origin-{run.id}-{failure_key}.json"
    if not (root / failure_reference).is_file():
        w.write_json_atomic(root / failure_reference, {"failure_report": failure})
    # 原卡完整留存为只读依据，返修请求不重发所有旧验收映射与接口正文。
    card_reference = f"evidence/slice-repair-card-{run.id}.json"
    w.write_json_atomic(root / card_reference, card)
    standard_reference = "docs/acceptance-standard.json" if standard else None
    scoped = SliceTools(root, owned_files, all_scope + [owner["card_path"], card_reference, failure_reference,
                        "evidence/repair-objectives.json", "docs/product.md", "docs/architecture.md"]
                        + ([standard_reference] if standard_reference else []),
                        submission_files=owned_files, self_test_files=all_scope,
                        test_files=card["test_files"])

    def refresh_diagnostic() -> dict:
        """入口与工具批次后刷新当前诊断，完整证据只读可查，不赋予自测资格。"""
        diagnostic = _repair_diagnostic(db, task, run, scoped)
        scoped.readable.add(scoped._safe_path(diagnostic["detail_path"]))
        return diagnostic

    diagnostic = refresh_diagnostic()
    w.model_tool_loop(db, task, run, load_prompt("slice-developer"), "按 context.repair_task 修复当前真实失败，保留原始验收目标，主动自测并显式提交。", {
        "repair_task": {"card_id": card["id"], "goal": "修复当前真实诊断列出的失败项，并完成未闭合的原始验收目标。",
                        "current_failure_ref": "unit_diagnostic", "execution_contract_ref": "verification_execution_contract",
                        "original_card_ref": card_reference, "acceptance_standard_ref": standard_reference,
                        "original_objectives_ref": "unresolved_acceptance_objectives", "writable_files_ref": "owned_files",
                        "test_files": card["test_files"]},
        "owned_files": owned_files,
        "unit": {"id": card["id"]},
        "unit_file_scope": all_scope,
        "require_unit_submission": True,
        "repair_round": task.repair_round,
        "unresolved_acceptance_objectives": objectives,
        "unit_diagnostic": diagnostic,
        "unit_test_feedback": {"failure_source": "verify_product" if verification_failure else "test",
                               "failure_report": failure,
                               "detail_path": failure_reference,
                               "report_sha256": hashlib.sha256((root / failure_reference).read_bytes()).hexdigest(),
                               "instruction": "保留并完成原始验收目标；最新失败是当前阻塞，不能替代原始目标。先读取必要文件，补对应操作与断言，修改后测试并提交。"},
        "passed_slices": [{"id": entry["card"]["id"]} for entry in completed],
    }, scoped, tool_schemas=[schema for schema in TOOL_SCHEMAS
                             if schema["function"]["name"] in {"read", "write", "replace"}]
        + [RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA],
        stop_when=lambda: scoped.submitted_hashes is not None,
        refresh_diagnostic=refresh_diagnostic,
        history_key=_repair_history_key(run, card['id'], failure_key))
    if scoped.submitted_hashes is None:
        raise RuntimeError("slice_repair_submission_required")
    if verification_failure:
        # 返修后的浏览器复验与首次验证共用脚本预检，避免绕过 URL 和脚本错误门禁。
        result, command = w.run_product_browser_validation(db, task, run, tools)
    else:
        command = "node --test"
        result = w.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
            {"action": "run", "command": command}), history_key=f"slice-repair-test:{run.id}")
    passed = (w.browser_validation_passed(result) if verification_failure else
              result.status == "succeeded" and result.output.get("exit_code") == 0)
    if not passed:
        latest = result.output.get("stdout", "") + result.output.get("stderr", "")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("# 最新受控集成验证失败\n\n```text\n" + latest + "\n```\n", encoding="utf-8")
        # 保留最新失败证据，并在已有返修预算内交回开发阶段。
        w.fail_or_repair(db, task, run, "slice_repair_validation_failed")
        return
    run.output_path = "product/implementation.md"
    w.finish_step(db, task, run, Step.test)
