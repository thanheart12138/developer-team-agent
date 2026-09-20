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
MAX_REPAIR_CALLS_PER_EVIDENCE = 2
MAX_SLICE_REPAIR_CALLS = 4
MAX_RESTRICTED_IMPLEMENTATION_CALLS = 4
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
        """初始化切片工具和当前调用的重规划状态。"""
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


class RestrictedImplementationTools(SliceTools):
    """仅允许模型修改当前拥有文件或请求重规划。"""

    def execute(self, call: ToolCall) -> ToolResult:
        """即使模型调用未公开工具，也不能读取、执行命令或自行提交。"""
        if call.tool_name not in {"write", "replace", "request_slice_replan"}:
            return ToolResult(call.call_id, call.tool_name, "failed", error="restricted_implementation_tool_not_allowed")
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


def _repair_budget(root: Path, failure_key: str) -> tuple[Path, dict, int]:
    """读取单份证据与整个返修事务跨恢复累计的模型调用预算。"""
    path = root / "evidence/slice-repair-budgets.json"
    budgets = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    used = budgets.get(failure_key, {}).get("used_calls", 0)
    total_used = sum(entry.get("used_calls", 0) for entry in budgets.values())
    if type(used) is not int or used < 0 or type(total_used) is not int or total_used < 0:
        raise ValueError("slice_repair_budget_invalid")
    return path, budgets, min(MAX_REPAIR_CALLS_PER_EVIDENCE - used,
                              MAX_SLICE_REPAIR_CALLS - total_used)


