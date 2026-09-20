import json
import difflib
import hashlib
import logging
import shlex
import shutil
import socket
import sys
import time
import uuid
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import Event, EventStatus, Message, Step, StepRun, StepStatus, Task, TaskStatus, TraceRecord
from .contracts import ModelRequest, ToolCall, ToolResult
from .model import ModelProtocolError, create_model_runtime
from .prompt_registry import PromptContent, sha256_text
from .tools import TOOL_SCHEMAS, QUERY_TOOL_SCHEMAS, ToolRuntime
from .tool_summaries import ToolSummaryStore
from .tracing import publish_live_response, safe_record_trace

NEXT_STEP = {
    Step.architecture_docs: Step.dev_design,
    Step.dev_design: Step.develop,
    Step.develop: Step.test,
    Step.test: Step.start_product,
    Step.start_product: Step.verify_product,
}
FIXED_PRODUCT_CONSTRAINTS = [
    "原生 HTML、CSS、JavaScript 软件，按确认架构划分模块和可测试功能", "使用 Node 内置测试框架",
    "使用 Python Playwright 验证真实浏览器", "本地 HTTP 启动与健康检查",
    "本地 HTTP 服务仅用于 Worker 预览和验证，不是生成产品的外部接口或主动网络请求",
    "不引入生成产品依赖或数据存储",
]
MAX_MODEL_CALLS_PER_STEP = 100
MAX_TRANSPORT_ATTEMPTS = 3
MAX_REPAIR_ROUNDS = 3
MAX_NO_CHANGE_CORRECTIONS = 2
MAX_IDENTICAL_TOOL_ACTIONS = 2
MAX_REPAIR_ACTIONS_WITHOUT_WRITE = 5
MAX_BUG_PLANNER_DECISIONS = 12
MAX_BUG_EXTRA_INSPECTIONS = 3

BASE_INSTRUCTIONS = """你是开发团队模拟器中的执行 Agent。严格完成当前 Step，不改变已确认需求、技术栈或流程。
你只能通过提供的工具读写当前任务工作区；不得访问工作区外资源。文件操作必须使用相对路径。
需要操作文件或运行命令时返回工具调用。所有要求完成且无需工具时才结束。"""


def _action_signature(action: ToolCall) -> str:
    # 把工具动作转换为可比较的稳定签名。
    return json.dumps({"tool_name": action.tool_name, "parameters": action.parameters},
                      ensure_ascii=False, sort_keys=True)


def unit_idle_calls(history: list[dict], versions: dict) -> int:
    # 按文件版本统计连续无进展模型批次，交替读取或修改描述也不能绕过。
    batches = set()
    for entry in reversed(history):
        if entry.get('unit_versions_before') != versions or entry.get('unit_versions_after') != versions:
            break
        batches.add(entry.get('model_request_id'))
    return len(batches)


def _recent_action_count(entries: list[dict], history_key: str, signature: str) -> int:
    # 统计同一上下文连续重复的工具动作次数。
    count = 0
    for entry in reversed(entries):
        if entry.get("history_key", "default") != history_key or not entry.get("action"):
            continue
        action = entry["action"]
        current = json.dumps({"tool_name": action.get("tool_name"),
                              "parameters": action.get("parameters")},
                             ensure_ascii=False, sort_keys=True)
        if current != signature:
            break
        count += 1
    return count


def _repair_actions_without_write(entries: list[dict], history_key: str) -> int:
    # 统计返修中连续未成功写入的工具动作次数。
    count = 0
    for entry in reversed(entries):
        if entry.get("history_key", "default") != history_key or not entry.get("action"):
            continue
        result = entry.get("result") or {}
        if entry["action"].get("tool_name") == "write" and result.get("status") == "succeeded":
            break
        count += 1
    return count


def _read_interval(parameters: dict) -> tuple[int, int]:
    # 把全文读取和局部读取归一为可比较的闭区间。
    start = parameters.get("start_line")
    end = parameters.get("end_line")
    return (start if type(start) is int else 1,
            end if type(end) is int else sys.maxsize)


def _unchanged_read_is_covered(entries: list[dict], history_key: str, action: ToolCall) -> bool:
    # 普通开发中拒绝再次读取同一未修改文件内已完整覆盖的行区间。
    if action.tool_name != "read":
        return False
    path = action.parameters.get("path") or action.parameters.get("file_path")
    if not path:
        return False
    intervals = []
    known_total = 0
    for entry in entries:
        if entry.get("history_key", "default") != history_key:
            continue
        previous = entry.get("action", {})
        previous_path = previous.get("parameters", {}).get("path") or previous.get("parameters", {}).get("file_path")
        result = entry.get("result", {})
        if previous_path != path or result.get("status") != "succeeded":
            continue
        if previous.get("tool_name") in {"write", "replace"}:
            intervals = []
            continue
        if previous.get("tool_name") != "read":
            continue
        output = result.get("output") or {}
        start = output.get("start_line", 1)
        end = output.get("end_line", output.get("total_lines"))
        total = output.get("total_lines")
        if type(total) is int:
            known_total = max(known_total, total)
        if type(start) is int and type(end) is int and end >= start:
            intervals.append((start, end))
    requested_start, requested_end = _read_interval(action.parameters)
    if requested_end == sys.maxsize:
        if not intervals or not known_total or not any(start == 1 for start, _ in intervals):
            return False
        requested_end = known_total
    covered_until = requested_start - 1
    for start, end in sorted(intervals):
        if start > covered_until + 1:
            break
        if end >= requested_start:
            covered_until = max(covered_until, end)
        if covered_until >= requested_end:
            return True
    return False


def _covered_read_requires_progress(entries: list[dict], history_key: str,
                                    model_request_id: str, action: ToolCall) -> bool:
    # 重复读取被拒绝后，持续要求写入、自测或重规划，避免模型改读其他已知文件空转。
    relevant = [entry for entry in entries if entry.get("history_key", "default") == history_key]
    guard_index = None
    guard_request_id = None
    for index in range(len(relevant) - 1, -1, -1):
        entry = relevant[index]
        result = entry.get("result") or {}
        if result.get("status") == "failed" and result.get("error") == "unchanged_file_read_already_covered":
            guard_index = index
            guard_request_id = entry.get("model_request_id")
            break
    if guard_index is None:
        return False
    allowed = {"write", "run_unit_tests", "request_slice_replan"}
    for entry in relevant[guard_index + 1:]:
        if entry.get("model_request_id") == guard_request_id:
            continue
        if (entry.get("action", {}).get("tool_name") in allowed
                and entry.get("result", {}).get("status") == "succeeded"):
            return False
    return model_request_id != guard_request_id and action.tool_name not in allowed


def _repeated_failed_self_test_read(entries: list[dict], history_key: str, action: ToolCall) -> bool:
    # 自测失败后阻止读取同一未变文件的重叠区域，迫使流程进入修改、重规划或阻塞。
    if action.tool_name != "read":
        return False
    relevant = [entry for entry in entries if entry.get("history_key", "default") == history_key]
    failure_index = None
    for index in range(len(relevant) - 1, -1, -1):
        entry = relevant[index]
        if (entry.get("action", {}).get("tool_name") == "run_unit_tests"
                and entry.get("result", {}).get("status") == "succeeded"
                and entry.get("result", {}).get("output", {}).get("passed") is False):
            failure_index = index
            break
    if failure_index is None:
        return False
    later = relevant[failure_index + 1:]
    if any(entry.get("action", {}).get("tool_name") in {"write", "replace"}
           and entry.get("result", {}).get("status") == "succeeded" for entry in later):
        return False
    path = action.parameters.get("path")
    requested_start, requested_end = _read_interval(action.parameters)
    for entry in later:
        previous = entry.get("action", {})
        if (previous.get("tool_name") != "read" or previous.get("parameters", {}).get("path") != path
                or entry.get("result", {}).get("status") != "succeeded"):
            continue
        previous_start, previous_end = _read_interval(previous.get("parameters", {}))
        if max(requested_start, previous_start) <= min(requested_end, previous_end):
            return True
    return False


def _failed_unit_change_requires_test(entries: list[dict], history_key: str,
                                      model_request_id: str, action: ToolCall,
                                      external_failure: bool = False) -> bool:
    # 失败修复产生文件变化后，下一批只能复测，不能重新读取或继续跨批修改。
    relevant = [entry for entry in entries if entry.get("history_key", "default") == history_key]
    failed = external_failure
    pending_change = None
    for entry in relevant:
        tool_name = entry.get("action", {}).get("tool_name")
        result = entry.get("result", {})
        if (tool_name == "run_unit_tests" and result.get("status") == "succeeded"):
            failed = result.get("output", {}).get("passed") is False
            pending_change = None
        elif (failed and tool_name in {"write", "replace"}
              and result.get("status") == "succeeded"):
            pending_change = entry.get("model_request_id")
    return bool(pending_change and pending_change != model_request_id
                and action.tool_name != "run_unit_tests")


def _unit_change_requires_test(entries: list[dict], history_key: str,
                               model_request_id: str, action: ToolCall) -> bool:
    # 普通单元开发跨批成功写入后也必须立即自测，用真实结果替代继续读取确认。
    pending_change = None
    for entry in entries:
        if entry.get("history_key", "default") != history_key:
            continue
        tool_name = entry.get("action", {}).get("tool_name")
        result = entry.get("result", {})
        if tool_name == "run_unit_tests" and result.get("status") == "succeeded":
            pending_change = None
        elif tool_name in {"write", "replace"} and result.get("status") == "succeeded":
            pending_change = entry.get("model_request_id")
    return bool(pending_change and pending_change != model_request_id
                and action.tool_name != "run_unit_tests")


def workspace_for(task: Task) -> Path:
    # 解析当前任务的独立工作区路径。
    return Path(task.workspace_path or settings.workspace_root / str(task.id)).resolve()


def add_message(db: Session, task: Task, role: str, content: str):
    # 持久化一条任务消息并取得数据库 ID。
    message = Message(task_id=task.id, role=role, content=content)
    db.add(message)
    db.flush()
    return message


def _load_ledger(path: Path) -> list[dict]:
    # 读取工作区账本，不存在时返回空列表。
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def _save_ledger(path: Path, value: list[dict]) -> None:
    # 以临时文件替换方式保存工作区账本。
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _is_question_message(content: str) -> bool:
    # 识别需要与用户回答配对的模型问题。
    stripped = content.strip()
    return stripped.startswith("BLOCKED") or (not stripped.startswith("{") and ("?" in stripped or "？" in stripped))


def sync_conversation_turns(task: Task, run: StepRun, messages: list[Message]) -> list[dict]:
    # 将模型问题和用户回答同步为成对问答账本。
    path = workspace_for(task) / "evidence" / "conversation-turns.json"
    # 从持久化账本恢复成对问答，保留用户回答的指代。
    turns = _load_ledger(path)
    by_question = {turn.get("question", {}).get("message_id"): turn for turn in turns}
    pending: Message | None = None
    changed = False
    for message in messages:
        if message.role == "assistant" and _is_question_message(message.content):
            pending = message
        elif message.role == "user" and pending is not None:
            existing = by_question.get(pending.id)
            if existing and existing.get("status") == "open":
                existing["answer"] = {"message_id": message.id, "content": message.content}
                existing["status"] = "answered"
                existing["turn_id"] = f"qa-{pending.id}-{message.id}"
                changed = True
            elif not existing:
                turn = {
                    "turn_id": f"qa-{pending.id}-{message.id}",
                    "question": {"message_id": pending.id, "content": pending.content},
                    "answer": {"message_id": message.id, "content": message.content},
                    "status": "answered", "step_run_id": run.id, "actions": [],
                }
                turns.append(turn)
                by_question[pending.id] = turn
                changed = True
            pending = None
    if pending is not None and pending.id not in by_question:
        turns.append({"turn_id": f"qa-{pending.id}-open",
                      "question": {"message_id": pending.id, "content": pending.content},
                      "answer": None, "status": "open", "step_run_id": run.id, "actions": []})
        changed = True
    if changed:
        # 只有问答状态变化时才更新持久化账本。
        _save_ledger(path, turns)
    return turns


def record_written_artifact(db: Session, task: Task, run: StepRun, call: ToolCall, result: Any) -> None:
    # 为成功写入的文件记录来源、哈希和 Trace。
    if call.tool_name != "write" or result.status != "succeeded":
        return
    requested = str(call.parameters.get("path", ""))
    resolved = (workspace_for(task) / requested).resolve()
    if not resolved.is_file() or workspace_for(task) not in resolved.parents:
        return
    # 记录文件哈希、工具调用和阶段来源，供后续返修核对。
    artifact = {
        "tool_call_id": call.call_id, "requested_path": requested,
        "resolved_path": str(resolved), "name": resolved.name,
        "operation": "overwrite" if call.parameters.get("overwrite") else "create",
        "bytes_written": result.output.get("bytes_written"),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "step_run_id": run.id, "step": run.step.value, "attempt": run.attempt,
        "turn_id": None,
    }
    turns_path = workspace_for(task) / "evidence" / "conversation-turns.json"
    # 从持久化账本恢复成对问答，保留用户回答的指代。
    turns = _load_ledger(turns_path)
    answered = [turn for turn in turns if turn.get("status") == "answered"]
    if answered:
        artifact["turn_id"] = answered[-1]["turn_id"]
        answered[-1].setdefault("actions", []).append({"type": "write", **artifact})
        _save_ledger(turns_path, turns)
    artifacts_path = workspace_for(task) / "evidence" / "artifacts.json"
    artifacts = _load_ledger(artifacts_path)
    artifacts.append(artifact)
    _save_ledger(artifacts_path, artifacts)
    # 把新产物加入任务时间线。
    safe_record_trace(db, task, run, "artifact", "succeeded", f"文件：{resolved.name}",
                      requested, artifact, {"path": requested, "name": resolved.name,
                                             "tool_call_id": call.call_id, "sha256": artifact["sha256"]})


def create_step_run(db: Session, task: Task) -> StepRun:
    # 复用运行中的阶段执行或创建下一次执行记录。
    # 先复用正在运行的 StepRun，保证重启恢复。
    existing = db.scalar(select(StepRun).where(
        StepRun.task_id == task.id, StepRun.step == task.cur_step, StepRun.status == StepStatus.running
    ).order_by(StepRun.attempt.desc()))
    if existing:
        return existing
    attempt = (db.scalar(select(func.max(StepRun.attempt)).where(
        StepRun.task_id == task.id, StepRun.step == task.cur_step)) or 0) + 1
    checkpoint = workspace_for(task) / "evidence" / f"{task.cur_step.value}-{attempt}-checkpoint.json"
    run = StepRun(task_id=task.id, step=task.cur_step, attempt=attempt,
                  checkpoint_path=str(checkpoint), last_completed_action_index=-1)
    db.add(run)
    db.flush()
    safe_record_trace(db, task, run, "step", "running", "阶段开始",
                      f"开始执行 {task.cur_step.value}", {"step": task.cur_step.value, "attempt": attempt},
                      started_at=run.started_at)
    return run


def execute_tool(db: Session, task: Task, run: StepRun, tools: ToolRuntime, call: ToolCall,
                 parent_model_call_id: str | None = None, history_key: str = "system",
                 blocked_error: str | None = None):
    # 执行工具并记录调用、结果及写入产物。
    started = datetime.utcnow()
    store = ToolSummaryStore(workspace_for(task))
    before = store.file_state(call.parameters.get("path")) if call.tool_name in {"read", "write"} else {}
    # 在执行前绑定文件版本，验证结束后不能用已修改文件冒充执行时版本。
    code_hashes = product_code_hashes(task) if call.tool_name == "exec" and call.parameters.get("action") == "run" else {}
    call_trace = safe_record_trace(db, task, run, "tool_call", "running", f"调用 {call.tool_name}",
                      str(call.parameters.get("path") or call.parameters.get("command") or call.parameters.get("action", "")),
                      {"call_id": call.call_id, "tool_name": call.tool_name, "parameters": call.parameters},
                      started_at=started)
    # 调用受控工具运行时，随后保存完整结果 Trace。
    result = ToolResult(call.call_id, call.tool_name, "failed", {}, blocked_error) if blocked_error else tools.execute(call)
    finished = datetime.utcnow()
    result_trace = safe_record_trace(db, task, run, "tool_result", result.status,
                      f"{call.tool_name} 执行{'成功' if result.status == 'succeeded' else '失败'}",
                      result.error or str(result.output.get("path") or result.output.get("exit_code") or ""),
                      {"call_id": call.call_id, "tool_name": call.tool_name,
                       "result": result.__dict__}, started_at=started, finished_at=finished)
    record_written_artifact(db, task, run, call, result)
    try:
        # 摘要保存失败也必须把真实结果交回检查点，不重执行已有副作用。
        store.record(run.id, history_key, parent_model_call_id, call, result, before,
                     {"call": call_trace.detail_path if call_trace else None,
                      "result": result_trace.detail_path if result_trace else None}, code_hashes, bool(blocked_error))
    except (OSError, ValueError, TypeError) as exc:
        logging.getLogger(__name__).warning("Tool summary unavailable: %s", type(exc).__name__)
    return result