def _record_repair_calls(path: Path, budgets: dict, failure_key: str, calls: int) -> None:
    """持久化本次实际增加的模型调用，Worker 恢复不能重置同一失败预算。"""
    previous = budgets.get(failure_key, {}).get("used_calls", 0)
    budgets[failure_key] = {"used_calls": previous + max(0, calls),
                            "max_calls": MAX_REPAIR_CALLS_PER_EVIDENCE}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(budgets, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


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
    """校验完成报告，兼容旧字符串清单和新版结构化需求覆盖表。"""
    if not isinstance(value, list) or not value:
        raise ValueError("slice_coverage_summary_invalid")
    for item in value:
        if isinstance(item, str) and item.strip():
            continue
        if (isinstance(item, dict)
                and isinstance(item.get("requirement"), str) and item["requirement"].strip()
                and isinstance(item.get("covered_by"), str) and item["covered_by"].strip()):
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
    rework = _string_list(card.get("rework_delivered_modules", []),
                          "rework_delivered_modules", allow_empty=True)
    reasons = card.get("rework_reasons", {})
    if not isinstance(reasons, dict) or any(
            not isinstance(reasons.get(module_id), str) or not reasons[module_id].strip()
            for module_id in rework):
        raise ValueError("slice_rework_reason_required")
    card["rework_delivered_modules"] = rework
    card["rework_reasons"] = {module_id: reasons[module_id] for module_id in rework}
    forbidden = ("test", "verification", "document", "docs", "setup", "scaffold")
    if any(word in card["id"].lower() for word in forbidden):
        raise ValueError("slice_non_business_id")
    return card


def validate_card_dependencies(card: dict, scaffold: dict | None, completed: list[dict]) -> dict:
    """校验依赖交付与所有权，并返回经过同一校验的接口—文件映射。"""
    if not scaffold:
        return {}
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
    rework = set(card.get("rework_delivered_modules", []))
    included_delivered = {module_id for module_id in delivered_modules
                          if set(modules[module_id].get("implementation_files", [])) <= current_files
                          and modules[module_id].get("test_file") in current_tests}
    repeated_owners = delivered_modules.intersection(card.get("owners", []))
    redundant = (included_delivered | repeated_owners) - rework
    if redundant:
        raise ValueError("slice_repeats_delivered_modules:" + ",".join(sorted(redundant)))
    invalid_rework = rework - included_delivered
    if invalid_rework:
        raise ValueError("slice_rework_modules_invalid:" + ",".join(sorted(invalid_rework)))
    unavailable = []
    mapping = {}
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
        mapping[interface] = {"owner": owner, "implementation_files": module["implementation_files"]}
        included = (set(module.get("implementation_files", [])) <= current_files
                    and module.get("test_file") in current_tests and owner in card["owners"])
        if owner not in delivered_modules and not included:
            unavailable.append(interface)
    if unavailable:
        raise ValueError("slice_required_interfaces_unavailable:" + ",".join(unavailable))
    return mapping


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
    from .scaffold_workflow import ensure_scaffold
    root = w.workspace_for(task)
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
        "passed_slices": [{"id": entry["card"]["id"],
                           "owners": entry["card"]["owners"],
                           "interfaces": entry["card"]["interfaces"],
                           "implementation_files": entry["card"]["implementation_files"],
                           "test_files": entry["card"]["test_files"],
                           "acceptance": entry["card"]["acceptance"]}
                          for entry in completed],
        "current_product_manifest": manifest,
        "missing_product_entries": w.missing_product_files(root),
        "scaffold_contract": (json.loads((root / "docs/scaffold-contract.json").read_text(encoding="utf-8"))
                              if (root / "docs/scaffold-contract.json").is_file() else None),
        "remaining_todo_files": remaining_todo_files(root),
        "latest_test_result": ({
            "slice_id": completed[-1]["card"]["id"],
            "passed": completed[-1]["test"].get("passed"),
            "command": completed[-1]["test"].get("command"),
            "report": completed[-1].get("report"),
        } if completed and completed[-1].get("test") else None),
        "replan_blocker": blocker,
        "current_card": current_card,
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
                _validate_coverage_summary(decision.get("coverage_summary"))
                if remaining_todo_files(root):
                    raise ValueError("slice_complete_scaffold_todos_remaining")
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
            if str(exc) in {"slice_card_ignores_scaffold_todos", "slice_complete_scaffold_todos_remaining"}:
                instruction += (" 必须优先选择 remaining_todo_files 对应的业务模块，并在该业务切片中把 todo"
                                " 改成真实断言；仍有 todo 时不得 complete。")
            if str(exc).startswith("slice_required_interfaces_unavailable:"):
                instruction += (" 当前卡依赖尚未交付的公共接口。必须把这些接口所属模块的全部骨架实现文件和测试文件"
                                "加入当前卡，并把所属模块加入 owners；不得把缺口留给 Developer。")
            if str(exc).startswith("slice_repeats_delivered_modules:"):
                instruction += (" 已通过模块默认是只读依赖，不要把其 implementation_files、test_file 或 owner 重复加入当前卡。"
                                "只有 acceptance 明确改变其既有行为时，才列入 rework_delivered_modules 并提供 rework_reasons。")
            if str(exc).startswith("slice_rework_modules_invalid:") or str(exc) == "slice_rework_reason_required":
                instruction += (" rework_delivered_modules 只能声明当前卡确实完整纳入且已通过的模块，"
                                "rework_reasons 必须逐项说明哪条 acceptance 要改变该模块既有行为。")
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


def run_slice_developer(db, task, run, card: dict, completed: list[dict], scoped: SliceTools,
                        history_key: str, feedback: dict | None = None) -> str:
    """运行普通开发；一次推进违约后持久切换到独立实现，不再恢复旧对话。"""
    from . import worker as w
    root = w.workspace_for(task)
    state_path = root / f"evidence/slices/developer-{w.content_hash(history_key)}.json"
    card_hash = w.content_hash(json.dumps(card, ensure_ascii=False, sort_keys=True))
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
    if state is None:
        response = w.model_tool_loop(db, task, run, load_prompt("slice-developer"),
            json.dumps(card, ensure_ascii=False), {
                "card": card, "owned_files": scoped.submission_files,
                "unit": {"id": card["id"]}, "unit_file_scope": scoped.submission_files,
                "require_unit_submission": True, "unit_test_feedback": feedback,
                "switch_on_progress_violation": True,
                "passed_slices": [{"id": entry["card"]["id"],
                                   "acceptance": entry["card"]["acceptance"],
                                   "interfaces": entry["card"]["interfaces"],
                                   "implementation_files": entry["card"]["implementation_files"]}
                                  for entry in completed],
            }, scoped, tool_schemas=[schema for schema in TOOL_SCHEMAS
                                     if schema["function"]["name"] in {"read", "write"}]
                + [RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA, REQUEST_REPLAN_SCHEMA],
            stop_when=lambda: scoped.submitted_hashes is not None or scoped.replan_reason is not None,
            history_key=history_key)
        if response != "DEVELOPER_PROGRESS_SWITCH":
            return response
        state = {"card_hash": card_hash, "source_history_key": history_key,
                 "history_prefix": history_key + ":implementation", "used_calls": 0,
                 "phase": "ready", "reason": "covered_read_requires_write_test_or_replan"}
        w.write_json_atomic(state_path, state)
        safe_record_trace(db, task, run, "transition_decision", "succeeded", "切换到独立受限实现",
                          card["id"], state)
        db.commit()
    if state["card_hash"] != card_hash:
        raise RuntimeError("slice_restricted_card_changed")
    return _run_restricted_implementation(db, task, run, card, completed, scoped, state_path, state)


def _implementation_inputs(root: Path, card: dict, completed: list[dict], scoped: SliceTools) -> dict:
    """只从已校验契约确定依赖范围，未知或缺失时停止，绝不按接口名猜文件。"""
    contract = root / "docs/scaffold-contract.json"
    if not contract.is_file():
        raise ValueError("slice_dependency_mapping_missing")
    mapping = validate_card_dependencies(card, json.loads(contract.read_text(encoding="utf-8")), completed)
    paths = list(dict.fromkeys(scoped.submission_files + [
        path for value in mapping.values() for path in value["implementation_files"]]))
    for path in paths:
        target = scoped._safe_path(path)
        if target not in scoped.readable:
            raise ValueError("slice_dependency_outside_readable_scope:" + path)
        if path not in scoped.submission_files and not target.is_file():
            raise ValueError("slice_dependency_file_missing:" + path)
        if path not in scoped.submission_files:
            delivered = next((entry for entry in reversed(completed)
                              if path in entry["card"]["implementation_files"]), None)
            current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if (not delivered or delivered.get("status") != "passed"
                    or not delivered.get("test", {}).get("passed")
                    or delivered.get("file_hashes", {}).get(path) != current_hash):
                raise ValueError("slice_dependency_evidence_stale:" + path)
    # 完整内容由 build_tool_context 按相同范围读取，证据包只保存映射与版本，避免重复正文。
    return {"interface_files": mapping, "file_hashes": file_hashes(root, paths)}


def _run_restricted_implementation(db, task, run, card: dict, completed: list[dict], scoped: SliceTools,
                                   state_path: Path, state: dict) -> str:
    """在持久化四次额度内实现、程序自测和提交，失败仅使用当前版本证据修复。"""
    from . import worker as w
    root = w.workspace_for(task)
    if state["phase"] == "failed":
        raise RuntimeError(state["error"])
    if state["phase"] in {"replan", "blocked"}:
        if state["phase"] == "replan":
            scoped.replan_reason = state["detail"]
        return state["response"]
    if state["phase"] == "submitted":
        if not scoped.restore_submission(state["submission"]):
            raise RuntimeError("slice_restricted_submission_stale")
        return "SUBMITTED_FOR_TEST"
    restricted = RestrictedImplementationTools(root, scoped.submission_files,
        [str(path.relative_to(root.resolve())) for path in scoped.readable],
        submission_files=scoped.submission_files, self_test_files=scoped.self_test_files,
        test_files=scoped.test_files)
    try:
        while True:
            inputs = _implementation_inputs(root, card, completed, scoped)
            if state["phase"] == "tested":
                # 自测落盘后退出时直接恢复校验并提交，不再浪费一次实现调用。
                if scoped.restore_self_test(state["test"]):
                    submission = w.execute_tool(db, task, run, scoped,
                        ToolCall(str(uuid.uuid4()), "submit_unit_for_test", {}),
                        history_key=state["active_history_key"] + ":runtime-submit")
                    if submission.status != "succeeded":
                        raise RuntimeError("slice_restricted_submission_failed:" + str(submission.error))
                    state.update(phase="submitted", submission=submission.output)
                    w.write_json_atomic(state_path, state)
                    db.commit()
                    return "SUBMITTED_FOR_TEST"
                state["phase"] = "testing"
            if state["phase"] == "ready":
                if state["used_calls"] >= MAX_RESTRICTED_IMPLEMENTATION_CALLS:
                    raise RuntimeError("slice_restricted_call_budget_exceeded")
                if run.model_call_count >= w.MAX_MODEL_CALLS_PER_STEP:
                    raise RuntimeError("model_call_limit_exceeded")
                # 请求前预留额度并绑定文件版本；即使进程在模型响应期间退出也不返还额度。
                state.update(phase="implementing", used_calls=state["used_calls"] + 1,
                             before_hashes=scoped.submission_versions(), inputs=inputs)
                state["active_history_key"] = f'{state["history_prefix"]}:{state["used_calls"]}'
                w.write_json_atomic(state_path, state)
                response = w.model_tool_loop(db, task, run, load_prompt("slice-implementer"),
                    json.dumps(card, ensure_ascii=False), {
                        "card": card, "owned_files": scoped.submission_files,
                        "unit": {"id": card["id"]}, "unit_file_scope": list(inputs["file_hashes"]),
                        "implementation_inputs": inputs, "unit_test_feedback": state.get("test"),
                        "require_unit_submission": False,
                    }, restricted, tool_schemas=[schema for schema in TOOL_SCHEMAS
                                                 if schema["function"]["name"] in {"write", "replace"}]
                        + [REQUEST_REPLAN_SCHEMA],
                    stop_when=lambda: restricted.replan_reason is not None,
                    history_key=state["active_history_key"], max_calls=1, single_batch=True)
                state["response"] = response
                signal, detail = _control_signal(response)
                if restricted.replan_reason:
                    signal, detail = "REPLAN", restricted.replan_reason
                if signal in {"REPLAN", "BLOCKED"}:
                    state.update(phase=signal.lower(), detail=detail, response=f"{signal}: {detail}")
                    w.write_json_atomic(state_path, state)
                    scoped.replan_reason = detail if signal == "REPLAN" else None
                    return state["response"]
                state["phase"] = "testing"
                w.write_json_atomic(state_path, state)
            # 恢复时不重发已预留的模型调用；仅检查已落盘写入，部分写入由真实自测暴露。
            if state["phase"] == "implementing" and run.checkpoint_path:
                checkpoint = Path(run.checkpoint_path)
                entries = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.is_file() else []
                for entry in entries:
                    result = entry.get("result", {})
                    if (entry.get("history_key") == state["active_history_key"]
                            and entry.get("action", {}).get("tool_name") == "request_slice_replan"
                            and result.get("status") == "succeeded"):
                        detail = result["output"]["reason"]
                        state.update(phase="replan", detail=detail, response=f"REPLAN: {detail}")
                        w.write_json_atomic(state_path, state)
                        scoped.replan_reason = detail
                        return state["response"]
            if scoped.submission_versions() == state["before_hashes"]:
                raise RuntimeError("slice_restricted_no_file_change")
            # 自测及提交使用普通受控工具，模型无法自行调用或改变测试范围。
            result = w.execute_tool(db, task, run, scoped, ToolCall(str(uuid.uuid4()), "run_unit_tests", {}),
                                    history_key=state["active_history_key"] + ":runtime-test")
            if result.status != "succeeded":
                raise RuntimeError("slice_restricted_self_test_error:" + str(result.error))
            state["test"] = result.output
            pending_tests = sorted(set(remaining_todo_files(root)).intersection(card["test_files"]))
            state["test"]["remaining_todo_files"] = pending_tests
            if pending_tests:
                state["test"]["passed"] = False
            state["phase"] = "tested" if state["test"]["passed"] else "ready"
            w.write_json_atomic(state_path, state)
            db.commit()
    except Exception as exc:
        # 已失败的同一次尝试保留原错误与预算，恢复不能暗中开启新一轮付费请求。
        state.update(phase="failed", error=str(exc))
        w.write_json_atomic(state_path, state)
        raise


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
        try:
            # 恢复任务时重新校验旧待开发卡，防止规则升级前的错误所有权绕过 Planner 门禁。
            scaffold_path = root / "docs/scaffold-contract.json"
            scaffold = json.loads(scaffold_path.read_text(encoding="utf-8")) if scaffold_path.is_file() else None
            validate_card_dependencies(card, scaffold, completed)
        except ValueError as exc:
            decision = plan_next_slice(db, task, run, tools, plan, progress, str(exc), card)
            if decision is None:
                return
            if decision["action"] != "implement":
                raise RuntimeError("slice_replan_must_implement")
            card = decision["card"]
            pending["card"] = card
            w.write_json_atomic(root / pending["card_path"], card)
            pending.update(status="planned", attempt=0,
                           generation=int(pending.get("generation", 0)) + 1)
            _save_progress(root, progress)
            _write_index(root, progress)
            continue
        prior_tests = [path for entry in completed for path in entry["card"]["test_files"]]
        all_scope = list(dict.fromkeys([str(path.relative_to(root)) for path in w.product_files(root)]
                                       + card["implementation_files"] + card["test_files"]))
        current_tests = list(dict.fromkeys(prior_tests + card["test_files"]))
        command = "node --test " + " ".join(shlex.quote(str(Path(path).relative_to("product"))) for path in current_tests)
        feedback = pending.get("test") if pending.get("status") == "failed" else None
        start = (int(pending["attempt"]) if pending.get("status") == "developing"
                 else int(pending.get("attempt", 0)) + 1)
        generation = int(pending.get("generation", 0))
        for attempt in range(start, w.MAX_NO_CHANGE_CORRECTIONS + 2):
            scoped = SliceTools(root, card["implementation_files"] + card["test_files"],
                               all_scope + [pending["card_path"], "docs/product.md", "docs/architecture.md"],
                               submission_files=card["implementation_files"] + card["test_files"],
                               self_test_files=all_scope, test_files=current_tests)
            pending.update(status="developing", attempt=attempt)
            _save_progress(root, progress)
            response = run_slice_developer(db, task, run, card, completed, scoped,
                _slice_history_key("slice", card["id"], attempt, generation), feedback)
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


def handle_repair(db, task, run, tools: ToolRuntime) -> None:
    """把集成失败路由给拥有失败入口的已交付切片，并在提交后立即复跑原验证。"""
    from . import worker as w
    root = w.workspace_for(task)
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

    if verification_failure and w.verification_evidence_matches(task) is False:
        # 当前代码已不同于失败报告的验证版本；先复跑原验证，不消耗模型调用。
        command = f"{shlex.quote(w.sys.executable)} verify_product.py {shlex.quote(task.result_url)}"
        refreshed = w.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
            {"action": "run", "command": command}), history_key=f"stale-verification-refresh:{run.id}")
        report_path = w.write_verification_evidence(task, None, refreshed)
        if (refreshed.status == "succeeded" and refreshed.output.get("exit_code") == 0
                and "[SKIP]" not in refreshed.output.get("stdout", "")):
            run.output_path = "product/implementation.md"
            w.finish_step(db, task, run, Step.test)
            return

    card = owner["card"]
    owned_files = card["implementation_files"] + card["test_files"]
    all_scope = [str(path.relative_to(root)) for path in w.product_files(root)]
    failure = report_path.read_text(encoding="utf-8") if report_path.is_file() else "集成验证失败"
    scoped = SliceTools(root, owned_files, owned_files + [owner["card_path"], "docs/product.md", "docs/architecture.md"],
                        submission_files=owned_files, self_test_files=all_scope,
                        test_files=card["test_files"])
    failure_key = hashlib.sha256(failure.encode("utf-8")).hexdigest()[:12]
    budget_path, budgets, remaining_calls = _repair_budget(root, failure_key)
    if remaining_calls <= 0:
        raise RuntimeError("slice_repair_call_budget_exceeded")
    before_calls = run.model_call_count
    before_files = {path: (root / path).read_bytes() if (root / path).is_file() else None
                    for path in owned_files}

    def repair_file_changed() -> bool:
        """首次实际修改后立即停止模型循环，由程序复跑原失败验证。"""
        return any((root / path).is_file()
                   and before_files.get(path) != (root / path).read_bytes()
                   for path in owned_files)

    try:
        w.model_tool_loop(db, task, run, load_prompt("slice-developer"), json.dumps(card, ensure_ascii=False), {
            "card": card,
            "owned_files": owned_files,
            "unit": {"id": card["id"]},
            "unit_file_scope": owned_files,
            "require_unit_submission": False,
            "repair_round": task.repair_round,
            "provide_file_contents": False,
            "allow_history_detail": False,
            "repair_budget": {"failure_key": failure_key, "remaining_calls": remaining_calls},
            "unit_test_feedback": {"failure_source": "verify_product" if verification_failure else "test",
                                   "failure_report": failure,
                                   "instruction": "先核对验证脚本自身，再只修复该真实失败；修改后测试并提交。"},
            "passed_slices": [{"id": entry["card"]["id"]} for entry in completed],
        }, scoped, tool_schemas=[schema for schema in TOOL_SCHEMAS
                                 if schema["function"]["name"] in {"read", "write", "replace"}],
            stop_when=repair_file_changed,
            history_key=f"slice-repair:{card['id']}:{failure_key}",
            max_calls=remaining_calls)
    finally:
        _record_repair_calls(budget_path, budgets, failure_key, run.model_call_count - before_calls)
    if not repair_file_changed():
        raise RuntimeError("slice_repair_made_no_changes")
    command = (f"{shlex.quote(w.sys.executable)} verify_product.py {shlex.quote(task.result_url)}"
               if verification_failure else "node --test")
    result = w.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
        {"action": "run", "command": command}), history_key=f"slice-repair-test:{run.id}")
    if result.status != "succeeded" or result.output.get("exit_code") != 0:
        w.write_verification_evidence(task, None, result)
        raise RuntimeError("slice_repair_validation_failed")
    run.output_path = "product/implementation.md"
    w.finish_step(db, task, run, Step.test)