def save_checkpoint(run: StepRun, entries: list[dict]):
    # 原子保存阶段工具历史检查点。
    path = Path(run.checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def atomic_copy(source: Path, target: Path):
    # 通过临时文件原子复制正式产物。
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(target)


def write_json_atomic(path: Path, value: dict):
    # 通过临时文件原子保存 JSON 证据。
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def content_hash(text: str) -> str:
    # 计算文本内容的 SHA-256。
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unified_text_diff(previous: str, current: str, previous_name: str, current_name: str) -> str:
    # 生成新旧文档的统一格式差异。
    return "".join(difflib.unified_diff(
        previous.splitlines(keepends=True), current.splitlines(keepends=True),
        fromfile=previous_name, tofile=current_name,
    ))


def parse_transition_decision(text: str, kind: str, required_update: bool = False) -> dict:
    # 将设计阶段 Planner 的具体下一行动映射为现有文档执行器的修订或复用。
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        value = {}
    next_action = value.get("action")
    confidence = value.get("confidence", 0)
    revise_action = "update_architecture" if kind == "architecture" else "update_dev_design"
    reuse_action = "update_dev_design" if kind == "architecture" else "modify_code"
    if next_action == revise_action:
        action = "revise"
    elif next_action == reuse_action and not required_update:
        action = "reuse"
    else:
        action = "clarify"
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        action = "clarify"
        confidence = 0
    if confidence < 0.7:
        action = "clarify"
    return {
        "action": action,
        "next_action": next_action if action != "clarify" else "clarify",
        "reason": str(value.get("reason", "证据不足，无法安全决定下一步")),
        "affected_sections": value.get("affected_sections")
        if isinstance(value.get("affected_sections"), list) else [],
        "preserved_sections": value.get("preserved_sections")
        if isinstance(value.get("preserved_sections"), list) else [],
        "confidence": confidence,
        "clarifying_question": value.get("clarifying_question") or
        "请说明这次修改期望改变哪些行为，以及哪些现有行为必须保持不变。",
    }


def build_tool_context(task: Task, run: StepRun, context: dict, history: list[dict], history_key: str) -> dict:
    # 每次逻辑调用重建工具投影，刷新文件版本，不改变原始检查点。
    root = workspace_for(task)
    hashes = product_code_hashes(task)
    try:
        projected = ToolSummaryStore(root).project(history, run.id, history_key, hashes)
    except (OSError, ValueError, TypeError) as exc:
        # 账本暂不可用时沿用完整历史，保证执行连续性。
        logging.getLogger(__name__).warning("Tool context projection unavailable: %s", type(exc).__name__)
        projected = {"tool_history": history, "tool_summaries": [], "summary_unavailable": True}
    value = {**context, **projected}
    paths = product_files(root)
    value["product_file_manifest"] = [
        {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in paths]
    if "existing_product_files" in value:
        value["existing_product_files"] = [str(path.relative_to(root)) for path in paths]
    if "unit_file_scope" in context:
        # 单元开发只刷新当前单元与依赖范围，避免轮内读取结果立即丢失。
        scope = set(context["unit_file_scope"])
        paths = [path for path in paths if str(path.relative_to(root)) in scope]
    provide_file_contents = context.get("provide_file_contents", True)
    if provide_file_contents and (context.get("current_product_files") or "unit_file_scope" in context):
        # 首次开发可提供范围内快照；返修默认只给清单与哈希，源码由模型按需读取。
        contents = {str(path.relative_to(root)): path.read_text(encoding="utf-8", errors="replace") for path in paths}
        for entry in projected["tool_history"]:
            action = entry.get("action", {})
            parameters = action.get("parameters", {})
            result = entry.get("result", {})
            output = result.get("output", {})
            path = parameters.get("path")
            content = parameters.get("content") if action.get("tool_name") == "write" else output.get("content") if action.get("tool_name") == "read" and not output.get("truncated") else None
            if result.get("status") == "succeeded" and path in contents and content == contents[path]:
                contents.pop(path)
        value["current_product_files"] = contents
        value["current_files_omitted_as_recent_fulltext"] = len(paths) - len(contents)
        requested = []
        for result in value.get('current_requested_data', []):
            # 按需读取全文已在当前快照中时只返回引用，原始 Trace／检查点不修改。
            output = dict(result.get('output') or {})
            if result.get('tool_name') == 'read' and output.get('content') is not None and not output.get('truncated') and contents.get(output.get('path')) == output['content']:
                output.pop('content')
                output['content_source'] = 'current_product_files'
            requested.append({**result, 'output':output})
        value['current_requested_data'] = requested
    if 'unit_file_scope' in context:
        # 当前单元交接提示依据缺失文件与真实测试反馈，文件存在不等于测试通过。
        missing = [path for path in context.get('owned_files', context['unit_file_scope']) if not (root / path).is_file()]
        feedback = context.get('unit_test_feedback')
        self_test = context.get('unit_self_test')
        current_versions = {path:hashlib.sha256((root / path).read_bytes()).hexdigest() if (root / path).is_file() else None
                            for path in (self_test or feedback or {}).get('file_hashes_after', {})}
        evidence = self_test or feedback
        matches = bool(evidence and evidence.get('file_hashes_after') == current_versions)
        state = 'passed' if matches and evidence.get('passed') else 'failed' if matches else 'stale' if evidence else 'not_run'
        if not context.get('require_unit_submission') and feedback and feedback.get('passed') is False:
            # 旧无计划入口保留原失败提示，不要求旧报告补齐新增自测协议。
            state = 'failed'
        # 旧失败保留修复依据，同时明确当前版本是否仍适用，不把改动视为成功。
        for field, versions_field in [('unit_test_feedback', 'file_hashes_after'), ('global_failure', 'file_hashes')]:
            report = context.get(field)
            if report:
                versions = report.get(versions_field)
                current = {path:hashlib.sha256((root / path).read_bytes()).hexdigest() if (root / path).is_file() else None
                           for path in versions or {}}
                value[field] = {**report, 'matches_current_files':versions == current if versions is not None else None}
        value['test_evidence_matches_current_files'] = matches
        value['development_state'] = {'unit_id':context.get('unit', {}).get('id'), 'missing_owned_files':missing,
            'test_state':state,
            'next_action':'develop_missing_files' if missing else 'repair_current_unit_from_test_feedback' if state == 'failed' else
                'submit_unit_for_test' if state == 'passed' and self_test and context.get('require_unit_submission') else
                'run_unit_tests' if context.get('require_unit_submission') else 'finish_development_for_program_test',
            'file_presence_is_not_test_pass':True}
    return value


def model_tool_loop(db: Session, task: Task, run: StepRun, instructions: str | PromptContent, input_text: str,
                    context: dict, tools: ToolRuntime,
                    stop_when: Callable[[], bool] | None = None,
                    tool_schemas: list[dict] | None = None,
                    history_key: str = "default",
                    runtime_step: Step | None = None,
                    max_calls: int | None = None,
                    single_batch: bool = False) -> str:
    # 在预算内循环调用模型、执行工具并保存过程证据。
    if max_calls is not None and (type(max_calls) is not int or max_calls <= 0):
        raise ValueError("model_loop_max_calls_invalid")
    initial_model_call_count = run.model_call_count
    prompt = instructions if isinstance(instructions, PromptContent) else None
    instruction_text = prompt.text if prompt else instructions
    checkpoint = Path(run.checkpoint_path) if run.checkpoint_path else None
    checkpoint_entries: list[dict] = []
    history: list[dict] = []
    # 恢复已有检查点中的工具历史，避免 Worker 重启后重复执行。
    if checkpoint and checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if isinstance(saved, list):
            checkpoint_entries = saved
            # 对摘要已落盘的执行恢复原始结果，不能重新发起已完成的副作用。
            store = ToolSummaryStore(workspace_for(task))
            for index, entry in enumerate(checkpoint_entries):
                if entry.get("action") and not entry.get("result"):
                    recovered = store.recover_result(run.id, entry.get("model_request_id"), entry["action"]["call_id"])
                    if recovered is not None:
                        entry["result"] = recovered
                        if recovered.get("status") == "succeeded":
                            run.last_completed_action_index = max(run.last_completed_action_index, index)
            save_checkpoint(run, checkpoint_entries)
            history = [entry for entry in checkpoint_entries
                       if entry.get("result") and entry.get("history_key", "default") == history_key]
    # 已持久化的推进违约直接交回切片 Runtime，恢复不能重新请求旧对话。
    if context.get("switch_on_progress_violation") and any(
            entry.get("result", {}).get("error") == "covered_read_requires_write_test_or_replan"
            for entry in history):
        return "DEVELOPER_PROGRESS_SWITCH"
    # 根据阶段选择主 Provider，技术失败时才尝试受控降级。
    primary_runtime = create_model_runtime(db, runtime_step or task.cur_step)
    text_without_submit = 0
    if context.get('require_unit_submission'):
        # 恢复开发自测证据，过期结果只能作为旧失败依据，不能授权提交。
        for entry in reversed(history):
            if entry.get('action', {}).get('tool_name') == 'run_unit_tests' and entry.get('result', {}).get('status') == 'succeeded':
                output = entry['result'].get('output', {})
                tools.self_test = output
                tools.restore_self_test(output)
                break
        # 提交与检查点之间中断时恢复版本一致的交接，不靠文件存在推断完成。
        for entry in reversed(history):
            if entry.get('action', {}).get('tool_name') == 'submit_unit_for_test' and entry.get('result', {}).get('status') == 'succeeded':
                if tools.restore_submission(entry['result'].get('output', {})):
                    return 'SUBMITTED_FOR_TEST'
                break
    while (run.model_call_count < MAX_MODEL_CALLS_PER_STEP
           and (max_calls is None or run.model_call_count - initial_model_call_count < max_calls)):
        if context.get('require_unit_submission'):
            from .unit_workflow import file_hashes
            versions = file_hashes(workspace_for(task), context['owned_files'])
            idle = unit_idle_calls(history, versions)
            self_test_current = bool(tools.self_test and tools.restore_self_test(tools.self_test))
            if idle >= 8 and not self_test_current:
                raise RuntimeError('unit_development_no_progress')
            context = {**context, 'unit_self_test':tools.self_test, 'unit_no_progress':{'calls_without_file_change':idle,
                'instruction':('当前版本自测已通过，下一步只能立即调用 submit_unit_for_test，不要再读取或诊断。'
                               if self_test_current else
                               '先自测，通过后提交；确有设计阻塞说明 BLOCKED，禁止重复读取未变文件' if idle >= 4 else ''),
                'submission_required':True}}
        # 每次逻辑模型调用先计入阶段预算并持久化。
        run.model_call_count += 1
        db.commit()
        stream_parts = []
        last_publish = 0.0
        def on_delta(delta: str) -> None:
            # 限频发布临时回答快照，不写数据库或永久 Trace。
            nonlocal last_publish
            stream_parts.append(delta)
            if time.monotonic() - last_publish >= 0.25:
                publish_live_response(str(workspace_for(task)), request.request_id, "".join(stream_parts))
                last_publish = time.monotonic()
        # 只给执行阶段增加只读查询，保持无工具 Planner 和文档作者的原边界。
        schemas = TOOL_SCHEMAS if tool_schemas is None else tool_schemas
        if any(schema["function"]["name"] in {"read", "exec"} for schema in schemas):
            query_schemas = QUERY_TOOL_SCHEMAS
            if context.get("allow_history_detail") is False:
                # 返修只允许摘要查询，禁止重新取回包含整文件写入参数的原始历史详情。
                query_schemas = [schema for schema in query_schemas
                                 if schema["function"]["name"] != "get_tool_execution_detail"]
            schemas = schemas + query_schemas
        tool_instructions = "每次工具调用用 description 简述目的。当前文件版本以 product_file_manifest 为准；tool_summaries 是当前循环按文件合并的最近读取／写入状态，不是历史流水。current_requested_data 返回本次请求的读取／查询数据。已完整读取且哈希未变的文件不要重复读。development_state 是当前单元交接提示，文件齐备不等于测试通过；按 next_action 进行自测、修复或交接；require_unit_submission=true 时必须调用 submit_unit_for_test，普通完成文本不能替代提交。仅可使用本次提供的工具。earlier_summary_count 表示省略的文件状态数。不得把历史执行成功当作当前代码已验证。"
        if context.get("provide_file_contents", True):
            # 首次开发说明预载源码的引用规则，返修不声称存在全文快照。
            tool_instructions += "content_source=current_product_files 表示全文已在当前快照。"
        else:
            # 返修只携带失败证据与文件版本，要求围绕报错位置局部读取。
            tool_instructions += "返修上下文不预载源码；只按失败位置 read 必要行，不查询原始历史详情。"
        if context.get('require_unit_submission'):
            # 开发自测与后续独立验证分开，旧失败不代表修改后的版本仍失败。
            tool_instructions += '开发必须先 run_unit_tests 自测，当前版本通过后才 submit_unit_for_test。修改使旧结果过期，应重新自测；unit_self_test 返回真实自测结果，旧 unit_test_feedback/global_failure 是修复依据，不能认定未复测的新版本仍有原错误。'
        if context.get('require_unit_submission') and context['unit_no_progress']['calls_without_file_change'] >= 4:
            # 无进展提醒同步提升到系统指令，避免只埋在较长文件上下文中被忽略。
            tool_instructions += ('【交接提醒】当前版本自测已通过，本轮只能调用 submit_unit_for_test，不要读取、诊断或重新测试。'
                                  if context['unit_self_test'] and context['unit_self_test'].get('passed') else
                                  '【无进展提醒】已连续多轮没有文件版本变化，不要再次读取已提供的文件。缺交付文件则补齐；无需修改时先 run_unit_tests，当前版本通过后立即 submit_unit_for_test。确有设计阻塞只输出 BLOCKED: 和具体问题。剩余无进展额度耗尽将停止，不会自动测试或放宽权限。')
        if any(schema["function"]["name"] == "get_tool_execution_detail" for schema in schemas):
            tool_instructions += "需要旧操作时用 get_file_change_history 或 get_model_call_summaries，需要原始历史参数/结果时用 get_tool_execution_detail；最新文件内容用 read。"
        request_id = str(uuid.uuid4())
        request_context = {**build_tool_context(task, run, context, history, history_key), "model_call_id": request_id}
        request = ModelRequest(instructions=f"{BASE_INSTRUCTIONS}\n\n{instruction_text}\n\n{tool_instructions}", input=input_text,
                               context=request_context,
                               tools=schemas,
                               request_id=request_id, on_delta=on_delta)
        runtimes = [primary_runtime]
        if primary_runtime.provider == "kimi":
            runtimes.append(create_model_runtime(db, Step.develop))
        result = None
        protocol_error: ModelProtocolError | None = None
        final_error: Exception | None = None
        for provider_index, runtime in enumerate(runtimes):
            safe_record_trace(db, task, run, "model_request", "running", "请求模型",
                              f"第 {run.model_call_count} 次逻辑调用" +
                              ("（降级）" if provider_index else ""),
                              {"request_id": request.request_id,
                               "payload": runtime.build_payload(request)},
                              {"history_key": history_key, "request_id": request.request_id,
                               "model_call_count": run.model_call_count,
                               "provider": runtime.provider, "model": runtime.model_name,
                               "fallback": provider_index > 0,
                               "prompt_name": prompt.name if prompt else "legacy-inline",
                               "prompt_version": prompt.version if prompt else "unversioned",
                               "prompt_template_sha256": prompt.template_sha256 if prompt else sha256_text(instruction_text),
                               "prompt_rendered_sha256": prompt.rendered_sha256 if prompt else sha256_text(instruction_text),
                               "runtime_context_sha256": sha256_text(json.dumps(request_context, ensure_ascii=False, sort_keys=True, default=str))},
                              started_at=datetime.utcnow())
            last_transport_error: Exception | None = None
            protocol_error = None
            # 传输重试与逻辑调用分别计数，并记录每次失败。
            for transport_attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
                try:
                    # 执行真实模型请求；协议错误与传输错误采用不同处理路径。
                    stream_parts.clear()
                    last_publish = 0.0
                    try:
                        result = runtime.call(task.id, request)
                    except (httpx.HTTPError, ModelProtocolError) as exc:
                        # 中断时只归档合并的部分响应和错误，不归档流式事件。
                        safe_record_trace(db, task, run, "model_interrupted", "failed", "模型调用中断",
                                          type(exc).__name__,
                                          {"request_id": request.request_id,
                                           "partial_response": getattr(exc, "response_body", {"text": "".join(stream_parts)})},
                                          {"provider": runtime.provider, "model": runtime.model_name})
                        db.commit()
                        raise
                    finally:
                        publish_live_response(str(workspace_for(task)), "", "")
                    break
                except ModelProtocolError as exc:
                    protocol_error = exc
                    final_error = exc
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    final_error = exc
                    if status_code < 500 and status_code != 429:
                        last_transport_error = exc
                        break
                    last_transport_error = exc
                    entry = {"history_key": history_key, "model_request_id": request.request_id,
                             "model_error": type(exc).__name__, "status_code": status_code,
                             "transport_attempt": transport_attempt, "provider": runtime.provider}
                except httpx.TransportError as exc:
                    last_transport_error = exc
                    final_error = exc
                    entry = {"history_key": history_key, "model_request_id": request.request_id,
                             "model_error": type(exc).__name__, "transport_attempt": transport_attempt,
                             "provider": runtime.provider}
                except RuntimeError as exc:
                    final_error = exc
                    last_transport_error = exc
                    break
                checkpoint_entries.append(entry)
                save_checkpoint(run, checkpoint_entries)
                safe_record_trace(db, task, run, "model_retry", "failed", "模型传输失败",
                                  f"第 {transport_attempt} 次传输失败：{type(last_transport_error).__name__}", entry,
                                  {"history_key": history_key, "transport_attempt": transport_attempt,
                                   "provider": runtime.provider, "model": runtime.model_name})
                db.commit()
                if transport_attempt < MAX_TRANSPORT_ATTEMPTS:
                    time.sleep(0.5 * (2 ** (transport_attempt - 1)))
            if result is not None:
                break
            # 主 Provider 技术失败后用原始上下文降级一次。
            if provider_index == 0 and len(runtimes) > 1:
                safe_record_trace(db, task, run, "model_fallback", "info", "模型技术降级",
                                  f"{runtime.provider} → {runtimes[1].provider}",
                                  {"request_id": request.request_id,
                                   "reason": (protocol_error.code if protocol_error
                                              else type(final_error).__name__)},
                                  {"from_provider": runtime.provider,
                                   "to_provider": runtimes[1].provider,
                                   "model_call_count": run.model_call_count})
                db.commit()
                continue
        if result is None and not protocol_error:
            raise RuntimeError(f"model_transport_failed:{type(final_error).__name__}") from final_error
        # 保留非法响应原文，并按协议失败策略决定继续或终止。
        if protocol_error:
            entry = {"history_key": history_key, "model_request_id": request.request_id,
                     "model_error": protocol_error.code}
            checkpoint_entries.append(entry)
            save_checkpoint(run, checkpoint_entries)
            safe_record_trace(db, task, run, "model_response", "failed", "模型响应协议错误",
                              protocol_error.code,
                              {"request_id": request.request_id,
                               "raw_response": protocol_error.response_body},
                              {"history_key": history_key, "request_id": request.request_id,
                               "provider": runtime.provider,
                               "model": runtime.model_name}, finished_at=datetime.utcnow())
            db.commit()
            if primary_runtime.provider == "kimi" and runtime.provider == "deepseek":
                raise RuntimeError(f"model_protocol_failed:{protocol_error.code}") from protocol_error
            context = {**context, "model_protocol_feedback": {
                "error": protocol_error.code,
                "instruction": "上一响应的工具参数无效或被截断。不要原样重试；显著压缩输出，确保工具参数 JSON 完整，并严格遵守指令中的字符上限。",
            }}
            continue
        db.commit()
        safe_record_trace(db, task, run, "model_response", "succeeded", "收到模型响应",
                          result.finish_reason,
                          {"request_id": result.request_id, "text": result.text,
                           "actions": [action.__dict__ for action in result.actions],
                           "raw_response": result.raw_response},
                          {"history_key": history_key, "request_id": result.request_id,
                           "message_id": result.message_id,
                           "provider": runtime.provider, "model": runtime.model_name},
                          finished_at=datetime.utcnow())
        if tool_schemas == [] and result.actions:
            raise RuntimeError("model_tool_call_not_allowed")
        if not result.actions:
            if context.get('require_unit_submission') and not result.text.strip().startswith('BLOCKED:'):
                # 普通完成文本不能绕过显式提交，最多两次纠正后停止。
                text_without_submit += 1
                if text_without_submit > MAX_NO_CHANGE_CORRECTIONS:
                    raise RuntimeError('unit_submission_required')
                context = {**context, 'submission_feedback':'必须调用 submit_unit_for_test，普通结束文本不代表提交。'}
                continue
            return result.text
        # 工具执行前保存待办检查点，便于故障恢复。
        for index, action in enumerate(result.actions, start=run.last_completed_action_index + 1):
            guard_code = None
            entry = {"history_key": history_key, "model_request_id": result.request_id,
                     "action": action.__dict__}
            if context.get('require_unit_submission'):
                entry['unit_versions_before'] = file_hashes(workspace_for(task), context['owned_files'])
            entries = checkpoint_entries + [entry]
            save_checkpoint(run, entries)
            signature = _action_signature(action)
            repeated = _recent_action_count(checkpoint_entries, history_key, signature)
            repair_without_write = (context.get("repair_round", 0) > 0
                                    and action.tool_name != "write"
                                    and _repair_actions_without_write(checkpoint_entries, history_key)
                                    >= MAX_REPAIR_ACTIONS_WITHOUT_WRITE)
            repeated_failed_read = (context.get('require_unit_submission')
                                    and _repeated_failed_self_test_read(checkpoint_entries, history_key, action))
            covered_unchanged_read = (context.get('require_unit_submission')
                                      and _unchanged_read_is_covered(checkpoint_entries, history_key, action))
            covered_read_requires_progress = (context.get('require_unit_submission')
                                              and _covered_read_requires_progress(
                                                  checkpoint_entries, history_key,
                                                  result.request_id, action))
            unit_feedback = context.get('unit_test_feedback') or {}
            change_requires_test = (context.get('require_unit_submission')
                                    and _failed_unit_change_requires_test(
                                        checkpoint_entries, history_key, result.request_id, action,
                                        external_failure=unit_feedback.get('passed') is False))
            unit_change_requires_test = (context.get('require_unit_submission')
                                         and _unit_change_requires_test(
                                             checkpoint_entries, history_key,
                                             result.request_id, action))
            # 阻止连续重复动作和返修中无写入循环。
            invalid_submit = (context.get('require_unit_submission') and action.tool_name == 'submit_unit_for_test'
                              and action is not result.actions[-1])
            if (repeated >= MAX_IDENTICAL_TOOL_ACTIONS or repair_without_write or invalid_submit
                    or repeated_failed_read or covered_unchanged_read
                    or covered_read_requires_progress or change_requires_test
                    or unit_change_requires_test):
                # 阻止连续重复动作和返修中无写入循环。
                code = ('submission_must_be_last' if invalid_submit else
                        'unit_change_requires_self_test' if (change_requires_test or unit_change_requires_test) else
                        'self_test_repeated_read_requires_change' if repeated_failed_read else
                        'covered_read_requires_write_test_or_replan' if covered_read_requires_progress else
                        'unchanged_file_read_already_covered' if covered_unchanged_read else
                        "repeated_tool_action" if repeated >= MAX_IDENTICAL_TOOL_ACTIONS else
                        "repair_tool_loop_no_write")
                guard_code = code
                safe_record_trace(db, task, run, "tool_guard", "failed", "阻止无效工具循环", code,
                                  {"action": action.__dict__, "reason": code},
                                  {"history_key": history_key, "reason": code})
                tool_result = execute_tool(db, task, run, tools, action, result.request_id, history_key, code)
            else:
                # 受控工具执行后记录调用、结果和文件产物。
                tool_result = execute_tool(db, task, run, tools, action, result.request_id, history_key)
            entry["result"] = tool_result.__dict__
            if context.get('require_unit_submission'):
                entry['unit_versions_after'] = file_hashes(workspace_for(task), context['owned_files'])
            history.append(entry)
            checkpoint_entries.append(entry)
            save_checkpoint(run, checkpoint_entries)
            if guard_code in {"unchanged_file_read_already_covered",
                              "covered_read_requires_write_test_or_replan"}:
                context = {**context, "unit_progress_feedback": {
                    "error": guard_code,
                    "instruction": ("已成功读取的未修改文件内容仍然有效。下一次响应不得继续 read；"
                                    "只能写入当前 owned_files、调用 run_unit_tests，或调用 request_slice_replan。"),
                }}
            if tool_result.status == "succeeded":
                run.last_completed_action_index = index
            db.commit()
            if (context.get("switch_on_progress_violation")
                    and guard_code == "covered_read_requires_write_test_or_replan"):
                # 首次违反已给出的推进约束即结束，剩余同批动作也不能继续旧流程。
                return "DEVELOPER_PROGRESS_SWITCH"
            if tool_result.status == "succeeded" and stop_when and stop_when():
                return 'SUBMITTED_FOR_TEST' if context.get('require_unit_submission') else result.text
        if single_batch:
            # 受限实现处理完整写入批次后交回 Runtime，由程序负责测试与有界修复。
            return result.text
    raise RuntimeError("model_loop_call_budget_exceeded" if max_calls is not None else "model_call_limit_exceeded")


def finish_step(db: Session, task: Task, run: StepRun, next_step: Step):
    # 结束当前阶段并推进任务到下一阶段。
    previous = task.cur_step.value
    safe_record_trace(db, task, run, "step", "succeeded", "阶段完成", previous,
                      {"output_path": run.output_path}, started_at=run.started_at,
                      finished_at=datetime.utcnow())
    safe_record_trace(db, task, run, "state_transition", "info", "进入下一阶段",
                      f"{previous} → {next_step.value}", {"from": previous, "to": next_step.value})
    # 阶段成功后同时更新执行记录、任务状态和版本。
    run.status = StepStatus.succeeded
    run.finished_at = datetime.utcnow()
    task.cur_step = next_step
    task.status = TaskStatus.running
    task.version += 1
    db.commit()


def fail_or_repair(db: Session, task: Task, run: StepRun, reason: str):
    # 按返修预算决定重新进入开发或终止任务。
    safe_record_trace(db, task, run, "validation", "failed", "验证失败", reason,
                      {"reason": reason, "repair_round": task.repair_round})
    run.status = StepStatus.failed
    run.error = reason
    run.finished_at = datetime.utcnow()
    # 验证失败只在返修预算内回到开发阶段。
    if task.repair_round < MAX_REPAIR_ROUNDS:
        task.repair_round += 1
        task.cur_step = Step.develop
        task.status = TaskStatus.running
        safe_record_trace(db, task, run, "state_transition", "info", "进入返修",
                          f"返回 develop，第 {task.repair_round} 轮返修",
                          {"from": run.step.value, "to": Step.develop.value,
                           "repair_round": task.repair_round})
        add_message(db, task, "system", f"验证失败，进入第 {task.repair_round} 轮返修：{reason}")
    else:
        task.status = TaskStatus.failed
        task.failure_reason = reason
        safe_record_trace(db, task, run, "state_transition", "failed", "任务失败",
                          reason, {"from": run.step.value, "to": TaskStatus.failed.value})
        evidence = workspace_for(task) / "evidence" / "failure-report.md"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(f"# 失败报告\n\n{reason}\n", encoding="utf-8")
    task.version += 1
    db.commit()


def product_code_hashes(task: Task) -> dict[str, str]:
    # 取得会影响测试和浏览器行为的当前产品代码哈希，用于防止复用旧验证结果。
    root = workspace_for(task)
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "product").rglob("*"))
            if path.is_file() and path.suffix in {".html", ".css", ".js", ".cjs", ".mjs", ".py"}}


def write_verification_evidence(task: Task, unit: ToolResult | None, browser: ToolResult) -> Path:
    # 同时保存人可读报告与被验证代码版本，返修时可判断失败证据是否已经过期。
    root = workspace_for(task)
    report = root / "evidence/verification-report.md"
    unit_section = ("## JavaScript 单元测试\n\n```json\n" +
                    json.dumps(unit.__dict__, ensure_ascii=False, indent=2) + "\n```\n\n") if unit else ""
    report.write_text("# 验证报告\n\n" + unit_section +
                      "## Playwright 浏览器验证\n\n```json\n" +
                      json.dumps(browser.__dict__, ensure_ascii=False, indent=2) + "\n```\n",
                      encoding="utf-8")
    write_json_atomic(root / "evidence/verification-evidence.json", {
        "report_path": "evidence/verification-report.md",
        "report_sha256": content_hash(report.read_text(encoding="utf-8")),
        "file_hashes": product_code_hashes(task),
        "browser_passed": (browser.status == "succeeded"
                           and browser.output.get("exit_code") == 0
                           and "[SKIP]" not in browser.output.get("stdout", "")),
    })
    return report


def verification_evidence_matches(task: Task) -> bool | None:
    # 旧任务没有版本证据时返回未知；有证据时严格比较当前产品代码哈希。
    path = workspace_for(task) / "evidence/verification-evidence.json"
    if not path.is_file():
        return None
    evidence = json.loads(path.read_text(encoding="utf-8"))
    hashes = evidence.get("file_hashes")
    return hashes == product_code_hashes(task) if isinstance(hashes, dict) else None


def skipped_design_evidence(task: Task) -> dict[str, dict]:
    # 取得缺省设计文档对应的最近跳过理由，供开发返修和验收规划使用。
    root = workspace_for(task)
    skipped = {}
    for path in sorted((root / "evidence").glob("initial-*-decision-v*.json")):
        decision = json.loads(path.read_text(encoding="utf-8"))
        for name in decision.get("skipped_documents", []):
            if not (root / "docs" / name).is_file():
                skipped[name] = {"reason": decision.get("reason"),
                                 "evidence": decision.get("evidence", []),
                                 "product_hash_when_decided": decision.get("document_hashes", {}).get("product"),
                                 "decision_path": str(path.relative_to(root))}
    return skipped


def active_bug_triage(task: Task) -> dict:
    # 识别最近一次已确认的现有产品变更，避免影响新建任务原流程。
    root = workspace_for(task)
    files = list((root / "evidence").glob("acceptance-triage-*.json"))
    if not files:
        return {}
    latest = max(files, key=lambda path: int(path.stem.rsplit("-", 1)[-1]))
    triage = json.loads(latest.read_text(encoding="utf-8"))
    return triage if triage.get("classification") in {
        "implementation_defect", "requirement_change", "architecture_defect", "dev_design_defect"
    } and triage.get("planner_action") in {
        "update_requirement", "update_architecture", "update_dev_design", "modify_code"
    } else {}


def bug_verified_ready(db: Session, task: Task) -> bool:
    # 检查同一份代码已经通过测试与浏览器验证，供 finish 门径使用。
    root = workspace_for(task)
    tested = root / "evidence" / "bug-tested-code-hashes.json"
    verified = root / "evidence" / "bug-verified-code-hashes.json"
    last_verify = db.scalar(select(StepRun).where(
        StepRun.task_id == task.id, StepRun.step == Step.verify_product,
        StepRun.status == StepStatus.succeeded).order_by(StepRun.id.desc()).limit(1))
    last_develop = db.scalar(select(StepRun).where(
        StepRun.task_id == task.id, StepRun.step == Step.develop,
        StepRun.status == StepStatus.succeeded).order_by(StepRun.id.desc()).limit(1))
    if not last_verify or not last_develop or last_verify.id < last_develop.id \
            or not tested.is_file() or not verified.is_file() or not task.result_url:
        return False
    current = product_code_hashes(task)
    return (json.loads(tested.read_text(encoding="utf-8")) == current
            and json.loads(verified.read_text(encoding="utf-8")) == current)


def plan_bug_action(db: Session, task: Task, run: StepRun, tools: ToolRuntime) -> str:
    # 根据已确认的现有产品变更和真实执行结果规划下一行动，程序负责校验和执行。
    triage = active_bug_triage(task)
    event_id = triage["event_id"]
    root = workspace_for(task)
    decisions = [trace for trace in db.scalars(select(TraceRecord).where(
        TraceRecord.task_id == task.id, TraceRecord.type == "bug_planner_decision")).all()
                 if trace.metadata_json.get("event_id") == event_id]
    if len(decisions) >= MAX_BUG_PLANNER_DECISIONS:
        raise RuntimeError("bug_planner_decision_limit_exceeded")
    inspections = [trace for trace in db.scalars(select(TraceRecord).where(
        TraceRecord.task_id == task.id, TraceRecord.type == "bug_planner_inspect")).all()
                   if trace.metadata_json.get("event_id") == event_id]
    candidates = [f"evidence/{name}" for name in ("test-report.md", "verification-report.md")
                  if (root / "evidence" / name).is_file()]
    candidates += sorted(str(path.relative_to(root)) for path in (root / "product").rglob("*")
                         if path.is_file())
    previous_hashes = {**triage.get("inspected_evidence", {}),
                       **{trace.metadata_json["path"]: trace.metadata_json["sha256"]
                          for trace in inspections if trace.status == "succeeded"}}
    remaining_files = [path for path in candidates if previous_hashes.get(path) !=
                       hashlib.sha256((root / path).read_bytes()).hexdigest()]
    if task.cur_step == Step.develop:
        allowed = ["modify_code"]
    elif task.cur_step == Step.test:
        # 新修改尚无正式测试结果时先运行原失败用例，避免基于旧报告反复改代码。
        allowed = ["run_test"]
    elif task.cur_step == Step.start_product:
        tested = root / "evidence" / "bug-tested-code-hashes.json"
        if not tested.is_file() or json.loads(tested.read_text(encoding="utf-8")) != product_code_hashes(task):
            raise RuntimeError("bug_test_evidence_stale")
        allowed = ["start_product"]
    elif task.cur_step == Step.verify_product:
        allowed = ["finish"] if bug_verified_ready(db, task) else ["verify_product"]
    else:
        raise RuntimeError("bug_planner_invalid_step")
    if remaining_files and len(inspections) < MAX_BUG_EXTRA_INSPECTIONS:
        allowed.append("inspect")
    allowed.append("clarify")
    last_run = db.scalar(select(StepRun).where(
        StepRun.task_id == task.id, StepRun.id < run.id).order_by(StepRun.id.desc()).limit(1))
    reports = {name: (root / "evidence" / name).read_text(encoding="utf-8")
               for name in ("test-report.md", "verification-report.md")
               if (root / "evidence" / name).is_file()}
    inspected_content = {}
    for trace in inspections[-MAX_BUG_EXTRA_INSPECTIONS:]:
        detail = root / trace.detail_path
        if detail.is_file() and trace.status == "succeeded":
            inspected_content[trace.metadata_json["path"]] = json.loads(
                detail.read_text(encoding="utf-8"))["payload"]["content"]
    context = {"approved_documents": {name: (root / "docs" / name).read_text(encoding="utf-8")
                                      for name in ("product.md", "architecture.md", "dev-design.md")
                                      if (root / "docs" / name).is_file()},
               "skipped_design": skipped_design_evidence(task),
               "acceptance_triage": triage, "last_action_result":
               {"step": last_run.step.value, "status": last_run.status.value,
                "error": last_run.error, "output_path": last_run.output_path} if last_run else None,
               "reports": reports, "code_hashes": product_code_hashes(task),
               "inspected_content": inspected_content, "allowed_actions": allowed,
               "remaining_files": remaining_files,
               "remaining_decisions": MAX_BUG_PLANNER_DECISIONS - len(decisions),
               "repair_round": task.repair_round}
    for attempt in range(2):
        # Planner 只提出行动和证据目标，不接触工具；非法决定最多纠正一次。
        response = model_tool_loop(
            db, task, run,
            """你是现有产品变更的 Next Action Planner。根据已确认变更、最近真实结果及调查证据，从 allowed_actions 中选择下一行动。不能跳过程序的测试、启动、浏览器和人工验收门径。只返回 JSON：action、path、reason、evidence_refs、clarifying_question；inspect 的 path 必须在 remaining_files 中；clarify 必须给出一个具体问题；其他行动的 path 为 null。""",
            triage["user_feedback"], context, tools, tool_schemas=[],
            history_key=f"bug_planner_{event_id}_{run.id}_{attempt}", runtime_step=Step.product_docs)
        try:
            value = json.loads(response.strip().removeprefix("```json").removeprefix("```")
                               .removesuffix("```").strip())
        except json.JSONDecodeError:
            value = {}
        if not isinstance(value, dict):
            value = {}
        action = value.get("action")
        path = value.get("path")
        valid = (action in allowed and isinstance(value.get("reason"), str)
                 and bool(value["reason"].strip())
                 and (action != "inspect" or path in remaining_files)
                 and (action != "clarify" or isinstance(value.get("clarifying_question"), str)
                      and bool(value["clarifying_question"].strip())))
        if valid:
            safe_record_trace(db, task, run, "bug_planner_decision", "succeeded", "Bug 下一行动",
                              action, {"decision": value, "context": context},
                              {"event_id": event_id, "action": action, "path": path})
            if action == "inspect":
                # 实际读取和内容哈希由程序产生，下一次规划将获得这份证据。
                result = tools.execute(ToolCall(str(uuid.uuid4()), "read", {"path": path}))
                if result.status != "succeeded" or result.output.get("truncated"):
                    raise RuntimeError("bug_inspection_read_failed")
                digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
                safe_record_trace(db, task, run, "bug_planner_inspect", "succeeded", "读取 Bug 证据",
                                  path, {"path": path, "content": result.output["content"], "sha256": digest},
                                  {"event_id": event_id, "path": path, "sha256": digest})
            elif action == "clarify":
                run.status = StepStatus.waiting_user
                task.status = TaskStatus.waiting_user
                add_message(db, task, "assistant", value["clarifying_question"])
            db.commit()
            return action
        context["protocol_error"] = {"attempt": attempt + 1, "response": response,
                                     "allowed_actions": allowed}
    raise RuntimeError("bug_planner_protocol_failed")


def product_feedback_is_decided(current_product: str, triage: dict) -> bool:
    # 已核实的明确验收变更覆盖旧产品条款，不再重复向用户确认。
    changes = triage.get("changes")
    consistency = triage.get("consistency_validation")
    return bool(current_product and triage.get("classification") == "requirement_change"
                and isinstance(triage.get("confidence"), (int, float))
                and triage["confidence"] >= 0.7
                and not triage.get("clarifying_question")
                and isinstance(consistency, dict) and consistency.get("consistent") is True
                and consistency.get("contradictions") == []
                and isinstance(triage.get("user_feedback"), str) and triage["user_feedback"].strip()
                and isinstance(changes, list) and changes
                and all(isinstance(item, dict)
                        and isinstance(item.get("current_behavior"), str) and item["current_behavior"].strip()
                        and isinstance(item.get("expected_behavior"), str) and item["expected_behavior"].strip()
                        and isinstance(item.get("acceptance_examples"), list) and item["acceptance_examples"]
                        and all(isinstance(example, str) and example.strip()
                                for example in item["acceptance_examples"])
                        for item in changes))


def handle_product_docs(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 生成、评审和提交产品文档候选供用户批准。
    version = run.attempt
    messages = list(db.scalars(select(Message).where(Message.task_id == task.id).order_by(Message.id)).all())
    # 用正式产品文档和成对问答构造本轮输入，避免用户回答失去指代。
    conversation_turns = sync_conversation_turns(task, run, messages)
    user_messages = [message.content for message in messages if message.role == "user"]
    initial = user_messages[0] if user_messages else ""
    current_product_path = workspace_for(task) / "docs" / "product.md"
    current_product = current_product_path.read_text(encoding="utf-8") if current_product_path.is_file() else ""
    primary_product_input = current_product or initial
    # 回答只通过完整问答对传递，初始需求已作为 input 时也不重复携带。
    paired_ids = {turn["answer"]["message_id"] for turn in conversation_turns if turn.get("answer")}
    unpaired_requests = [message.content for message in messages
                         if message.role == "user" and message.id not in paired_ids]
    if not current_product and unpaired_requests:
        unpaired_requests = unpaired_requests[1:]
    target = f"docs/product-v{version}-draft.md"
    review_target = f"docs/product-v{version}-review.md"
    candidate_target = f"docs/product-v{version}-candidate.md"
    triage_files = sorted((workspace_for(task) / "evidence").glob("acceptance-triage-*.json"))
    acceptance_triage = json.loads(triage_files[-1].read_text(encoding="utf-8")) if triage_files else {}
    if not (workspace_for(task) / target).is_file():
        context = {"conversation_history": [
                       {"question": turn.get("question"), "answer": turn.get("answer"),
                        "status": turn.get("status"), "turn_id": turn.get("turn_id")}
                       for turn in conversation_turns
                   ], "unpaired_user_requests": unpaired_requests,
                   "input_source": {"kind": "approved_product" if current_product else "initial_request",
                                    "sha256": content_hash(primary_product_input)},
                   "fixed_v1_boundaries": ["Windows 本地运行", "浏览器使用",
                                           "原生 HTML/CSS/JavaScript", "单用户",
                                           "不需要公网、域名或安装包"],
                   "acceptance_triage": acceptance_triage}
        # 让模型依据现有证据作出受限的产品阶段动作判断。
        decision = "READY" if product_feedback_is_decided(current_product, acceptance_triage) else model_tool_loop(db, task, run,
                        """你只负责产品门径判断，本次没有任何工具，绝对不能生成或写入 Draft。
判断完整问答历史中是否仍存在会改变核心功能范围、主要交互形态，或导致验收结果无法判定的未决产品问题。
如果存在，第一行必须是 BLOCKED，随后列出最多三个需要用户回答的问题。每个编号只能包含一个决策，不得用“另外”“以及”“是否还需要”等方式在一个编号中打包多个子问题。
主输入方式、用户如何触发核心动作、单次还是连续操作，属于主要交互，用户未明确时必须提问，绝对不能默认。例如计算器使用两个输入框还是按钮键盘、一次二元运算还是结果可连续参与运算，必须由用户决定。
只有不改变控件、状态转换和核心行为的细节，例如布局和视觉样式，才不算阻塞问题；可采用最简单默认值，并在后续 Draft 中明确标注为“默认假设”。提示文案仅在不影响验收判定时可以默认。
当核心功能、主要交互和可执行验收标准足够明确时，必须只返回一个单词 READY，不得为了补齐所有产品细节继续提问。
产品名称、品类惯例和你的常识都不代表用户已经授权具体功能。不得因为用户说“计算器”“待办清单”等产品名称，就自行假定运算类型、输入方式、按钮、清除、历史、数据保存、输出格式或异常行为。
本轮已验证的明确验收反馈优先于旧版产品文档；旧文档与反馈冲突，不代表反馈仍需用户确认。只有反馈存在两种实质不同的实现解释且用户未选择时，才必须提问。
只有核心范围、主要交互或验收判定存在多种实质不同方案且用户没有明确选择时，才必须提问。
不得询问或重新决定系统固定事项。""",
                        primary_product_input, context, tools, tool_schemas=[], history_key="product_gate")
        if decision.strip() != "READY":
            if not decision.strip():
                raise RuntimeError("product_clarification_question_missing")
            run.status = StepStatus.waiting_user
            task.status = TaskStatus.waiting_user
            refreshed = list(db.scalars(select(Message).where(
                Message.task_id == task.id).order_by(Message.id)).all())
            sync_conversation_turns(task, run, refreshed)
            safe_record_trace(db, task, run, "step", "waiting", "等待用户回答",
                              "产品需求仍有阻塞问题", {"question": decision})
            db.commit()
            return
        # 门径通过后才生成 Draft，文件不存在时恢复仍可接着执行。
        model_tool_loop(db, task, run,
                        f"""门径判断已确认无阻塞问题。根据用户明确需求、回答和系统固定边界生成产品文档，只写入 {target}，write 必须使用 overwrite=false。
文档必须说明要做什么、为什么、怎么算成功。不得包含“待确认”“尚未确定”、TBD 或任何留给后续决定的产品问题。
Draft 以用户明确需求、用户回答、验收分类结论和系统固定边界为准；若 acceptance_triage 标记 requirement_change，必须修改被用户反馈推翻的旧行为，不得原样保留冲突的旧约束。不得把模型推测写成“用户明确要求”。默认假设不得增加用户未确认的控件、输入方式、触发动作、连续操作、历史、持久化或其他状态行为。只有布局、视觉样式等不改变功能行为的必要细节可采用最简单默认值，且必须集中放在“默认假设”章节。""",
                        primary_product_input, context, tools,
                        stop_when=lambda: (workspace_for(task) / target).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key="product_draft")
    if not (workspace_for(task) / target).is_file():
        raise RuntimeError("product_draft_missing")
    draft_text = (workspace_for(task) / target).read_text(encoding="utf-8")
    previous_product = workspace_for(task) / "docs" / "product.md"
    previous_text = previous_product.read_text(encoding="utf-8") if previous_product.is_file() else ""
    if not (workspace_for(task) / review_target).is_file():
        # 独立 Reviewer 对照用户原文与旧正式需求评审 Draft。
        model_tool_loop(db, task, run,
                        f"""你是独立 Product Reviewer，不是 Draft 作者。对照全部用户消息、上一版正式需求和本轮 Draft 进行评审，只写入 {review_target}，write 必须使用 overwrite=false。
评审报告必须依次包含“阻塞问题”“普通问题”“建议”三个章节，没有内容的章节明确写“无”。阻塞问题包括遗漏或曲解用户明确要求、与用户要求或正式边界冲突、导致验收无法判定的问题。若 acceptance_triage 标记 requirement_change，必须检查 Draft 是否仍保留了被本轮反馈推翻的旧约束；保留即为阻塞问题。普通问题是不阻塞当前目标但应澄清或修正的问题。建议不得擅自扩大产品范围。""",
                        draft_text,
                        {"unpaired_user_requests": unpaired_requests if current_product else [initial] + unpaired_requests, "previous_product": previous_text,
                         "question_answer_turns": conversation_turns,
                         "acceptance_triage": acceptance_triage}, tools,
                        stop_when=lambda: (workspace_for(task) / review_target).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key="product_review")
    if not (workspace_for(task) / review_target).is_file():
        raise RuntimeError("product_review_missing")
    review_text = (workspace_for(task) / review_target).read_text(encoding="utf-8")
    if not (workspace_for(task) / candidate_target).is_file():
        # 作者根据独立评审生成供用户审批的 Candidate。
        model_tool_loop(db, task, run,
                        f"""你是 Product Author。根据 Draft、独立 Review、全部用户消息和上一版正式需求生成供用户审批的候选版，只写入 {candidate_target}，write 必须使用 overwrite=false。
必须解决 Review 中的阻塞问题；普通问题在不替用户做关键决定的前提下修正；建议只有不扩大范围且有明确依据时才采纳。不得把模型推测写成用户明确要求。""",
                        draft_text,
                        {"review": review_text, "unpaired_user_requests": unpaired_requests if current_product else [initial] + unpaired_requests,
                         "question_answer_turns": conversation_turns,
                         "previous_product": previous_text,
                         "acceptance_triage": acceptance_triage}, tools,
                        stop_when=lambda: (workspace_for(task) / candidate_target).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key="product_candidate")
    if not (workspace_for(task) / candidate_target).is_file():
        raise RuntimeError("product_candidate_missing")
    changes = acceptance_triage.get("changes", [])
    if changes:
        candidate_text = (workspace_for(task) / candidate_target).read_text(encoding="utf-8")
        # 独立检查候选产品文档是否逐条覆盖验收行为变更。
        coverage_text = model_tool_loop(
            db, task, run,
            """你是独立 Product Change Coverage Validator，只核对候选需求是否正确吸收变更契约，不写文件。
逐条比较 current_behavior、expected_behavior、acceptance_examples 与候选文档。若候选仍保留被推翻的旧行为、把现状当期望、遗漏期望行为或没有可执行验收标准，则 covered=false。
只返回 JSON：items 数组，每项包含 index（从 1 开始）、covered、reason；all_covered 仅在所有条目 covered=true 时为 true。不要返回 Markdown。""",
            candidate_text, {"changes": changes, "previous_product": previous_text,
                             "unpaired_user_requests": unpaired_requests if current_product else [initial] + unpaired_requests,
                             "question_answer_turns": conversation_turns}, tools, tool_schemas=[],
            history_key="product_change_coverage")
        try:
            coverage = json.loads(coverage_text.strip().removeprefix("```json").removeprefix("```")
                                  .removesuffix("```").strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError("product_change_coverage_invalid") from exc
        if not isinstance(coverage, dict):
            coverage = {"items": [], "all_covered": False, "raw_type": type(coverage).__name__}
        items = coverage.get("items") if isinstance(coverage, dict) else None
        # 程序逐条验证覆盖结果的数量、索引和类型，不能只信模型结论。
        valid_items = (isinstance(items, list) and len(items) == len(changes)
                       and all(isinstance(item, dict)
                               and item.get("index") == index
                               and isinstance(item.get("covered"), bool)
                               and isinstance(item.get("reason"), str)
                               for index, item in enumerate(items, 1)))
        coverage["validated"] = bool(valid_items and coverage.get("all_covered") is True
                                     and all(item["covered"] for item in items))
        coverage_path = workspace_for(task) / "evidence" / f"product-v{version}-change-coverage.json"
        # 永久保存候选覆盖判断，供用户审批前核对。
        write_json_atomic(coverage_path, coverage)
        safe_record_trace(db, task, run, "validation",
                          "succeeded" if coverage["validated"] else "failed",
                          "产品变更覆盖校验",
                          "全部覆盖" if coverage["validated"] else "存在未覆盖变更",
                          {"changes": changes, "candidate": candidate_text,
                           "model_response": coverage_text},
                          {"validated": coverage["validated"],
                           "coverage_path": str(coverage_path.relative_to(workspace_for(task)))})
        if not coverage["validated"]:
            raise RuntimeError("product_change_coverage_failed")
    run.output_path = candidate_target
    run.status = StepStatus.waiting_user
    task.status = TaskStatus.waiting_user
    safe_record_trace(db, task, run, "step", "waiting", "等待产品文档审批",
                      f"产品文档 v{version} 已完成独立评审并生成候选版",
                      {"draft_path": target, "review_path": review_target,
                       "output_path": candidate_target})
    add_message(db, task, "assistant", f"产品文档 v{version} 候选已生成，请批准或提供修改意见。")
    db.commit()


def plan_initial_design_action(db: Session, task: Task, run: StepRun, tools: ToolRuntime) -> str:
    # 用已批准需求和项目固定约束判断缺失的设计文档是否确有必要。
    root = workspace_for(task)
    product_path = root / "docs/product.md"
    if not product_path.is_file():
        raise RuntimeError("approved_product_missing_for_design_plan")
    product = product_path.read_text(encoding="utf-8")
    architecture_path = root / "docs/architecture.md"
    architecture = architecture_path.read_text(encoding="utf-8") if architecture_path.is_file() else ""
    phase = "architecture" if task.cur_step == Step.architecture_docs else "dev_design"
    triage = active_bug_triage(task)
    allowed = (["update_architecture", "update_dev_design", "modify_code", "clarify"]
               if phase == "architecture" else ["update_dev_design", "modify_code", "clarify"])
    if (phase == "architecture" and triage.get("classification") == "architecture_defect") or (
            phase == "dev_design" and triage.get("classification") == "dev_design_defect"):
        # 已确认该设计阶段缺陷时不得再次以简单任务为由跳过。
        allowed = [allowed[0], "clarify"]
    decision_path = root / "evidence" / f"initial-{phase}-decision-v{run.attempt}.json"
    design_answers = design_clarifications(db, task)
    current_hashes = {"product": content_hash(product), "architecture": content_hash(architecture),
                      "design_answers": content_hash(json.dumps(design_answers, ensure_ascii=False))}
    decision = None
    if decision_path.is_file():
        # 运行中恢复只复用与当前正式输入完全一致的已校验决定。
        saved = json.loads(decision_path.read_text(encoding="utf-8"))
        if saved.get("document_hashes") == current_hashes and saved.get("action") in allowed:
            decision = saved
    if decision is None:
        context = {"phase": phase, "input_source": {"path": "docs/product.md", "sha256": content_hash(product)}, "existing_architecture": architecture,
                   "project_constraints": FIXED_PRODUCT_CONSTRAINTS,
                   "confirmed_design_answers": design_answers, "allowed_actions": allowed}
        for attempt in range(2):
            # Planner 只返回建议，不写文件；非法输出最多纠正一次。
            response = model_tool_loop(
                db, task, run,
                """你是新任务设计门径的 Next Action Planner。docs/product.md 已由程序在用户批准后正式化，正文即使残留「候选版」标题也不改变审批状态。Worker 的本地 HTTP 服务仅用于软件预览和健康检查，与生成产品不发起外部网络请求不冲突；这不是用户待决的产品设计。只依据已经批准的产品需求、现有正式设计和固定项目约束判断编码前还有没有必须写进独立设计文档的决定。不能按需求字数或软件名称判断。若模块职责、接口、数据、状态、关键流程或失败处理在正式需求和固定约束中已明确且无需额外取舍，可跳过不必要的设计文档；若某份设计承载必要取舍，则选对应更新行动。用户未确认的关键业务规则不能由你猜测，证据不足只提出一个澄清问题。只返回 JSON：action、reason、evidence（引用正式需求的具体句子，字符串数组）、unresolved_decisions（未解决的关键决定数组）、confidence（0 到 1）、clarifying_question。action 必须在 allowed_actions 中。跳过设计时 evidence 必须非空，unresolved_decisions 必须为空。不得调用工具或改文件。""",
                product, {**context, "protocol_error": context.get("protocol_error")}, tools,
                tool_schemas=[], history_key=f"initial_{phase}_plan_{run.attempt}_{attempt}")
            try:
                value = json.loads(response.strip().removeprefix("```json").removeprefix("```")
                                   .removesuffix("```").strip())
            except json.JSONDecodeError:
                value = {}
            if not isinstance(value, dict):
                value = {}
            action = value.get("action")
            confidence = value.get("confidence")
            evidence = value.get("evidence")
            unresolved = value.get("unresolved_decisions")
            skip = (action in {"update_dev_design", "modify_code"} if phase == "architecture"
                    else action == "modify_code")
            valid = (action in allowed and isinstance(value.get("reason"), str)
                     and bool(value["reason"].strip())
                     and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                     and 0 <= confidence <= 1 and (action == "clarify" or confidence >= 0.7)
                     and isinstance(evidence, list) and
                     all(isinstance(item, str) and item.strip() for item in evidence)
                     and isinstance(unresolved, list) and
                     all(isinstance(item, str) and item.strip() for item in unresolved)
                     and (not skip or evidence and not unresolved)
                     and (action != "clarify" or isinstance(value.get("clarifying_question"), str)
                          and bool(value["clarifying_question"].strip())))
            if valid:
                skipped = (["architecture.md", "dev-design.md"] if phase == "architecture"
                           and action == "modify_code" else ["architecture.md"] if phase == "architecture"
                           and action == "update_dev_design" else ["dev-design.md"] if phase == "dev_design"
                           and action == "modify_code" else [])
                decision = {**value, "phase": phase, "document_hashes": current_hashes,
                            "skipped_documents": skipped, "approved_product_path": "docs/product.md"}
                write_json_atomic(decision_path, decision)
                safe_record_trace(db, task, run, "initial_design_plan",
                                  "waiting" if action == "clarify" else "succeeded",
                                  "新任务设计门径", action,
                                  {"input": context, "decision": decision},
                                  {"action": action, "skipped_documents": skipped,
                                   "decision_path": str(decision_path.relative_to(root)),
                                   "confidence": confidence})
                break
            context["protocol_error"] = {"response": response, "attempt": attempt + 1,
                                         "allowed_actions": allowed}
        if decision is None:
            # 非法决定无法证明可跳过设计，安全地转为人工澄清。
            decision = {"action": "clarify", "reason": "设计门径行动或证据无效",
                        "evidence": [], "unresolved_decisions": ["编码前必要设计仍待判断"],
                        "confidence": 0, "clarifying_question":
                        "请确认这项软件是否存在需要在编码前确定的模块、接口、状态或失败处理规则。",
                        "phase": phase, "document_hashes": current_hashes,
                        "skipped_documents": [], "approved_product_path": "docs/product.md"}
            write_json_atomic(decision_path, decision)
            safe_record_trace(db, task, run, "initial_design_plan", "waiting",
                              "新任务设计门径", "clarify",
                              {"input": context, "decision": decision},
                              {"action": "clarify", "skipped_documents": [],
                               "decision_path": str(decision_path.relative_to(root)),
                               "confidence": 0})
    action = decision["action"]
    if action == "clarify":
        run.status = StepStatus.waiting_user
        task.status = TaskStatus.waiting_user
        add_message(db, task, "assistant", decision["clarifying_question"])
        db.commit()
    elif action == "update_dev_design" and phase == "architecture":
        # 缺失架构只保存跳过依据，进入必要的 Dev Design 生成。
        run.input_path = "docs/product.md"
        run.output_path = str(decision_path.relative_to(root))
        finish_step(db, task, run, Step.dev_design)
    elif action == "modify_code":
        # 设计已由正式需求和固定约束覆盖，直接进入开发但保留规划证据。
        run.input_path = "docs/product.md"
        run.output_path = str(decision_path.relative_to(root))
        finish_step(db, task, run, Step.develop)
    return action


def design_clarifications(db: Session, task: Task) -> list[str]:
    # 只传产品批准后的增量回答；更早需求和问答已经固化在正式产品文档中。
    approval = db.scalar(select(Message).where(
        Message.task_id == task.id, Message.role == "user", Message.content == "批准产品文档"
    ).order_by(Message.id.desc()))
    if approval is None:
        return []
    return list(db.scalars(select(Message.content).where(
        Message.task_id == task.id, Message.role == "user", Message.id > approval.id
    ).order_by(Message.id)).all())


def handle_reviewed_doc(db: Session, task: Task, run: StepRun, tools: ToolRuntime, kind: str):
    # 处理架构或 Dev Design 的规划、评审和正式化。
    root = workspace_for(task)
    if kind == "dev_design" and (root / "docs/delivery-plan.json").is_file():
        # 新任务只规划第一张业务切片，后续依据真实实现和测试逐片规划。
        from .slice_workflow import handle_design as handle_slice_design
        handle_slice_design(db, task, run, tools)
        return
    if kind == "dev_design" and (root / "docs/development-plan.json").is_file():
        # 有正式模块计划时分别评审共享契约与每个单元，不再生成巨大的单份设计。
        from .unit_workflow import handle_design
        handle_design(db, task, run, tools)
        return
    source = ("docs/product.md" if kind == "architecture" or
              not (root / "docs/architecture.md").is_file() else "docs/architecture.md")
    target = "docs/architecture.md" if kind == "architecture" else "docs/dev-design.md"
    revision = run.attempt > 1 and (root / target).is_file()
    version_suffix = f"-v{run.attempt}" if revision else ""
    draft = target.replace(".md", f"{version_suffix}-draft.md")
    review = target.replace(".md", f"{version_suffix}-review.md")
    formal_version = target.replace(".md", f"-v{run.attempt}.md")
    previous_formal_version = target.replace(".md", f"-v{run.attempt - 1}.md")
    source_text = (root / source).read_text(encoding="utf-8")
    confirmed_answers = design_clarifications(db, task)
    answer_context = {"confirmed_design_answers": confirmed_answers}
    answer_instruction = ("审批后的 confirmed_design_answers 是用户最新明确决定，优先于上游文档残留的待确认旧表述；"
                          "必须吸收这些决定，不得继续写成待确认。" if confirmed_answers else "")
    label = "架构设计" if kind == "architecture" else "Dev Design"
    extra = ("明确接口、数据、状态、流程和失败处理。" if kind == "dev_design" else
             "按职责划分模块，定义依赖、数据所有权、公共接口与跨模块流程；较大模块按可独立测试的功能拆分。采用最少且完整可验收的单元，测试、文档和验证脚本归属相应功能，不单独拆成业务模块或功能。测试固定 Node 内置框架，真实浏览器固定 Python Playwright 且只连接系统提供 URL；不得新增 npm Playwright 或自行启动验证服务。保持精简，函数内部详细设计留给逐单元 Dev Design。")
    if not revision and (root / target).is_file():
        # 首版正式文件已经存在时补存版本快照并跳过重复生成。
        if not (root / formal_version).is_file():
            atomic_copy(root / target, root / formal_version)
        run.input_path = source
        run.output_path = target
        if kind == "architecture":
            from .slice_workflow import prepare_architecture_delivery
            prepare_architecture_delivery(db, task, run, tools)
        finish_step(db, task, run, NEXT_STEP[task.cur_step])
        return

    transition = {"action": "execute", "reason": "首次生成", "affected_sections": [],
                  "preserved_sections": [], "confidence": 1.0, "clarifying_question": None}
    previous_text = ""
    upstream_diff = ""
    if revision:
        # 返工时固定旧正式版本和上游差异，作为 Planner 的比较基线。
        current_formal = root / target
        previous_version = root / previous_formal_version
        if not previous_version.is_file():
            if not current_formal.is_file():
                raise RuntimeError(f"{kind}_previous_formal_missing")
            atomic_copy(current_formal, previous_version)
        previous_text = previous_version.read_text(encoding="utf-8")
        if kind == "architecture":
            previous_upstream = root / "docs" / f"product-v{run.attempt - 1}.md"
            if not previous_upstream.is_file():
                previous_upstream = root / "docs" / f"product-v{run.attempt - 1}-candidate.md"
        else:
            previous_upstream = root / "docs" / f"architecture-v{run.attempt - 1}.md"
        previous_upstream_text = previous_upstream.read_text(encoding="utf-8") if previous_upstream.is_file() else ""
        triage_files = sorted((root / "evidence").glob("acceptance-triage-*.json"))
        acceptance_triage = json.loads(triage_files[-1].read_text(encoding="utf-8")) if triage_files else {}
        upstream_diff = unified_text_diff(previous_upstream_text, source_text,
                                          previous_upstream.name if previous_upstream_text else "previous-missing",
                                          Path(source).name)
        diff_path = root / "evidence" / f"{kind}-upstream-diff-v{run.attempt}.md"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(upstream_diff or "无文本差异。\n", encoding="utf-8")
        # 设计阶段 Planner 从具体下一行动中选择修订、复用或澄清。
        required_update = ((kind == "architecture" and acceptance_triage.get("classification") == "architecture_defect")
                           or (kind == "dev_design" and acceptance_triage.get("classification") == "dev_design_defect"))
        revise_action = "update_architecture" if kind == "architecture" else "update_dev_design"
        reuse_action = "update_dev_design" if kind == "architecture" else "modify_code"
        allowed_actions = [revise_action, "clarify"] if required_update else [revise_action, reuse_action, "clarify"]
        decision_text = model_tool_loop(
            db, task, run,
            f"""你是已有产品设计阶段的 Next Action Planner，根据上游正式文档差异决定下一行动，不写文件。
只返回 JSON：action 必须属于 allowed_actions；reason；affected_sections；preserved_sections；confidence（0 到 1）；clarifying_question。
选择 {revise_action} 表示现有{label}受影响，应以旧正式版本为基线局部修订。选择 {reuse_action} 表示有证据确认全部上游变化不影响现有{label}，程序保存复用血缘后进入下游；证据不足选择 clarify。""",
            upstream_diff,
            {"previous_upstream": previous_upstream_text, "current_upstream": source_text,
             "input_source": "upstream_diff", "previous_artifact": previous_text,
             "acceptance_triage": acceptance_triage, "allowed_actions": allowed_actions},
            tools, tool_schemas=[], history_key=f"{kind}_transition")
        # 程序校验 Planner 的动作和置信度，低置信度转为澄清。
        transition = parse_transition_decision(decision_text, kind, required_update)
        transition.update({"kind": kind, "version": run.attempt,
                           "previous_upstream_path": str(previous_upstream.relative_to(root)),
                           "current_upstream_path": source,
                           "previous_artifact_path": previous_formal_version})
        transition_path = root / "evidence" / f"{kind}-transition-v{run.attempt}.json"
        # 保存规划决定及证据，供历史版本回溯。
        write_json_atomic(transition_path, transition)
        safe_record_trace(db, task, run, "transition_decision",
                          "waiting" if transition["action"] == "clarify" else "succeeded",
                          f"{label}影响判断", transition["action"],
                          {"previous_upstream": previous_upstream_text,
                           "current_upstream": source_text, "upstream_diff": upstream_diff,
                           "previous_artifact": previous_text, "decision": transition},
                          {"action": transition["action"], "next_action": transition["next_action"],
                           "confidence": transition["confidence"],
                           "decision_path": str(transition_path.relative_to(root))})
        if transition["action"] == "clarify":
            run.status = StepStatus.waiting_user
            task.status = TaskStatus.waiting_user
            add_message(db, task, "assistant", transition["clarifying_question"])
            db.commit()
            return
        if transition["action"] == "reuse":
            # 复用只在 Planner 确认上游变化不影响本阶段时执行。
            atomic_copy(previous_version, root / formal_version)
            atomic_copy(previous_version, root / target)
            run.input_path = source
            run.output_path = formal_version
            if kind == "architecture":
                from .slice_workflow import prepare_architecture_delivery
                prepare_architecture_delivery(db, task, run, tools)
            finish_step(db, task, run, NEXT_STEP[task.cur_step])
            return

    if not (root / draft).is_file():
        # 修订以旧正式文档为基线；首次生成直接使用当前正式上游。
        if revision:
            instructions = (f"以旧{label}为唯一基线，根据上游差异和影响判断进行局部修订，只写入 {draft}，"
                            f"write 必须使用 overwrite=false。不得重写 preserved_sections，不得引入无上游依据的变化。"
                            f"{extra}{answer_instruction}")
            input_text = previous_text
            context = {"current_upstream": source_text, "upstream_diff": upstream_diff,
                       "transition_decision": transition, **answer_context}
        else:
            instructions = (f"根据正式上游文档生成{label}候选，只写入 {draft}；该文件不存在，必须使用 overwrite=false。"
                            f"{extra}{answer_instruction}")
            input_text = source_text
            context = answer_context
        model_tool_loop(db, task, run,
                        instructions, input_text, context, tools,
                        stop_when=lambda: (root / draft).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key=f"{kind}_draft")
    if not (root / draft).is_file():
        raise RuntimeError(f"{kind}_draft_missing")
    draft_text = (root / draft).read_text(encoding="utf-8")
    if not (root / review).is_file():
        # 独立评审保留章节和旧约束，避免增量修订引入无依据设计。
        model_tool_loop(db, task, run,
                        f"你是独立 reviewer。评审候选，区分阻塞问题、普通问题和建议，只写入 {review}；"
                        "检查差异是否完整覆盖、preserved_sections 是否被意外修改、旧约束是否丢失以及是否引入无依据设计；write 必须使用 overwrite=false。",
                        draft_text, {"upstream": source_text, "previous_artifact": previous_text,
                                     "upstream_diff": upstream_diff, "transition_decision": transition,
                                     **answer_context}, tools,
                        stop_when=lambda: (root / review).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key=f"{kind}_review")
    if not (root / review).is_file():
        raise RuntimeError(f"{kind}_review_missing")
    review_text = (root / review).read_text(encoding="utf-8")
    if not (root / formal_version).is_file():
        # 把评审意见并入正式版本，再同步当前有效文档。
        model_tool_loop(db, task, run,
                        f"根据候选与独立评审生成正式{label}，只写入 {formal_version}，不得改变上游需求；"
                        f"write 必须使用 overwrite=false。{answer_instruction}",
                        draft_text, {"review": review_text, "upstream": source_text,
                                     "previous_artifact": previous_text,
                                     "transition_decision": transition, **answer_context}, tools,
                        stop_when=lambda: (root / formal_version).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key=f"{kind}_formal")
    if not (root / formal_version).is_file():
        raise RuntimeError(f"{kind}_formal_missing")
    atomic_copy(root / formal_version, root / target)
    run.input_path = source
    run.output_path = formal_version
    if kind == "architecture":
        from .slice_workflow import prepare_architecture_delivery
        prepare_architecture_delivery(db, task, run, tools)
    finish_step(db, task, run, NEXT_STEP[task.cur_step])


def product_files(root: Path) -> list[Path]:
    # 收集当前产品目录的全部实际文件，供完整快照和变更判断使用。
    directory = (root / "product").resolve()
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    for path in files:
        # 不把产品目录之外的符号链接目标当作产品文件读取。
        if directory not in path.resolve().parents:
            raise RuntimeError("product_file_outside_directory")
    return files


def is_product_test(path: Path) -> bool:
    # 按产品约定识别 Node 自动发现的测试文件，不绑定产品名称。
    return path.name.endswith((".test.js", ".test.cjs", ".test.mjs"))


class ProductEntryParser(HTMLParser):
    def __init__(self):
        # 收集 HTML 中需要加载的脚本和样式引用。
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        # 只检查实际加载的 script src 与 stylesheet href，不把普通链接当入口。
        attributes = dict(attrs)
        reference = attributes.get("src") if tag == "script" else None
        if tag == "link" and "stylesheet" in (attributes.get("rel") or "").lower().split():
            reference = attributes.get("href")
        if reference is not None:
            self.references.append(reference)


def missing_product_files(root: Path) -> list[str]:
    # 校验固定入口、自动发现测试及 HTML 的本地引用，返回真实缺失路径。
    directory = (root / "product").resolve()
    required = ["index.html", "verify_product.py", "implementation.md"]
    files = product_files(root)
    missing = [name for name in required if not (directory / name).is_file()]
    # 排除 Node 自动发现会跳过的 node_modules 目录。
    if not any(is_product_test(path) and "node_modules" not in path.relative_to(directory).parts for path in files):
        missing.append("*.test.js|*.test.cjs|*.test.mjs")
    entry = directory / "index.html"
    if entry.is_file():
        parser = ProductEntryParser()
        parser.feed(entry.read_text(encoding="utf-8"))
        for reference in parser.references:
            url = urlsplit(reference)
            if url.scheme or url.netloc:
                continue
            # 站点绝对路径也相对于产品目录，查询参数与片段不属于文件名。
            relative = unquote(url.path).lstrip("/")
            target = (directory / relative).resolve()
            if directory not in target.parents:
                raise RuntimeError("product_entry_outside_directory")
            if not target.is_file():
                missing.append(relative)
    return list(dict.fromkeys(missing))


def check_product_entry(db: Session, task: Task, run: StepRun) -> bool:
    # 在验证前重新检查产品入口，避免零测试或缺失资源被视为验证通过。
    missing = missing_product_files(workspace_for(task))
    if not missing:
        return True
    reason = f"implementation_files_missing:{','.join(missing)}"
    report_name = "test-report.md" if run.step == Step.test else "verification-report.md"
    report = workspace_for(task) / "evidence" / report_name
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(f"# 入口校验失败\n\n{reason}\n", encoding="utf-8")
    run.output_path = f"evidence/{report_name}"
    # 保存失败证据并进入现有返修规则，不让 Node 空发现掩盖缺失测试。
    fail_or_repair(db, task, run, reason)
    return False


def handle_develop(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 根据当前设计开发或返修生成软件并核对实现血缘。
    root = workspace_for(task)
    if (root / "docs/delivery-plan.json").is_file():
        # 首次开发逐片闭环；集成失败则按文件所有权回到对应切片定向返修。
        from .slice_workflow import handle_develop as handle_slice_develop, handle_repair as handle_slice_repair
        (handle_slice_repair if task.repair_round > 0 else handle_slice_develop)(db, task, run, tools)
        return
    if (root / "docs/development-plan.json").is_file():
        # 新计划串行执行模块／功能测试闭环，旧任务保留原开发入口。
        from .unit_workflow import handle_develop as handle_unit_develop
        handle_unit_develop(db, task, run, tools)
        return
    product = (root / "docs" / "product.md").read_text(encoding="utf-8")
    architecture_path = root / "docs/architecture.md"
    architecture = architecture_path.read_text(encoding="utf-8") if architecture_path.is_file() else ""
    design_path = root / "docs/dev-design.md"
    if not design_path.is_file() and "dev-design.md" not in skipped_design_evidence(task):
        raise RuntimeError("dev_design_missing_without_planner_skip")
    design_source = "docs/dev-design.md" if design_path.is_file() else "approved_product_and_constraints"
    # Dev Design 被明确跳过时，以已批准需求及固定实现约束构造开发依据。
    dev_design = (design_path.read_text(encoding="utf-8") if design_path.is_file() else
                  "正式产品需求见 input；现有架构见 existing_architecture。"
                  f"\n\n项目固定实现约束：\n" + "\n".join(FIXED_PRODUCT_CONSTRAINTS))
    existing = [str(path.relative_to(root)) for path in product_files(root)]
    is_repair = task.repair_round > 0
    lineage_path = root / "evidence" / "implementation-lineage.json"
    lineage = json.loads(lineage_path.read_text(encoding="utf-8")) if lineage_path.is_file() else {}
    dev_design_hash = content_hash(dev_design)
    upstream_changed = (not missing_product_files(root)
                        and lineage.get("dev_design_hash") != dev_design_hash)
    # 文件齐全也要核对设计血缘；上游设计变化时仍必须增量修改。
    triage = active_bug_triage(task)
    feature_change = triage.get("classification") == "requirement_change"
    non_bug_change = triage.get("classification") in {
        "requirement_change", "architecture_defect", "dev_design_defect"
    }
    is_revision = is_repair or upstream_changed or non_bug_change
    if not is_revision and not missing_product_files(root) and lineage.get("dev_design_hash") == dev_design_hash:
        run.output_path = "product/implementation.md"
        finish_step(db, task, run, Step.test)
        return
    instructions = """实现原生 HTML、CSS、JavaScript 软件，服从正式设计的模块边界。先在 text 中给出简短计划，再用 write 创建或覆盖文件。
write/read 的路径相对任务工作区，不是 product 工作目录。固定入口为 product/index.html、product/verify_product.py、product/implementation.md；JS、CSS 和其他文件路径按正式设计生成，HTML 本地引用必须指向实际产品文件。不要求根目录 app.js 或 styles.css。
不存在的文件必须使用 overwrite=false；只有 existing_product_files 明确列出的已有文件才使用 overwrite=true。不要把文件写到工作区根目录。
优先完成设计规定的全部实现文件、三个固定入口及测试文件，再使用 exec 调试；不要在文件未齐时反复运行测试或临时诊断命令。正式测试和失败返修由后续 test Step 负责。
Node 内置测试文件命名为 *.test.js、*.test.cjs 或 *.test.mjs，可放在子目录；verify_product.py 使用 Python Playwright 验证已批准需求中的核心行为、异常输入和错误后恢复。
verify_product.py 必须读取命令行第一个参数作为访问地址，直接连接系统已启动的产品服务；不得自行启动 HTTP 服务或绑定固定端口。
可使用 exec 执行 node --test 自动发现测试。不得引入生成产品依赖。全部设计文件完成后立即结束，不得仅因入口文件存在就宣称完成。"""
    if not design_path.is_file():
        instructions += "\n此任务经 Planner 确认无需独立 Dev Design；按 context 的正式产品需求和固定约束实施，不补写虚假的设计文档，也不擅自增加产品行为。"
    if is_repair:
        instructions += """
这是失败后的返修，不是首次生成。正式实现依据、失败来源、对应的完整失败报告和当前产品文件已放在 context 或最近工具交互中；优先使用已有内容，需要原始历史证据时用查询工具，需要最新文件时可用 read。逐项判断失败来自实现、测试还是两者。测试期望与已批准需求冲突时修测试，实现偏离时修实现。
必须优先解决 failure_source_step 指向的失败：若为 verify_product，重点检查 Playwright 输出、verify_product.py 是否使用系统传入的 HTTP URL，以及浏览器脚本是否真实加载；不得只运行 Node 测试后宣称完成。
至少使用 overwrite=true 实际修改一个 existing_product_files 中的文件。可以用 exec 运行 Node 测试，但不要查找、安装或尝试切换 Python／Playwright 环境；系统会在你结束本轮后使用受控 Python 自动复跑原失败验证。完成必要写入和 Node 测试后立即结束，不得因为入口文件已经存在就宣称完成。"""
    elif upstream_changed or non_bug_change:
        instructions += """
这是已验收产品的增量开发。必须比较变更后的正式产品需求、previous_product 与当前代码；若 Dev Design 变化，再比较 previous_dev_design 与当前 dev_design。以现有代码为基线，只修改受差异影响的代码和测试，不得推倒重写无关部分。
至少使用 overwrite=true 修改一个 existing_product_files 中的文件，并用 exec 运行更新后的相关测试。不得因为入口文件已经存在就宣称完成。"""
        safe_record_trace(db, task, run, "transition_decision", "succeeded", "开发影响判断",
                          "revise", {"previous_lineage": lineage,
                                     "current_dev_design_hash": dev_design_hash},
                          {"action": "revise", "reason": "implementation_lineage_mismatch"})
    # 等模型完成所有设计文件后再校验，避免入口齐全时截断模块生成。
    stop_when = None
    current_product_files = {
        str(path.relative_to(root)): path.read_text(encoding="utf-8", errors="replace")
        for path in product_files(root)
    } if is_revision and not is_repair else {}
    versioned_designs = sorted((root / "docs").glob("dev-design-v*.md"))
    previous_dev_design = versioned_designs[-2].read_text(encoding="utf-8") if len(versioned_designs) >= 2 else ""
    versioned_products = sorted((root / "docs").glob("product-v*.md"))
    previous_product = versioned_products[-2].read_text(encoding="utf-8") if len(versioned_products) >= 2 else ""
    dev_design_diff = unified_text_diff(previous_dev_design, dev_design,
                                        versioned_designs[-2].name if len(versioned_designs) >= 2 else "previous-missing",
                                        "dev-design.md") if previous_dev_design else ""
    triage_files = sorted((root / "evidence").glob("acceptance-triage-*.json"))
    acceptance_triage = json.loads(triage_files[-1].read_text(encoding="utf-8")) if triage_files else {}
    repair_tools = [schema for schema in TOOL_SCHEMAS
                    if schema["function"]["name"] in {"write", "exec", "read"}] if is_revision else None
    previous_failed = db.scalar(select(StepRun).where(
        StepRun.task_id == task.id, StepRun.id < run.id, StepRun.status == StepStatus.failed
    ).order_by(StepRun.id.desc()).limit(1)) if is_repair else None
    failure_source = previous_failed.step.value if previous_failed else "unknown"
    report_name = "verification-report.md" if previous_failed and previous_failed.step == Step.verify_product else "test-report.md"
    report_path = root / "evidence" / report_name
    latest_failure_report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    if previous_failed and previous_failed.step == Step.start_product:
        latest_failure_report = previous_failed.error or latest_failure_report
    if (failure_source == Step.verify_product.value and task.result_url
            and verification_evidence_matches(task) is False):
        # 失败报告对应的代码已经变化时，先用当前版本复跑原验证，禁止继续把旧错误喂给模型。
        command = f"{shlex.quote(sys.executable)} verify_product.py {shlex.quote(task.result_url)}"
        refreshed = execute_tool(db, task, run, tools, ToolCall(
            str(uuid.uuid4()), "exec", {"action": "run", "command": command}),
            history_key=f"stale-verification-refresh:{run.id}")
        report_path = write_verification_evidence(task, None, refreshed)
        if (refreshed.status == "succeeded" and refreshed.output.get("exit_code") == 0
                and "[SKIP]" not in refreshed.output.get("stdout", "")):
            run.output_path = "product/implementation.md"
            finish_step(db, task, run, Step.test)
            return
        latest_failure_report = report_path.read_text(encoding="utf-8")
    base_context = {"failure_source_step": failure_source,
                    "latest_failure_report": latest_failure_report,
                    "dev_design": dev_design, "design_source": design_source,
                    "input_source": {"path": "docs/product.md", "sha256": content_hash(product)},
                    "document_sources": {
                        "dev_design": {"source": design_source, "sha256": dev_design_hash},
                        "existing_architecture": {"path": "docs/architecture.md", "sha256": content_hash(architecture)},
                        "previous_product": {"sha256": content_hash(previous_product)} if previous_product else None,
                        "previous_dev_design": {"sha256": content_hash(previous_dev_design)} if previous_dev_design else None},
                    "existing_architecture": architecture,
                    "existing_product_files": existing,
                    "acceptance_triage": acceptance_triage,
                    "previous_product": previous_product,
                    "previous_dev_design": previous_dev_design,
                    "dev_design_diff": dev_design_diff,
                    "previous_dev_design_hash": lineage.get("dev_design_hash"),
                    "repair_round": task.repair_round,
                    "provide_file_contents": not is_repair,
                    "allow_history_detail": not is_repair}
    if current_product_files:
        # 首次开发和非返修修订保留源码快照；返修只传文件清单与哈希。
        base_context["current_product_files"] = current_product_files
    repair_feedback = None
    # 旧报告无法证明生成时的代码版本，不把当前哈希伪装成历史验证快照。
    failure_evidence_source = {"step_run_id": previous_failed.id if previous_failed else None,
                               "source": "step_error" if failure_source == Step.start_product.value else str(report_path.relative_to(root)),
                               "file_snapshot": "unknown", "sha256": content_hash(latest_failure_report)}
    # 返修最多两轮；每轮只有新失败证据才能继续，普通修订保留既有纠正次数。
    max_attempts = 2 if is_repair else MAX_NO_CHANGE_CORRECTIONS + 1 if is_revision else 1
    for repair_attempt in range(1, max_attempts + 1):
        attempt_before = {path: path.read_bytes() for path in product_files(root)}
        base_context = {**base_context,
                        "existing_product_files": [str(path.relative_to(root)) for path in attempt_before],
                        "snapshot": {"step_run_id": run.id, "repair_attempt": repair_attempt,
                                     "scope": "attempt_start",
                                     "file_sha256": {str(path.relative_to(root)): hashlib.sha256(content).hexdigest()
                                                     for path, content in attempt_before.items()}},
                        "failure_evidence_source": dict(failure_evidence_source)}
        # 每轮使用实际文件快照，避免纠正时仍把修改前的代码当作当前代码。
        if is_revision:
            # 每轮保留最新验证输出；只有非返修修订才预载完整源码。
            base_context = {**base_context, "latest_failure_report": latest_failure_report}
            if not is_repair:
                base_context["current_product_files"] = {
                    str(path.relative_to(root)): content.decode("utf-8", errors="replace")
                    for path, content in attempt_before.items()}
        def repair_file_changed() -> bool:
            # 返修首次写入后立即把控制权交回程序复跑原失败验证。
            return any(path.is_file() and attempt_before.get(path) != path.read_bytes()
                       for path in product_files(root))

        model_tool_loop(db, task, run, instructions, product,
                        {**base_context, "repair_feedback": repair_feedback}, tools,
                        stop_when=repair_file_changed if is_repair else stop_when,
                        tool_schemas=repair_tools,
                        max_calls=2 if is_repair else None)
        missing = missing_product_files(root)
        if missing:
            raise RuntimeError(f"implementation_files_missing:{','.join(missing)}")
        current_paths = product_files(root)
        changed_paths = {path for path in current_paths if attempt_before.get(path) != path.read_bytes()}
        changed = not is_revision or bool(changed_paths)
        if non_bug_change and not is_repair:
            code_changed = any(path.suffix in {".html", ".css", ".js", ".cjs", ".mjs"}
                               and not is_product_test(path) for path in changed_paths)
            test_changed = any(is_product_test(path) or path.name == "verify_product.py" for path in changed_paths)
            changed = code_changed and test_changed if feature_change else code_changed or test_changed
        if changed and is_repair and failure_source in {Step.test.value, Step.verify_product.value}:
            if failure_source == Step.verify_product.value and task.result_url:
                command = f"{shlex.quote(sys.executable)} verify_product.py {shlex.quote(task.result_url)}"
            else:
                command = "node --test"
            validation = execute_tool(db, task, run, tools, ToolCall(
                str(uuid.uuid4()), "exec", {"action": "run", "command": command}))
            validation_passed = (validation.status == "succeeded"
                                 and validation.output.get("exit_code") == 0
                                 and "[SKIP]" not in validation.output.get("stdout", ""))
            if validation_passed:
                break
            # 最新受控验证结果替代旧报告，后续无写入纠正也必须保留本次错误。
            latest_failure_report = json.dumps(validation.__dict__, ensure_ascii=False, default=str)
            failure_evidence_source = {"step_run_id": run.id, "repair_attempt": repair_attempt,
                                       "source": "controlled_validation", "sha256": content_hash(latest_failure_report),
                                       "file_snapshot": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                                                         for path in product_files(root)}}
            repair_feedback = {
                "attempt": repair_attempt,
                "message": "文件虽有变化，但最初失败的验证仍未通过。请根据本次真实输出继续修复，不得只运行其他测试。",
                "failure_source_step": failure_source,
                "validation_command": command,
                "validation_result": validation.__dict__,
            }
            safe_record_trace(db, task, run, "repair_validation", "failed", "返修验证仍失败",
                              f"第 {repair_attempt} 次修改未修复 {failure_source}", repair_feedback,
                              {"attempt": repair_attempt, "failure_source_step": failure_source})
            db.commit()
            if repair_attempt == max_attempts:
                raise RuntimeError("repair_validation_failed")
            continue
        if changed:
            break
        hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in product_files(root)}
        repair_feedback = {**(repair_feedback or {}),
            "attempt": repair_attempt,
            "message": "本轮返修未产生实际文件变化。相同失败证据禁止再次调用模型。",
            "failure_source_step": failure_source,
            "latest_failure_report": latest_failure_report,
            "unchanged_file_sha256": hashes,
        }
        safe_record_trace(db, task, run, "repair_no_change", "failed", "返修未产生文件变化",
                          f"第 {repair_attempt} 次无变化，事务式返修停止",
                          repair_feedback,
                          {"attempt": repair_attempt, "failure_source_step": failure_source})
        db.commit()
        if "validation_result" in repair_feedback:
            raise RuntimeError("repair_made_no_changes:latest_validation_failed")
        raise RuntimeError("repair_made_no_changes")
    # 更新实现依据的哈希和来源，便于后续设计变化时识别需要增量修改。
    write_json_atomic(lineage_path, {"dev_design_hash": dev_design_hash,
                                    "design_source": design_source,
                                    "develop_attempt": run.attempt,
                                    "product_hash": content_hash(product)})
    run.output_path = "product/implementation.md"
    finish_step(db, task, run, Step.test)


def handle_test(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 运行生成软件测试并据结果推进或返修。
    if not check_product_entry(db, task, run):
        return
    result = execute_tool(db, task, run, tools, ToolCall(call_id=str(uuid.uuid4()), tool_name="exec",
                                   parameters={"action": "run", "command": "node --test"}))
    report = workspace_for(task) / "evidence" / "test-report.md"
    report.write_text("# 测试报告\n\n```text\n" + json.dumps(result.__dict__, ensure_ascii=False, indent=2) + "\n```\n",
                      encoding="utf-8")
    run.output_path = "evidence/test-report.md"
    passed = (result.status == "succeeded" and result.output.get("exit_code") == 0
              and "[SKIP]" not in result.output.get("stdout", ""))
    if passed:
        safe_record_trace(db, task, run, "validation", "succeeded", "单元测试通过",
                          "node --test 返回 0", result.__dict__)
        if active_bug_triage(task):
            # 为 Bug 闭环绑定本次通过测试的代码版本，防止改动后直接启动。
            write_json_atomic(workspace_for(task) / "evidence" / "bug-tested-code-hashes.json",
                              product_code_hashes(task))
        finish_step(db, task, run, Step.start_product)
    else:
        fail_or_repair(db, task, run, result.error or result.output.get("stderr") or "unit_tests_failed")


def free_port() -> int:
    # 取得供生成软件本地启动使用的空闲端口。
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def handle_start(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 启动生成软件并检查 HTTP 健康状态。
    port = free_port()
    command = f"python -m http.server {port} --bind 127.0.0.1"
    result = execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec", {"action": "start", "command": command}))
    if result.status != "succeeded" or not result.output.get("running"):
        fail_or_repair(db, task, run, result.error or "product_start_failed")
        return
    url = f"http://127.0.0.1:{port}"
    try:
        healthy = False
        for _ in range(20):
            try:
                with httpx.Client(trust_env=False, timeout=1) as client:
                    healthy = client.get(url).status_code == 200
                if healthy:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        if not healthy:
            raise RuntimeError("health_check_failed")
    except Exception as exc:
        execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec", {"action": "stop", "process_id": result.output["process_id"]}))
        fail_or_repair(db, task, run, str(exc))
        return
    task.port = port
    task.process_id = result.output["process_id"]
    task.process_command = command
    task.result_url = url
    safe_record_trace(db, task, run, "validation", "succeeded", "健康检查通过", url,
                      {"url": url, "process_id": result.output["process_id"]})
    run.output_path = "product/index.html"
    finish_step(db, task, run, Step.verify_product)


def handle_verify(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 在真实浏览器中验证生成软件并保存结果。
    if not check_product_entry(db, task, run):
        return
    unit = execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
                                 {"action": "run", "command": "node --test"}))
    python = shlex.quote(sys.executable)
    browser = execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
                                    {"action": "run", "command": f"{python} verify_product.py {task.result_url}"}))
    unit_passed = unit.status == "succeeded" and unit.output.get("exit_code") == 0
    browser_stdout = browser.output.get("stdout", "")
    browser_passed = (browser.status == "succeeded" and browser.output.get("exit_code") == 0
                      and "[SKIP]" not in browser_stdout)
    passed = unit_passed and browser_passed
    safe_record_trace(db, task, run, "validation", "succeeded" if passed else "failed",
                      "真实产品验证", "单元测试与浏览器验证均通过" if passed else "产品验证未通过",
                      {"unit_passed": unit_passed, "browser_passed": browser_passed,
                       "unit": unit.__dict__, "browser": browser.__dict__})
    report = write_verification_evidence(task, unit, browser)
    if not passed:
        fail_or_repair(db, task, run, browser.error or browser.output.get("stderr") or "verification_failed")
        return
    readme = workspace_for(task) / "product" / "README.md"
    readme.write_text(f"# 生成的软件\n\n访问地址：{task.result_url}\n\n启动命令：`{task.process_command}`\n",
                      encoding="utf-8")
    run.output_path = "evidence/verification-report.md"
    if active_bug_triage(task):
        # Bug 验证通过后记录对应代码版本，留待 Planner 提议 finish 并由程序核验。
        write_json_atomic(workspace_for(task) / "evidence" / "bug-verified-code-hashes.json",
                          product_code_hashes(task))
        run.status = StepStatus.succeeded
        run.finished_at = datetime.utcnow()
        safe_record_trace(db, task, run, "step", "succeeded", "Bug 验证阶段完成",
                          "自动测试与真实浏览器验证通过，等待 Planner 提议 finish",
                          {"result_url": task.result_url}, started_at=run.started_at,
                          finished_at=run.finished_at)
        task.version += 1
        db.commit()
        return
    # 阶段成功后同时更新执行记录、任务状态和版本。
    run.status = StepStatus.succeeded
    run.finished_at = datetime.utcnow()
    task.status = TaskStatus.waiting_acceptance
    safe_record_trace(db, task, run, "step", "succeeded", "验证阶段完成",
                      "自动测试与真实浏览器验证通过", {"result_url": task.result_url},
                      started_at=run.started_at, finished_at=run.finished_at)
    safe_record_trace(db, task, run, "state_transition", "waiting", "等待人工验收",
                      "verify_product → waiting_acceptance", {"result_url": task.result_url})
    task.version += 1
    add_message(db, task, "assistant", f"软件已完成自动测试与真实浏览器验证，请访问 {task.result_url} 验收。")
    db.commit()


def reject_event(event: Event, reason: str):
    # 标记不适用的用户事件及拒绝原因。
    event.status = EventStatus.rejected
    event.error = reason
    event.processed_at = datetime.utcnow()


ACCEPTANCE_ACTIONS = {
    "update_requirement": ("requirement_change", Step.product_docs),
    "update_architecture": ("architecture_defect", Step.architecture_docs),
    "update_dev_design": ("dev_design_defect", Step.dev_design),
    "modify_code": ("implementation_defect", Step.develop),
}


def parse_acceptance_action(value: dict) -> dict:
    # 把 Planner 行动映射成下游兼容的分类，并校验需求变更的行为契约。
    action = value.get("action")
    confidence = value.get("confidence", 0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        confidence = 0
    classification = ACCEPTANCE_ACTIONS[action][0] \
        if isinstance(action, str) and action in ACCEPTANCE_ACTIONS else "unclear"
    changes = []
    for item in value.get("changes", []) if isinstance(value.get("changes"), list) else []:
        if not isinstance(item, dict):
            continue
        current = item.get("current_behavior")
        expected = item.get("expected_behavior")
        examples = item.get("acceptance_examples")
        if isinstance(current, str) and current.strip() and isinstance(expected, str) and expected.strip() \
                and isinstance(examples, list) and examples and all(isinstance(x, str) and x.strip() for x in examples):
            changes.append({"current_behavior": current.strip(), "expected_behavior": expected.strip(),
                            "acceptance_examples": [x.strip() for x in examples]})
    if confidence < 0.7 or classification == "requirement_change" and not changes:
        classification = "unclear"
    return {
        "planner_action": action if classification != "unclear" else "clarify",
        "classification": classification,
        "reason": str(value.get("reason", "证据不足")),
        "evidence": value.get("evidence") if isinstance(value.get("evidence"), list) else [],
        "changes": changes,
        "confidence": confidence,
        "clarifying_question": (value.get("clarifying_question") or
                                 "请补充期望行为、实际行为和复现步骤。")
        if classification == "unclear" else None,
    }


def plan_acceptance_action(db: Session, task: Task, run: StepRun, feedback: str,
                           approved_documents: dict, candidates: list[str]) -> tuple[dict, dict]:
    # 同一个 Planner 按反馈连续调查证据，然后直接选择文档、代码或澄清行动。
    root = workspace_for(task)
    inspected: dict = {}
    tools = ToolRuntime(root)
    protocol_error = None
    invalid_count = 0
    for index in range(6):
        remaining = [path for path in candidates if path not in inspected]
        allowed = ["clarify", *ACCEPTANCE_ACTIONS]
        if remaining and len(inspected) < 3:
            allowed.insert(0, "inspect")
        # Planner 不接触工具；所有正式文档和已读取证据在下一轮规划中继续可见。
        response = model_tool_loop(
            db, task, run,
            """你是已有产品验收反馈的 Next Action Planner。用户描述只是线索；对照实际存在的正式文档、明确保存的设计跳过依据和已调查证据，直接决定下一行动。被跳过的文档不是空白正式设计；若新问题表明必须补设计，可选择对应更新。若要判断代码实现缺陷，先 inspect 相关产品代码；证据不足可继续 inspect 或 clarify。只返回一个 JSON 对象：action、path、reason、evidence、changes、confidence、clarifying_question。action 必须在 allowed_actions 中；inspect 的 path 必须在 remaining_files 中，其他行动的 path 为 null。编号反馈逐条解释，选择所有条目中最早失效的行动。改变或新增产品可见行为选 update_requirement；需求不变但架构决策缺失或冲突选 update_architecture；架构成立但实现细节设计必须补充或冲突选 update_dev_design；正式需求和现有设计或跳过依据均支持期望行为而代码不符才选 modify_code。不能只凭“缺陷”一词认定代码问题，不能把用户描述的现状当期望。update_requirement 的 changes 每项须含 current_behavior、expected_behavior 和非空 acceptance_examples；clarify 须只提出一个具体问题。不得写文件或执行命令。""",
            feedback, {"approved_documents": approved_documents, "remaining_files": remaining,
                       "skipped_design": skipped_design_evidence(task),
                       "inspected_files": inspected, "allowed_actions": allowed,
                       "protocol_error": protocol_error,
                       "latest_verification_report":
                       (root / "evidence" / "verification-report.md").read_text(encoding="utf-8")
                       if (root / "evidence" / "verification-report.md").is_file() else ""},
            tools, tool_schemas=[], history_key=f"acceptance_plan_{run.id}_{index}",
            runtime_step=Step.product_docs)
        try:
            decision = json.loads(response.strip().removeprefix("```json").removeprefix("```")
                                  .removesuffix("```").strip())
        except json.JSONDecodeError:
            decision = {}
        if not isinstance(decision, dict):
            decision = {}
        action = decision.get("action")
        path = decision.get("path")
        if action == "inspect" and path in remaining and len(inspected) < 3:
            # 工具再次解析目标路径，拒绝清单外文件和符号链接逃逸。
            result = tools.execute(ToolCall(call_id=str(uuid.uuid4()), tool_name="read", parameters={"path": path}))
            if result.status != "succeeded" or result.output.get("truncated"):
                safe_record_trace(db, task, run, "acceptance_inspect", "failed", "证据读取失败",
                                  str(path), {"error": result.error, "truncated": result.output.get("truncated")})
                break
            digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
            inspected[path] = {"content": result.output["content"], "sha256": digest}
            safe_record_trace(db, task, run, "acceptance_inspect", "succeeded", "读取验收证据",
                              path, {"path": path, "sha256": digest, "content": result.output["content"]},
                              {"path": path, "sha256": digest})
            continue
        # 文档变更可依正式文件直接判断；实现缺陷必须有实际读取的产品代码证据。
        code_inspected = any(path.startswith("product/") and Path(path).suffix in {
            ".html", ".css", ".js", ".py"} for path in inspected)
        if action in {"clarify", *ACCEPTANCE_ACTIONS} and action in allowed \
                and (action != "modify_code" or code_inspected):
            parsed = parse_acceptance_action(decision)
            safe_record_trace(db, task, run, "acceptance_plan_decision", "succeeded", "验收下一行动",
                              parsed["planner_action"], {"decision": decision, "validated": parsed},
                              {"action": parsed["planner_action"], "classification": parsed["classification"]})
            return parsed, inspected
        safe_record_trace(db, task, run, "acceptance_inspect", "failed", "Planner 行动无效",
                          str(action), {"decision": decision, "allowed_actions": allowed,
                                        "remaining_files": remaining})
        invalid_count += 1
        protocol_error = {"message": "行动不在可选集合、目标不在文件清单，或代码缺少必需调查。",
                          "attempt": invalid_count}
        if invalid_count >= 2:
            break
    # 非法决定或达到有界调用上限时不猜测阶段，转为用户澄清。
    return {"planner_action": "clarify", "classification": "unclear", "reason": "调查证据不足或行动无效",
            "evidence": [], "changes": [], "confidence": 0,
            "clarifying_question": "请补充实际行为、期望行为和复现步骤。"}, inspected


def plan_acceptance_feedback(db: Session, task: Task, event: Event, feedback: str):
    # 将已有产品验收反馈交给统一 Planner 调查并提议最早需要处理的行动。
    root = workspace_for(task)
    run = db.scalar(select(StepRun).where(
        StepRun.task_id == task.id, StepRun.step == Step.verify_product,
        StepRun.status == StepStatus.running, StepRun.started_at >= event.created_at
    ).order_by(StepRun.id.desc()).limit(1))
    if not run:
        attempt = (db.scalar(select(func.max(StepRun.attempt)).where(
            StepRun.task_id == task.id, StepRun.step == Step.verify_product)) or 0) + 1
        checkpoint = root / "evidence" / f"acceptance-triage-{event.id}-checkpoint.json"
        run = StepRun(task_id=task.id, step=Step.verify_product, attempt=attempt,
                      checkpoint_path=str(checkpoint), last_completed_action_index=-1)
        db.add(run)
        db.flush()
        safe_record_trace(db, task, run, "step", "running", "验收规划开始",
                          f"Event {event.id} 使用独立调用预算",
                          {"event_id": event.id, "attempt": attempt}, started_at=run.started_at)
    inputs = {}
    for name in ("product.md", "architecture.md", "dev-design.md"):
        path = root / "docs" / name
        inputs[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    skips = skipped_design_evidence(task)
    product_files = sorted(str(path.relative_to(root)) for path in (root / "product").rglob("*") if path.is_file())
    report_files = [f"evidence/{name}" for name in ("verification-report.md", "test-report.md")
                    if (root / "evidence" / name).is_file()]
    if not inputs["product.md"] or any(not inputs[name] and name not in skips
                                         for name in ("architecture.md", "dev-design.md")):
        # 只有具备明确跳过决定的缺省设计才可继续规划，其他缺失文档须澄清。
        result = {"planner_action": "clarify", "classification": "unclear", "reason": "正式设计缺失",
                  "evidence": [], "changes": [], "confidence": 0,
                  "clarifying_question": "当前正式需求或设计文件缺失，请先确认该产品的有效文档。"}
        inspected = {}
    else:
        result, inspected = plan_acceptance_action(
            db, task, run, feedback, inputs, report_files + product_files)
    context = {
        "approved_documents": inputs,
        "skipped_design": skips,
        "product_files": product_files,
        "inspected_files": inspected,
    }
    # Planner 已提议澄清时无需再请求一致性模型。
    if result["classification"] == "unclear":
        consistency = {"consistent": False, "contradictions": [result["reason"]],
                       "clarifying_question": result["clarifying_question"]}
    else:
        # 再次核对行为变更契约与分类是否一致。
        consistency_text = model_tool_loop(
        db, task, run,
        """你是独立 Acceptance Interpretation Consistency Validator，不重新解决产品问题，也不修改文件。
检查初步分类是否忠实且自洽：用户是在“报告问题”，每个编号项都必须解释；current_behavior 必须是用户观察到的现状，expected_behavior 必须是用户希望改变后的行为。若某项被解释出的 expected_behavior 与现有正式需求相同，但初步分类又无法说明实际实现如何违反它，该解释通常把缺陷描述反当成期望；若原句方向存在两种合理解释，也必须判为不一致并要求澄清。总体 classification 必须采用所有条目中最早失效的阶段。
只返回 JSON：consistent 为布尔值；contradictions 为字符串数组；clarifying_question 在不一致时只问一个能消除行为方向歧义的问题，一致时为 null。""",
        feedback, {"approved_documents": inputs, "skipped_design": skips,
                   "inspected_files": inspected, "initial_triage": result},
        ToolRuntime(root), tool_schemas=[],
        history_key=f"acceptance_consistency_{event.id}", runtime_step=Step.product_docs)
        try:
            consistency = json.loads(consistency_text.strip().removeprefix("```json").removeprefix("```")
                                     .removesuffix("```").strip())
        except json.JSONDecodeError:
            consistency = {"consistent": False, "contradictions": ["一致性审查未返回合法 JSON"],
                           "clarifying_question": "请明确说明当前行为和你期望修改后的行为。"}
    valid_consistency = (isinstance(consistency, dict)
                         and isinstance(consistency.get("consistent"), bool)
                         and isinstance(consistency.get("contradictions"), list))
    if not valid_consistency or consistency.get("consistent") is not True:
        result["classification"] = "unclear"
        result["planner_action"] = "clarify"
        result["clarifying_question"] = (consistency.get("clarifying_question")
                                           if isinstance(consistency, dict) else None) or \
                                          "请明确说明当前行为和你期望修改后的行为。"
    result["consistency_validation"] = consistency
    result.update({"event_id": event.id, "user_feedback": feedback,
                   "inspected_evidence": {path: data["sha256"] for path, data in inspected.items()}})
    target = ACCEPTANCE_ACTIONS[result["planner_action"]][1] if result["classification"] != "unclear" else None
    result["target_step"] = target.value if target else None
    evidence_path = root / "evidence" / f"acceptance-triage-{event.id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    safe_record_trace(db, task, run, "acceptance_plan",
                      "waiting" if target is None else "succeeded", "验收下一行动",
                      f"{result['planner_action']} → {result['target_step'] or 'waiting_user'}",
                      {"input": {"feedback": feedback, **context}, "validated_result": result},
                      {"planner_action": result["planner_action"], "classification": result["classification"],
                       "target_step": result["target_step"],
                       "confidence": result["confidence"], "event_id": event.id})
    if target is None:
        run.status = StepStatus.waiting_user
        task.status = TaskStatus.waiting_user
        task.cur_step = Step.verify_product
        add_message(db, task, "assistant", result["clarifying_question"])
    else:
        # 阶段成功后同时更新执行记录、任务状态和版本。
        run.status = StepStatus.succeeded
        run.finished_at = datetime.utcnow()
        task.status = TaskStatus.running
        task.cur_step = target
        task.failure_reason = None
        if target == Step.develop and result["classification"] == "implementation_defect":
            task.repair_round += 1
        else:
            task.repair_round = 0
        add_message(db, task, "assistant",
                    f"下一行动为 {result['planner_action']}，将从 {target.value} 阶段处理。")
    return result


def consume_event(db: Session, event: Event, task: Task):
    # 根据事件类型和当前状态处理用户操作。
    data = event.data or {}
    if event.type == "document_approval":
        if task.status != TaskStatus.waiting_user or task.cur_step != Step.product_docs:
            reject_event(event, "task_not_waiting_for_product_approval")
            return
        latest = db.scalar(select(StepRun).where(StepRun.task_id == task.id, StepRun.step == Step.product_docs)
                           .order_by(StepRun.attempt.desc()))
        expected = latest.attempt if latest else 0
        if data.get("document_type") != "product" or data.get("document_version") != expected:
            reject_event(event, "document_type_or_version_mismatch")
            return
        candidate = workspace_for(task) / f"docs/product-v{expected}-candidate.md"
        legacy_draft = workspace_for(task) / f"docs/product-v{expected}-draft.md"
        source = candidate if candidate.is_file() else legacy_draft
        if not source.is_file():
            reject_event(event, "product_draft_not_available")
            return
        feedback = str(data.get("feedback", ""))
        add_message(db, task, "user", feedback or ("批准产品文档" if data.get("approved") else "拒绝产品文档"))
        if data.get("approved"):
            target = workspace_for(task) / "docs/product.md"
            previous_version = workspace_for(task) / f"docs/product-v{expected - 1}.md"
            if target.is_file() and expected > 1 and not previous_version.is_file():
                atomic_copy(target, previous_version)
            atomic_copy(source, target)
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                raise RuntimeError("formal_product_write_failed")
            formal_version = workspace_for(task) / f"docs/product-v{expected}.md"
            if not formal_version.is_file():
                atomic_copy(source, formal_version)
            latest.status = StepStatus.succeeded
            latest.finished_at = datetime.utcnow()
            task.cur_step = Step.architecture_docs
        task.status = TaskStatus.running
    elif event.type == "acceptance_result":
        if task.status != TaskStatus.waiting_acceptance:
            reject_event(event, "task_not_waiting_for_acceptance")
            return
        add_message(db, task, "user", str(data.get("feedback", "")) or "提交验收结果")
        if data.get("approved"):
            task.status = TaskStatus.succeeded
        else:
            feedback = str(data.get("feedback", "")).strip()
            if not feedback:
                reject_event(event, "acceptance_feedback_required")
                return
            # 将人工反馈路由到最早失效阶段。
            plan_acceptance_feedback(db, task, event, feedback)
    elif event.type == "change_request":
        # 已验收的产品在原任务上接收新功能请求，保留全部正式文档和历史证据。
        if task.status != TaskStatus.succeeded:
            reject_event(event, "task_not_succeeded_for_change_request")
            return
        feedback = str(data.get("feedback", "")).strip()
        if not feedback:
            reject_event(event, "change_request_feedback_required")
            return
        add_message(db, task, "user", feedback)
        plan_acceptance_feedback(db, task, event, feedback)
    elif event.type == "user_message":
        add_message(db, task, "user", str(data.get("content", "")))
        if task.status == TaskStatus.waiting_user:
            if task.cur_step == Step.product_docs:
                latest = db.scalar(select(StepRun).where(
                    StepRun.task_id == task.id, StepRun.step == Step.product_docs
                ).order_by(StepRun.attempt.desc()))
                if latest:
                    draft = workspace_for(task) / "docs" / f"product-v{latest.attempt}-draft.md"
                    if not draft.is_file():
                        latest.status = StepStatus.running
                task.status = TaskStatus.running
            elif task.cur_step == Step.verify_product:
                previous = sorted((workspace_for(task) / "evidence").glob("acceptance-triage-*.json"))
                prior_feedback = ""
                if previous:
                    prior_feedback = json.loads(previous[-1].read_text(encoding="utf-8")).get("user_feedback", "")
                combined = f"{prior_feedback}\n\n用户补充：{data.get('content', '')}".strip()
                # 将人工反馈路由到最早失效阶段。
                plan_acceptance_feedback(db, task, event, combined)
            else:
                # 单元设计问答恢复同一阶段预算，不能因一次回答重新获得整份调用上限。
                latest = db.scalar(select(StepRun).where(StepRun.task_id == task.id,
                    StepRun.step == task.cur_step, StepRun.status == StepStatus.waiting_user)
                    .order_by(StepRun.id.desc()).limit(1))
                if latest:
                    latest.status = StepStatus.running
                task.status = TaskStatus.running
    else:
        reject_event(event, "unknown_event_type")
        return
    task.version += 1
    event.status = EventStatus.consumed
    event.processed_at = datetime.utcnow()
    latest_run = db.scalar(select(StepRun).where(StepRun.task_id == task.id)
                           .order_by(StepRun.id.desc()).limit(1))
    safe_record_trace(db, task, latest_run, "user_event", "succeeded", "用户事件已处理",
                      event.type, {"event_id": event.id, "type": event.type, "data": data,
                                   "task_status": task.status.value, "cur_step": task.cur_step.value})


def process_pending_event(db: Session) -> bool:
    # 领取并处理一个待消费的用户事件。
    event = db.scalar(select(Event).where(Event.status == EventStatus.pending).order_by(Event.id).limit(1))
    if not event:
        return False
    task = db.get(Task, event.task_id)
    if not task:
        reject_event(event, "task_not_found")
    else:
        # 在锁定任务状态后处理用户事件。
        consume_event(db, event, task)
    db.commit()
    return True


def process_task(db: Session) -> bool:
    # 领取一个可运行任务并执行其当前阶段。
    task = db.scalar(select(Task).where(Task.status.in_([TaskStatus.pending, TaskStatus.running]))
                     .order_by(Task.created_at, Task.id).limit(1))
    if not task:
        return False
    task.status = TaskStatus.running
    task.version += 1
    db.commit()
    tools = ToolRuntime(workspace_for(task))
    run = create_step_run(db, task)
    db.commit()
    try:
        if task.cur_step in {Step.architecture_docs, Step.dev_design}:
            # 缺失的设计文档先由 Planner 判断必要性；已有正式版本仍走返工影响判断。
            design_target = ("architecture.md" if task.cur_step == Step.architecture_docs
                             else "dev-design.md")
            if (not (workspace_for(task) / "docs" / design_target).is_file()
                    and not (task.cur_step == Step.dev_design and any((workspace_for(task) / path).is_file()
                        for path in ("docs/development-plan.json", "docs/delivery-plan.json")))):
                action = plan_initial_design_action(db, task, run, tools)
                if action in {"clarify", "modify_code"}:
                    return True
                if action == "update_dev_design" and run.step == Step.architecture_docs:
                    return True
        if active_bug_triage(task) and task.cur_step in {
                Step.develop, Step.test, Step.start_product, Step.verify_product}:
            # Bug 闭环每轮先由 Planner 提议行动，程序只执行经校验的阶段内动作。
            action = plan_bug_action(db, task, run, tools)
            if action in {"inspect", "clarify"}:
                return True
            if action == "finish":
                # 再次核对同一代码版本的验证及服务可访问性，最终仅提交人工验收。
                if not bug_verified_ready(db, task):
                    raise RuntimeError("bug_finish_evidence_stale")
                with httpx.Client(trust_env=False, timeout=2) as client:
                    if client.get(task.result_url).status_code != 200:
                        raise RuntimeError("bug_finish_product_unavailable")
                run.status = StepStatus.succeeded
                run.finished_at = datetime.utcnow()
                task.status = TaskStatus.waiting_acceptance
                task.version += 1
                safe_record_trace(db, task, run, "state_transition", "waiting", "等待人工验收",
                                  "finish → waiting_acceptance", {"result_url": task.result_url})
                add_message(db, task, "assistant", f"软件已完成自动测试与真实浏览器验证，请访问 {task.result_url} 验收。")
                db.commit()
                return True
        if task.cur_step == Step.product_docs:
            handle_product_docs(db, task, run, tools)
        elif task.cur_step == Step.architecture_docs:
            handle_reviewed_doc(db, task, run, tools, "architecture")
        elif task.cur_step == Step.dev_design:
            handle_reviewed_doc(db, task, run, tools, "dev_design")
        elif task.cur_step == Step.develop:
            handle_develop(db, task, run, tools)
        elif task.cur_step == Step.test:
            handle_test(db, task, run, tools)
        elif task.cur_step == Step.start_product:
            handle_start(db, task, run, tools)
        elif task.cur_step == Step.verify_product:
            handle_verify(db, task, run, tools)
    except Exception as exc:
        safe_record_trace(db, task, run, "step", "failed", "阶段执行失败", str(exc),
                          {"error_type": type(exc).__name__, "error": str(exc)},
                          started_at=run.started_at, finished_at=datetime.utcnow())
        safe_record_trace(db, task, run, "state_transition", "failed", "任务失败",
                          str(exc), {"to": TaskStatus.failed.value})
        run.status = StepStatus.failed
        run.error = str(exc)
        run.finished_at = datetime.utcnow()
        task.status = TaskStatus.failed
        task.failure_reason = str(exc)
        task.version += 1
        add_message(db, task, "system", f"任务失败：{exc}")
        db.commit()
    return True


def run_forever():
    # 持续轮询事件和任务，驱动单 Worker。
    while True:
        with SessionLocal() as db:
            # 优先消费用户事件，再执行一个可运行任务。
            worked = process_pending_event(db) or process_task(db)
        if not worked:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run_forever()
