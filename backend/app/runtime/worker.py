import ast
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
from .context_relay import DeepSeekContextRelay, covered_end_line
from .model import ModelProtocolError, create_model_runtime
from .repair_runtime import BudgetExceeded
from .prompt_registry import PromptContent, sha256_text, load_prompt, compose_prompts, active_versions, bind_versions, rebind_prompt, PROMPT_ROOT
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

# 明确系统执行职责，旧执行卡的服务托管描述不能替代当前验证契约。
VERIFICATION_EXECUTION_CONTRACT = {
    "service_owner": "Worker 负责启动和停止产品服务；验证脚本不得创建 HTTP 服务或绑定端口。",
    "browser_script": "verify_product.py 接受命令行传入的位置 URL，在该当前产品 URL 上实际操作浏览器；不得回退旧地址或输出 skip 冒充通过。",
    "test_fixture": "Node 测试可以启动临时产品服务作为 URL 夹具，但不得要求验证脚本自行托管服务。",
    "legacy_conflicts": "当前契约优先于旧卡和测试的服务启动要求；在已有文件权限内修正冲突的服务实现断言或日志文字匹配，保留真实执行结果与业务断言。",
    "preserve_acceptance": "不得改变批准产品需求、业务规则和公共接口语义，不得删除业务操作／断言、使用 skip 或恒真断言。",
}
MAX_BUG_PLANNER_DECISIONS = 12
MAX_BUG_EXTRA_INSPECTIONS = 3

BASE_INSTRUCTIONS = load_prompt('execution-base')


def _action_signature(action: ToolCall) -> str:
    # 把工具动作转换为可比较的稳定签名。
    return json.dumps({"tool_name": action.tool_name, "parameters": action.parameters},
                      ensure_ascii=False, sort_keys=True)


def unit_idle_calls(history: list[dict], versions: dict) -> int:
    # 按模型批次统计连续无有效进展；实际版本变化或新的读取范围重置计数。
    batches = set()
    for entry in reversed(history):
        if (entry.get('unit_versions_before') != versions or entry.get('unit_versions_after') != versions
                or entry.get('unit_read_information_progress') is True):
            # 同一批次的其他动作不能把已经取得的实际进展重复计为停滞。
            batches.discard(entry.get('model_request_id'))
            break
        batches.add(entry.get('model_request_id'))
    return len(batches)


def _read_information_span(entry: dict, tools: ToolRuntime) -> tuple | None:
    # 从真实成功读取中取得规范路径、版本和实际返回范围，不相信调用描述。
    result = entry.get('result', {})
    if entry.get('action', {}).get('tool_name') != 'read' or result.get('status') != 'succeeded':
        return None
    output = result.get('output', {})
    content = output.get('content')
    if not isinstance(content, str) or not content or not output.get('sha256'):
        return None
    try:
        path = str(tools._safe_path(output['path']).relative_to(tools.workspace))
    except (KeyError, TypeError, ValueError):
        return None
    first = output.get('start_line') or 1
    # 截断输出只登记实际返回的行，不能把请求但未返回的范围算作已提供。
    return path, output['sha256'], first, first + len(content.splitlines()) - 1


def read_information_progress(entry: dict, history: list[dict], tools: ToolRuntime) -> bool:
    # 仅同版本中尚未返回的新行范围算信息进展，覆盖区间合并后仍去重。
    current = _read_information_span(entry, tools)
    if current is None:
        return False
    path, version, first, last = current
    intervals = []
    for previous in history:
        span = _read_information_span(previous, tools)
        if span and span[:2] == (path, version):
            intervals.append(span[2:])
    position = first
    # 合并多个已有读取的覆盖，不允许路径别名或重组行区间伪造新信息。
    for start, end in sorted(intervals):
        if start > position:
            break
        position = max(position, end + 1)
        if position > last:
            return False
    return position <= last


def duplicate_read_error(action: ToolCall, history: list[dict], request_context: dict,
                         tools: ToolRuntime) -> str | None:
    # 当前请求仍含对应内容时阻止同版本同范围重复读取，省略或变化后允许补读。
    if action.tool_name != 'read':
        return None
    try:
        path = str(tools._safe_path(action.parameters['path']).relative_to(tools.workspace))
    except (KeyError, TypeError, ValueError):
        return None
    target = tools.workspace / path
    if not target.is_file():
        return None
    if hasattr(tools, 'readable') and target not in tools.readable:
        return None
    visible_spans = []
    current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    requested_start, requested_end = action.parameters.get('start_line'), action.parameters.get('end_line')
    if requested_start is None and requested_end is None and hasattr(tools, 'default_read_lines'):
        # 默认两百行也是明确范围，重复默认预览不能伪装成补读全文。
        requested_start, requested_end = 1, min(tools.default_read_lines,
                                              len(target.read_text(encoding='utf-8').splitlines()))
    for available in request_context.get('carried_file_context', []):
        # 接力刷新后的正文独立证明当前范围；旧读记录的哈希不能替代这个新版本。
        if available.get('path') != path or available.get('content') is None:
            continue
        if available.get('sha256') == current_hash:
            visible_spans.append((available.get('start_line', 1), covered_end_line(available)))
        covered = (available.get('complete') is True if requested_start is None and requested_end is None else
                   type(requested_start) is int and type(requested_end) is int
                   and available.get('start_line', 1) <= requested_start <= requested_end <= available.get('covered_end_line', 0))
        if covered and available.get('sha256') == current_hash:
            return f'read_already_in_context:{path}:carried_file_context; use the available current-version content'
    snapshot = request_context.get('current_product_files', {})
    available_results = request_context.get('current_requested_data', []) + [
        entry.get('result', {}) for entry in
        request_context.get('tool_history', []) + request_context.get('reasoning_tool_history', [])
        if entry.get('action', {}).get('tool_name') == 'read']
    for entry in reversed(history):
        previous = entry.get('action', {})
        result = entry.get('result', {})
        if previous.get('tool_name') != 'read' or result.get('status') != 'succeeded':
            continue
        try:
            previous_path = str(tools._safe_path(previous['parameters']['path']).relative_to(tools.workspace))
        except (KeyError, TypeError, ValueError):
            continue
        if previous_path != path:
            continue
        output = result.get('output', {})
        # 历史读过不代表本次模型还看得到；只对实际保留的相同内容去重。
        if path not in snapshot and not any(
                available.get('status') == 'succeeded'
                and available.get('output', {}).get('content') is not None
                and available.get('output', {}).get('content') == output.get('content')
                and available.get('output', {}).get('sha256') == output.get('sha256')
                for available in available_results):
            continue
        if output.get('sha256') == current_hash:
            visible_spans.append((output.get('start_line', 1), covered_end_line(output)))
        if requested_start is None and requested_end is None:
            # 默认预览与字节截断不证明全文，允许读取缺少的范围。
            covered = (not output.get('truncated') and output.get('start_line', 1) == 1
                       and covered_end_line(output) == output.get('total_lines'))
        elif type(requested_start) is int and type(requested_end) is int:
            first = output.get('start_line', 1)
            # 工具声明的请求结束行可能含字节截断的半行，只有实际完整返回的范围可去重。
            last = (covered_end_line(output) if output.get('truncated') else
                    output.get('end_line', output.get('total_lines')))
            covered = last is not None and first <= requested_start <= requested_end <= last
        else:
            covered = False
        if not covered:
            continue
        prior_hash = output.get('sha256')
        if prior_hash and current_hash == prior_hash:
            return f'read_already_in_context:{path}:available_file_content; use the available content to write, test, or report a real blocker'
    # 多次实际返回的相邻范围共同覆盖请求时，也不能重复读取同一正文。
    merged = []
    for first, last in sorted(visible_spans):
        if last < first:
            continue
        if merged and first <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    if requested_start is None and requested_end is None and merged:
        requested_start, requested_end = 1, len(target.read_text(encoding='utf-8').splitlines())
    if type(requested_start) is int and type(requested_end) is int and any(
            first <= requested_start <= requested_end <= last for first, last in merged):
        return f'read_already_in_context:{path}:merged_visible_ranges; use the available content'
    return None


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
        if entry["action"].get("tool_name") in {"write", "replace"} and result.get("status") == "succeeded":
            break
        count += 1
    return count


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
    before = store.file_state(call.parameters.get("path")) if call.tool_name in {"read", "write", "replace"} else {}
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


def compact_repair_objectives(objectives: list[dict]) -> list[dict]:
    # 保留逐目标业务事实，将历史大报告及过期审查正文改为完整账本引用。
    values = []
    for item in objectives:
        value = {key: data for key, data in item.items()
                 if key not in {'original_verification_report', 'latest_review', 'verified_hashes'}}
        value['historical_evidence_ref'] = {'path':'evidence/repair-objectives.json', 'objective_id':item['id'],
            'original_report_sha256':sha256_text(item.get('original_verification_report') or '')}
        value['current_review_required'] = True
        values.append(value)
    return values


def compact_bug_planner_context(context: dict, fresh_paths: set[str]) -> dict:
    # 简单流程决策只提供状态与证据引用；刚完成的调查仍带真实正文。
    triage = context['acceptance_triage']
    value = {key: context[key] for key in (
        'last_action_result', 'code_hashes', 'allowed_actions', 'remaining_files',
        'remaining_decisions', 'repair_round')}
    value['acceptance_triage'] = {key: triage[key] for key in (
        'event_id', 'classification', 'planner_action') if key in triage}
    value['approved_document_refs'] = {name:{'path':f'docs/{name}', 'sha256':sha256_text(body)}
                                       for name, body in context['approved_documents'].items()}
    value['report_refs'] = {name:{'path':f'evidence/{name}', 'sha256':sha256_text(body)}
                            for name, body in context['reports'].items()}
    value['inspected_content'] = {path:body for path, body in context['inspected_content'].items()
                                  if path in fresh_paths}
    value['inspection_refs'] = {path:{**reference, 'body_in_context':path in value['inspected_content']}
                                for path, reference in context['inspection_refs'].items()}
    return value


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
        # 单元开发按需读正文，清单与版本继续刷新，不自动传送全部范围全文。
        value.pop("current_product_files", None)
        value["verification_execution_contract"] = VERIFICATION_EXECUTION_CONTRACT
        scope = set(context["unit_file_scope"])
        paths = [path for path in paths if str(path.relative_to(root)) in scope]
    if context.get("current_product_files") and "unit_file_scope" not in context:
        # 修订阶段继续提供完整当前快照；近期原始交互携带相同全文时不重复。
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
        diagnostic = context.get('unit_diagnostic')
        # 旧失败保留修复依据，同时明确当前版本是否仍适用，不把改动视为成功。
        for field, versions_field in [('unit_self_test', 'file_hashes_after'), ('unit_diagnostic', 'file_hashes_after'),
                                      ('unit_test_feedback', 'file_hashes_after'), ('global_failure', 'file_hashes')]:
            report = context.get(field)
            if report:
                versions = report.get(versions_field)
                current = {path:hashlib.sha256((root / path).read_bytes()).hexdigest() if (root / path).is_file() else None
                           for path in versions or {}}
                value[field] = {**report, 'matches_current_files':versions == current if versions is not None else None}
        # 当前自测优先；修改后的新诊断不能被过期自测遮住，也不能授予提交资格。
        self_test_current = bool(self_test and value['unit_self_test']['matches_current_files'])
        evidence_field = ('unit_self_test' if self_test_current else 'unit_diagnostic' if diagnostic else
                          'unit_self_test' if self_test else 'unit_test_feedback' if feedback else None)
        evidence = value.get(evidence_field)
        matches = bool(evidence and evidence.get('matches_current_files'))
        state = 'passed' if matches and evidence.get('passed') else 'failed' if matches else 'stale' if evidence else 'not_run'
        if not context.get('require_unit_submission') and feedback and feedback.get('passed') is False:
            # 旧无计划入口保留原失败提示，不要求旧报告补齐新增自测协议。
            state = 'failed'
        value['test_evidence_matches_current_files'] = matches
        value['development_state'] = {'unit_id':context.get('unit', {}).get('id'), 'missing_owned_files':missing,
            'test_state':state,
            'next_action':'develop_missing_files' if missing else
                'repair_current_unit_from_diagnostic' if state == 'failed' and evidence_field == 'unit_diagnostic' else
                'repair_current_unit_from_test_feedback' if state == 'failed' else
                'submit_unit_for_test' if state == 'passed' and self_test_current and context.get('require_unit_submission') else
                'run_unit_tests' if context.get('require_unit_submission') else 'finish_development_for_program_test',
            'file_presence_is_not_test_pass':True}
        # 当前任务先呈现原目标、有效职责和真实证据；完整依据仍只在原字段保留。
        focus = {
            'original_objectives_ref':'unresolved_acceptance_objectives' if 'unresolved_acceptance_objectives' in value else None,
            'effective_card':{'source_ref':'repair_task' if 'repair_task' in value else 'card' if 'card' in value else 'unit',
                'execution_contract_ref':'verification_execution_contract',
                'precedence':'业务验收与文件权限仍按原卡；旧卡服务托管及日志要求由当前执行契约覆盖。'},
            'latest_evidence':{'source_ref':evidence_field,
                'state':state, 'matches_current_files':matches,
                'integration_failure_ref':'global_failure' if value.get('global_failure') else
                    'unit_test_feedback.failure_report' if (feedback or {}).get('failure_report') else None},
            'remaining_work':{'missing_owned_files':missing,
                'needs_current_self_test':bool(context.get('require_unit_submission') and (state != 'passed' or not self_test_current)),
                'needs_explicit_submission':bool(context.get('require_unit_submission')),
                'objectives_pending_independent_verification':[item['id'] for item in value.get('unresolved_acceptance_objectives', [])]},
        }
        # 焦点置于请求正文最前，不复制卡片、原始目标或完整错误输出。
        value.pop('current_task', None)
        value = {'current_task':focus, **value}
    if context.get('repair_task'):
        # 旧报告仅作历史修复依据，完整原文仍在已授予只读权限的证据文件中。
        feedback = value.get('unit_test_feedback')
        report_path = ((root / feedback['detail_path']).resolve()
                       if feedback and isinstance(feedback.get('detail_path'), str) else None)
        if (report_path and root.resolve() in report_path.parents and report_path.is_file()
                and hashlib.sha256(report_path.read_bytes()).hexdigest() == feedback.get('report_sha256')):
            value['unit_test_feedback'] = {key: item for key, item in feedback.items() if key != 'failure_report'} | {
                'content_source':'read_on_demand', 'superseded_by_current_diagnostic':bool(value.get('unit_diagnostic'))}
            value['current_task']['latest_evidence']['integration_failure_ref'] = 'unit_test_feedback.detail_path'
        if (root / 'evidence/repair-objectives.json').is_file():
            # 目标原文、期望和复现保持；历史报告和核销说明留在账本供按需读取。
            value['unresolved_acceptance_objectives'] = compact_repair_objectives(
                value.get('unresolved_acceptance_objectives', []))
    return value


def model_tool_loop(db: Session, task: Task, run: StepRun, instructions: str | PromptContent, input_text: str,
                    context: dict, tools: ToolRuntime,
                    stop_when: Callable[[], bool] | None = None,
                    tool_schemas: list[dict] | None = None,
                    history_key: str = "default",
                    runtime_step: Step | None = None,
                    refresh_diagnostic: Callable[[], dict] | None = None) -> str:
    """绑定会话所有指令版本后执行循环，保留原工具协议与调用契约。"""
    from .repair_runtime import load as load_repair, save as save_repair
    repair = load_repair(workspace_for(task)) if context.get('repair_session') else None
    versions = active_versions()
    if repair:
        # 新字段仅冻结当前等价迁移版本；已有主模板哈希仍由会话核对。
        versions = repair['session'].get('prompt_versions',
            json.loads((PROMPT_ROOT / 'registry.json').read_text()).get('migration_baseline', versions))
        if 'prompt_versions' not in repair['session']:
            if isinstance(instructions, PromptContent):
                versions = {**versions, instructions.name: instructions.version}
            repair['session']['prompt_versions'] = versions
            save_repair(workspace_for(task), repair)
    else:
        # 每个旧流程逻辑会话独立绑定，恢复时不能跟随平台激活漂移。
        binding_file = workspace_for(task) / 'evidence' / f'prompt-bindings-{run.id}-{sha256_text(history_key)[:12]}.json'
        if binding_file.is_file():
            versions = json.loads(binding_file.read_text())['versions']
        else:
            checkpoint = Path(run.checkpoint_path) if run.checkpoint_path else None
            if checkpoint and checkpoint.is_file():
                versions = dict(json.loads((PROMPT_ROOT / 'registry.json').read_text()).get('migration_baseline', versions))
                if db is not None and run.id is not None:
                    for trace in db.scalars(select(TraceRecord).where(TraceRecord.step_run_id == run.id,
                            TraceRecord.type == 'model_request').order_by(TraceRecord.sequence)).all():
                        meta = trace.metadata_json
                        if meta.get('history_key') == history_key and meta.get('prompt_name') in versions:
                            versions[meta['prompt_name']] = meta['prompt_version']
            write_json_atomic(binding_file, {'versions': versions, 'history_key': history_key})
    with bind_versions(versions):
        return _model_tool_loop(db, task, run, rebind_prompt(instructions), input_text, context, tools,
                                stop_when, tool_schemas, history_key, runtime_step, refresh_diagnostic)


def _model_tool_loop(db: Session, task: Task, run: StepRun, instructions: str | PromptContent, input_text: str,
                    context: dict, tools: ToolRuntime,
                    stop_when: Callable[[], bool] | None = None,
                    tool_schemas: list[dict] | None = None,
                    history_key: str = "default",
                    runtime_step: Step | None = None,
                    refresh_diagnostic: Callable[[], dict] | None = None) -> str:
    # 在预算内循环调用模型、执行工具并保存过程证据。
    prompt = instructions if isinstance(instructions, PromptContent) else None
    instruction_text = prompt if prompt else instructions
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
                       if (entry.get("result") or (context.get('repair_session') and 'assistant_content' in entry))
                       and entry.get("history_key", "default") == history_key]
    # 根据阶段选择主 Provider，技术失败时才尝试受控降级。
    from .repair_runtime import load as load_repair
    repair_mode = load_repair(workspace_for(task))
    primary_runtime = create_model_runtime(db, Step.develop if repair_mode else runtime_step or task.cur_step)
    if context.get('repair_session'):
        # 连续主会话固定 Provider 和模型，配置变化不能悄悄迁移思考协议。
        from .repair_runtime import save as save_repair
        session = repair_mode['session']
        if primary_runtime.provider != session['provider']:
            raise RuntimeError('repair_session_provider_changed')
        if session.get('model') and session['model'] != primary_runtime.model_name:
            raise RuntimeError('repair_session_model_changed')
        session['model'] = primary_runtime.model_name
        save_repair(workspace_for(task), repair_mode)
    # 仅已有产物的 DeepSeek 切片返修启用接力，其他开发流程保持原会话边界。
    relay = (DeepSeekContextRelay(tools, repair_mode['event_id'] if context.get('repair_session') else run.id, history_key)
             if primary_runtime.provider == 'deepseek' and (context.get('repair_session') or
                (context.get('repair_task') and refresh_diagnostic is not None)) else None)
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
    while run.model_call_count < MAX_MODEL_CALLS_PER_STEP:
        if context.get('repair_session'):
            # 刷新当前计划、问题与完整文件集合；不因阶段恢复另建协议历史。
            current = load_repair(workspace_for(task))
            context = {**context, 'unit_file_scope': list(tools.self_test_versions()),
                       'unit_self_test': tools.self_test, 'plan': current['session']['plan'],
                       'decisions': current['session']['decisions'], 'last_failure': current.get('last_failure')}
        batch_versions = tools.self_test_versions() if relay else None
        if context.get('require_unit_submission'):
            from .unit_workflow import file_hashes
            versions = file_hashes(workspace_for(task), context['owned_files'])
            idle = unit_idle_calls(history, versions)
            self_test_current = bool(tools.self_test and tools.restore_self_test(tools.self_test))
            if idle >= 8 and not self_test_current:
                raise RuntimeError('unit_development_no_progress')
            context = {**context, 'unit_self_test':tools.self_test, 'unit_no_progress':{'calls_without_progress':idle,
                'progress_basis':load_prompt('worker-feedback-1').text,
                'instruction':(load_prompt('worker-feedback-2').text
                               if self_test_current else
                               load_prompt('worker-feedback-3').text if idle >= 4 else ''),
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
            schemas = schemas + QUERY_TOOL_SCHEMAS
        tool_instructions = load_prompt('worker-tool-instructions-738-1')
        # 区分未验证的历史成功与程序已核对当前全产品版本的真实自测，避免接力后反复怀疑证据。
        tool_instructions += (load_prompt('worker-tool-instructions-740-1')
                              if context.get('repair_session') else load_prompt('worker-tool-instructions-740-2'))
        if context.get('require_unit_submission'):
            # 开发自测与后续独立验证分开，旧失败不代表修改后的版本仍失败。
            tool_instructions += load_prompt('worker-tool-instructions-744-1')
            tool_instructions += load_prompt('worker-tool-instructions-745-1')
        if context.get('repair_task'):
            # 旧失败和目标历史可按需读取，当前诊断及目标业务事实仍直接提供。
            tool_instructions += load_prompt('worker-tool-instructions-748-1')
        if 'unit_file_scope' in context:
            # 按需读取仍须获得实际正文，清单与旧读取状态不能代替当前可用内容。
            tool_instructions += load_prompt('worker-tool-instructions-751-1')
            tool_instructions += load_prompt('worker-tool-instructions-752-1')
        if context.get('require_unit_submission') and context['unit_no_progress']['calls_without_progress'] >= 4:
            # 无进展提醒同步提升到系统指令，避免只埋在较长文件上下文中被忽略。
            tool_instructions += (load_prompt('worker-tool-instructions-755-1')
                                  if self_test_current else
                                  load_prompt('worker-tool-instructions-755-2'))
        if any(schema["function"]["name"] == "get_tool_execution_detail" for schema in schemas):
            tool_instructions += load_prompt('worker-tool-instructions-759-1')
        request_id = str(uuid.uuid4())
        request_context = {**build_tool_context(task, run, context, history, history_key),
                           "model_call_id": request_id,
                           # 计数已包含本次请求；沿用真实 Step 预算，不把传输重试误报为逻辑调用。
                           "model_call_budget": {"unit": "logical_model_call", "limit": MAX_MODEL_CALLS_PER_STEP,
                               "used_including_current": run.model_call_count,
                               "remaining_after_current": MAX_MODEL_CALLS_PER_STEP - run.model_call_count,
                                   "transport_retries_counted": False}}
        if repair_mode:
            # 当前视图展示实际 HTTP 剩余额度，逻辑调用数不能替代发送预算。
            actual = load_repair(workspace_for(task))
            budget = actual["budget"]
            reserve = 0 if actual["state"] == "reviewing" else budget["review_reserve"]
            request_context["actual_request_budget"] = {
                "attempts_used": budget["attempts_used"], "total_limit": budget["total_limit"],
                "review_reserve": budget["review_reserve"],
                "remaining_before_send": max(0, budget["total_limit"] - reserve - budget["attempts_used"]),
                "authorization_ref": actual["authorization_ref"], "retries_counted": True}
        if context.get('repair_session'):
            # 主会话不展示旧卡交接指令，允许自测后必要阅读及继续修改。
            request_context['current_task'] = {'session_id': context['session_id'],
                'original_feedback': actual['feedback'], 'plan': actual['session']['plan'],
                'last_failure': actual.get('last_failure'), 'write_scope': 'current_task_product',
                'needs_explicit_submission': True}
            self_test_current = bool(tools.self_test and tools.restore_self_test(tools.self_test))
            request_context['development_state'] = {'self_test_ref': 'unit_self_test',
                'current_version_passed': self_test_current,
                'next_action': 'submit_if_repair_complete' if self_test_current else 'continue_work_and_self_test',
                'instruction': (load_prompt('worker-feedback-4').text
                                if self_test_current else load_prompt('worker-feedback-5').text),
                'automatic_submit': False}
            tool_instructions += load_prompt('worker-tool-instructions-791-1')
        tool_instructions += load_prompt('worker-tool-instructions-792-1')
        if context.get('repair_session') and primary_runtime.provider != 'deepseek':
            # 所有返修供应商都保留会话工具历史，避免只看到上一批片段而重复补读。
            request_context['tool_history'] = history
        if primary_runtime.provider == "deepseek":
            # 当前会话完整续传；安全边界之前的原始历史保留在审计而不拼接到新会话。
            protocol_history, relay_context = relay.project(history, request_context) if relay else (history, {})
            request_context["reasoning_tool_history"] = protocol_history
            if relay_context:
                request_context.update(relay_context)
                current_calls = {entry.get('action', {}).get('call_id') for entry in protocol_history}
                request_context['current_requested_data'] = [item for item in request_context.get('current_requested_data', [])
                                                           if item.get('call_id') in current_calls]
                tool_instructions += load_prompt('worker-tool-instructions-802-1')
                tool_instructions += load_prompt('worker-tool-instructions-803-1')
                tool_instructions += load_prompt('worker-tool-instructions-804-1')
                if context.get('repair_session') and tools.self_test and tools.restore_self_test(tools.self_test):
                    # 通过诊断已完成独立上下文交接，只传版本与状态，完整输出可从审计查询。
                    request_context['unit_self_test'] = {k: v for k, v in tools.self_test.items() if k != 'result'}
                    request_context['unit_self_test']['result_ref'] = {'content_source': 'checkpoint_audit',
                        'query_tool': 'get_model_call_summaries', 'model_call_id': relay_context['context_session']['boundary_request_id']}
        if context.get('repair_session'):
            from .repair_session import project_test_history, self_test_view
            # 从首次发送起使用一致的摘要工具结果，原始思考和完整日志仍在检查点及 Trace。
            for key in ('tool_history', 'reasoning_tool_history'):
                if key in request_context:
                    request_context[key] = project_test_history(request_context[key])
            visible_results = {entry['action']['call_id']: entry['result']
                               for entry in request_context.get('reasoning_tool_history', request_context.get('tool_history', []))
                               if entry.get('action') and entry.get('result')}
            request_context['current_requested_data'] = [
                visible_results.get(item.get('call_id')) or {**item, 'output': self_test_view(item['output'])}
                if item.get('tool_name') == 'run_unit_tests' and isinstance(item.get('output'), dict) else item
                for item in request_context.get('current_requested_data', [])]
            if tools.self_test:
                source = next((entry for entry in reversed(history)
                               if entry.get('action', {}).get('tool_name') == 'run_unit_tests'), {})
                request_context['unit_self_test'] = self_test_view(tools.self_test, {
                    'content_source': 'checkpoint_audit', 'query_tool': 'get_model_call_summaries',
                    'model_call_id': source.get('model_request_id'),
                    'tool_call_id': source.get('action', {}).get('call_id')})
        if context.get('repair_session'):
            from .repair_session import current_facts, uses_current_facts
            if uses_current_facts(actual):
                # 新尝试在最后投影当前事实，不影响旧会话、实际协议或正文补读判定。
                request_context = current_facts(request_context, actual, history, tools)
                tool_instructions = (load_prompt('worker-tool-instructions-835-1'))
        combined_prompt = compose_prompts([load_prompt('execution-base'), instruction_text, tool_instructions])
        request = ModelRequest(instructions=combined_prompt.text, input=input_text,
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
                               "prompt_components": list(combined_prompt.components),
                               "combined_prompt_sha256": combined_prompt.rendered_sha256,
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
                except BudgetExceeded:
                    # 额度耗尽不是网络失败，不重试、不降级、不包装错误。
                    raise
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
                "instruction": load_prompt('worker-tool-instructions-740-3').text,
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
            if ((context.get('require_unit_submission') and not result.text.strip().startswith('BLOCKED:'))
                    or context.get('repair_session')):
                # 普通完成文本不能绕过显式提交，最多两次纠正后停止。
                text_without_submit += 1
                if text_without_submit > MAX_NO_CHANGE_CORRECTIONS:
                    raise RuntimeError('unit_submission_required')
                if runtime.provider == "deepseek" or context.get('repair_session'):
                    # 强制继续时保留通用助手响应，DeepSeek另外保存其协议要求的思考。
                    entry = {"history_key": history_key, "model_request_id": result.request_id,
                             "assistant_content": result.text,
                             "result": {"status": "succeeded"}}
                    if runtime.provider == 'deepseek':
                        entry['reasoning_content'] = result.raw_response.get('reasoning_content', '')
                    if context.get('repair_session'):
                        # 普通文本也保留思考，但不能依赖旧单元的文件清单。
                        entry['repair_versions_before'] = tools.self_test_versions()
                        entry['repair_versions_after'] = entry['repair_versions_before']
                    else:
                        entry["unit_versions_before"] = file_hashes(workspace_for(task), context['owned_files'])
                        entry["unit_versions_after"] = entry["unit_versions_before"]
                    history.append(entry)
                    checkpoint_entries.append(entry)
                    save_checkpoint(run, checkpoint_entries)
                context = {**context, 'submission_feedback': load_prompt('worker-extra-1757-3').text}
                continue
            return result.text
        if context.get('repair_session'):
            # 保存完整批次意图，逐动作结果落盘后解除；中断不能漏掉未执行调用。
            current = load_repair(workspace_for(task))
            current['session']['pending_actions'] = [a.__dict__ for a in result.actions]
            save_repair(workspace_for(task), current)
        # 工具执行前保存待办检查点，便于故障恢复。
        for index, action in enumerate(result.actions, start=run.last_completed_action_index + 1):
            entry = {"history_key": history_key, "model_request_id": result.request_id,
                     "action": action.__dict__}
            if context.get('repair_session'):
                # 通用助手内容与工具意图同批保存，恢复时仍能还原原始消息顺序。
                entry['assistant_content'] = result.text or None
            if runtime.provider == "deepseek":
                # 把本轮真实思考与工具调用共同持久化，恢复后按原内容续传。
                entry["reasoning_content"] = result.raw_response.get("reasoning_content", "")
                entry["assistant_content"] = result.text or None
            if context.get('require_unit_submission'):
                entry['unit_versions_before'] = file_hashes(workspace_for(task), context['owned_files'])
            if context.get('repair_session'):
                # 登记实际产品版本变化，为之后的完整自测批次提供接力依据。
                entry['repair_versions_before'] = tools.self_test_versions()
            entries = checkpoint_entries + [entry]
            save_checkpoint(run, entries)
            signature = _action_signature(action)
            repeated = _recent_action_count(checkpoint_entries, history_key, signature)
            repair_without_write = (context.get("repair_round", 0) > 0
                                    and not context.get("require_unit_submission")
                                    and action.tool_name not in {"write", "replace"}
                                    and _repair_actions_without_write(checkpoint_entries, history_key)
                                    >= MAX_REPAIR_ACTIONS_WITHOUT_WRITE)
            # 阻止连续重复动作和返修中无写入循环。
            invalid_submit = ((context.get('require_unit_submission') or context.get('repair_session'))
                              and action.tool_name in {'submit_unit_for_test', 'verify_and_submit', 'request_decision'}
                              and action is not result.actions[-1])
            duplicate_read = duplicate_read_error(action, history, request_context, tools)
            if context.get('repair_session') and action.tool_name == 'read' and not duplicate_read:
                # 合法补读以当前可见版本为准，不能被旧动作签名继续禁止。
                parameters = action.parameters
                first, last = parameters.get('start_line'), parameters.get('end_line')
                valid_range = ((first is None and last is None) or
                               (type(first) is int and type(last) is int and 1 <= first <= last))
                try:
                    target = tools._safe_path(parameters['path'])
                    if valid_range and target in tools.readable and target.is_file():
                        repeated = 0
                except (KeyError, TypeError, ValueError):
                    pass
            if repeated >= MAX_IDENTICAL_TOOL_ACTIONS or repair_without_write or invalid_submit or duplicate_read:
                # 阻止连续重复动作和返修中无写入循环。
                code = ('submission_must_be_last' if invalid_submit else
                        'duplicate_read' if duplicate_read else
                        'repeated_tool_action' if repeated >= MAX_IDENTICAL_TOOL_ACTIONS else
                        'repair_tool_loop_no_write')
                safe_record_trace(db, task, run, "tool_guard", "failed", "阻止无效工具循环", code,
                                  {"action": action.__dict__, "reason": code},
                                  {"history_key": history_key, "reason": code})
                tool_result = execute_tool(db, task, run, tools, action, result.request_id, history_key,
                                           duplicate_read or code)
            else:
                # 受控工具执行后记录调用、结果和文件产物。
                tool_result = execute_tool(db, task, run, tools, action, result.request_id, history_key)
            entry["result"] = tool_result.__dict__
            if context.get('repair_session'):
                entry['repair_versions_after'] = tools.self_test_versions()
            if context.get('require_unit_submission'):
                entry['unit_versions_after'] = file_hashes(workspace_for(task), context['owned_files'])
                # 读取进展与完成状态独立保存，检查点恢复后不重复发放相同范围进展。
                entry['unit_read_information_progress'] = read_information_progress(entry, history, tools)
            history.append(entry)
            checkpoint_entries.append(entry)
            save_checkpoint(run, checkpoint_entries)
            if context.get('repair_session'):
                # 当前结果与协议已落盘，才移除对应意图，不推测未知副作用。
                current = load_repair(workspace_for(task))
                current['session']['pending_actions'] = [a for a in current['session']['pending_actions']
                                                          if a['call_id'] != action.call_id]
                save_repair(workspace_for(task), current)
            if tool_result.status == "succeeded":
                run.last_completed_action_index = index
            db.commit()
            if tool_result.status == "succeeded" and stop_when and stop_when():
                return 'SUBMITTED_FOR_TEST' if context.get('require_unit_submission') else result.text
        if refresh_diagnostic is not None:
            # 整批工具完成后才诊断，避免多处修改之间测试半成品；缓存及主动自测避免重复执行。
            context = {**context, 'unit_diagnostic':refresh_diagnostic()}
            if relay:
                # 只有实际版本变化且诊断绑定当前完整版本时才能重建；通过诊断不等于交接。
                current_versions = tools.self_test_versions()
                diagnostic = context['unit_diagnostic']
                if (batch_versions != current_versions and all(value is not None for value in current_versions.values())
                        and diagnostic.get('file_hashes_before') == current_versions
                        and diagnostic.get('file_hashes_after') == current_versions):
                    relay.complete_batch(history, result.request_id, [action.call_id for action in result.actions], diagnostic)
        elif relay and context.get('repair_session'):
            # 只利用模型主动自测结果建立完整批次边界，不自动增加诊断命令。
            diagnostic = tools.self_test
            current_versions = tools.self_test_versions()
            # 查找协议边界只需索引，不为此重复刷新源码正文。
            boundary_end = relay._boundary_end(history, relay.boundaries[-1]) if relay.boundaries else None
            previous_history = history[boundary_end:] if boundary_end is not None else history
            changed = any(e.get('action', {}).get('tool_name') in {'write', 'replace'}
                          and e.get('result', {}).get('status') == 'succeeded'
                          and e.get('repair_versions_before') != e.get('repair_versions_after')
                          for e in previous_history)
            if (changed and diagnostic and diagnostic.get('file_hashes_before') == current_versions
                    and diagnostic.get('file_hashes_after') == current_versions
                    and any(a.tool_name == 'run_unit_tests' for a in result.actions)):
                relay.complete_batch(history, result.request_id, [a.call_id for a in result.actions], diagnostic)
    raise RuntimeError("model_call_limit_exceeded")


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
    from .repair_objectives import record_blocker
    record_blocker(task, reason)
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
    from .repair_runtime import load as load_repair, manifest
    if load_repair(root):
        # 新方式将目标关闭绑定需求、授权及完整产品，不能复用另一版本。
        return manifest(root)
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "product").rglob("*"))
            if path.is_file() and path.suffix in {".html", ".css", ".js", ".cjs", ".mjs", ".py"}}


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
    from .repair_objectives import pending
    if pending(task):
        return False
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


def saved_bug_inspections(tools: ToolRuntime, inspections: list[TraceRecord], current_hashes: dict) -> dict:
    # 从不可变调查 Trace 恢复同路径同版本正文，缺失或损坏的记录不能证明当前内容。
    saved = {}
    for trace in inspections:
        if trace.status != 'succeeded':
            continue
        path = trace.metadata_json['path']
        saved.pop(path, None)
        if trace.metadata_json['sha256'] != current_hashes.get(path):
            continue
        try:
            # 只读取已保存的工具证据，不再调用产品文件 read。
            detail = json.loads(tools._safe_path(trace.detail_path).read_text(encoding='utf-8'))['payload']
            if (not isinstance(detail['content'], str) or detail['path'] != path or detail['sha256'] != current_hashes[path]
                    or sha256_text(detail['content']) != current_hashes[path]):
                continue
            saved[path] = {'content':detail['content'], 'sha256':detail['sha256'],
                           'evidence_ref':trace.detail_path, 'step_run_id':trace.step_run_id}
        except (OSError, ValueError, KeyError, TypeError):
            # 证据不可恢复时保留实际失败状态，不能把旧正文重新标为当前版本。
            continue
    return saved


def bug_planner_protocol_errors(value: object, allowed: list[str], remaining_files: list[str],
                                inspection_refs: dict) -> list[dict]:
    # 给出实际拒绝字段与原因，供一次有界纠错使用，不代替模型选择行动。
    if not isinstance(value, dict):
        return [{'field':'response', 'code':'json_object_required', 'message':'回复必须是一个 JSON 对象。'}]
    errors = []
    action, path = value.get('action'), value.get('path')
    if action not in allowed:
        errors.append({'field':'action', 'code':'action_not_allowed',
                       'message':f'当前阶段只允许 {allowed}；调查额度用尽时不能 inspect。'})
    if not isinstance(value.get('reason'), str) or not value['reason'].strip():
        errors.append({'field':'reason', 'code':'reason_required', 'message':'reason 必须是非空字符串。'})
    if action == 'inspect' and path not in remaining_files:
        reference = inspection_refs.get(path, {}) if isinstance(path, str) else {}
        errors.append({'field':'path', 'code':'inspect_path_not_available',
            'message':('该同版本路径在当前 Run 已调查，不能重复选择；可依据本次恢复的已存正文和当前门禁继续。'
                       if reference.get('matches_current_file') else
                       'path 必须来自 remaining_files；缺失、损坏或过期的调查正文不能作为当前证据。')})
    if action != 'inspect' and path is not None:
        errors.append({'field':'path', 'code':'unexpected_path', 'message':'非 inspect 行动的 path 必须为 null。'})
    if action == 'clarify' and (not isinstance(value.get('clarifying_question'), str)
                              or not value['clarifying_question'].strip()):
        errors.append({'field':'clarifying_question', 'code':'question_required',
                       'message':'clarify 必须给出一个非空的具体问题。'})
    return errors


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
        TraceRecord.task_id == task.id, TraceRecord.type == "bug_planner_inspect")
        .order_by(TraceRecord.sequence)).all()
                   if trace.metadata_json.get("event_id") == event_id]
    candidates = [f"evidence/{name}" for name in ("test-report.md", "verification-report.md")
                  if (root / "evidence" / name).is_file()]
    candidates += sorted(str(path.relative_to(root)) for path in (root / "product").rglob("*")
                         if path.is_file())
    # 精简流程入口需要细节时沿用原 inspect 读取正式文档，不增加工具或额度。
    compact_phase = task.cur_step in {Step.test, Step.start_product, Step.verify_product}
    if compact_phase:
        candidates += [f'docs/{name}' for name in ('product.md', 'architecture.md', 'dev-design.md')
                       if (root / 'docs' / name).is_file()]
    previous_hashes = {**triage.get("inspected_evidence", {}),
                       **{trace.metadata_json["path"]: trace.metadata_json["sha256"]
                          for trace in inspections if trace.status == "succeeded"}}
    current_hashes = {path:hashlib.sha256((root / path).read_bytes()).hexdigest() for path in candidates}
    saved_inspections = saved_bug_inspections(tools, inspections, current_hashes)
    # 跨 Run 允许请求恢复有效旧证据，当前 Run 同版本只提供一次；调查额度仍共用原上限。
    reusable = {path for path, detail in saved_inspections.items()
                if compact_phase and detail['step_run_id'] != run.id}
    remaining_files = [path for path in candidates if previous_hashes.get(path) != current_hashes[path]
                       or path in reusable]
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
    inspected_content = {path:detail['content'] for path, detail in saved_inspections.items()}
    inspection_refs = {trace.metadata_json['path']:{'sha256':trace.metadata_json['sha256'],
        'content_source':'inspection_trace', 'evidence_ref':trace.detail_path,
        'matches_current_file':trace.metadata_json['path'] in saved_inspections,
        'available_for_inspect':trace.metadata_json['path'] in reusable and 'inspect' in allowed}
        for trace in inspections if trace.status == 'succeeded'}
    context = {"approved_documents": {name: (root / "docs" / name).read_text(encoding="utf-8")
                                      for name in ("product.md", "architecture.md", "dev-design.md")
                                      if (root / "docs" / name).is_file()},
               "skipped_design": skipped_design_evidence(task),
               "acceptance_triage": triage, "last_action_result":
               {"step": last_run.step.value, "status": last_run.status.value,
                "error": last_run.error, "output_path": last_run.output_path} if last_run else None,
               "reports": reports, "code_hashes": product_code_hashes(task),
               "inspected_content": inspected_content, "inspection_refs":inspection_refs, "allowed_actions": allowed,
               "remaining_files": remaining_files,
               "remaining_decisions": MAX_BUG_PLANNER_DECISIONS - len(decisions),
               "repair_round": task.repair_round}
    if compact_phase:
        from .repair_objectives import pending as repair_objectives_pending
        # 上次 inspect 后的首个规划接收正文，后续动作依据当前门禁状态及引用。
        last_decision_sequence = max((item.sequence for item in decisions), default=0)
        fresh_paths = {item.metadata_json['path'] for item in inspections
                       if item.sequence > last_decision_sequence and item.status == 'succeeded'}
        context = compact_bug_planner_context(context, fresh_paths)
        context['execution_state'] = {'step':task.cur_step.value, 'result_url':task.result_url,
            'unresolved_objective_ids':[item['id'] for item in repair_objectives_pending(task)],
            'suggested_action':allowed[0], 'user_feedback_role':'original_acceptance_feedback',
            'phase_goal':{Step.test:'运行当前版本全量测试，原始缺陷待后续浏览器与目标审查验证。',
                          Step.start_product:'当前版本测试门禁已通过，启动该版本并检查 HTTP 健康状态。',
                          Step.verify_product:('当前验证与目标门禁已通过，选择 finish 交给用户验收。'
                                               if allowed[0] == 'finish' else
                                               '执行当前版本测试、真实浏览器及原目标独立审查。')}[task.cur_step]}
        last_develop = db.scalar(select(StepRun).where(StepRun.task_id == task.id,
            StepRun.step == Step.develop).order_by(StepRun.id.desc()).limit(1))
        context['execution_state']['development_run'] = ({'id':last_develop.id,
            'status':last_develop.status.value, 'output_path':last_develop.output_path} if last_develop else None)
        # 适用性来自真实版本证据，不用旧报告的成功文字推断当前验证状态。
        hashes = context['code_hashes']
        context['current_evidence'] = {}
        for key, path in (
                ('tested_current', root / 'evidence/bug-tested-code-hashes.json'),
                ('verified_current', root / 'evidence/bug-verified-code-hashes.json')):
            try:
                context['current_evidence'][key] = path.is_file() and json.loads(path.read_text(encoding='utf-8')) == hashes
            except (OSError, ValueError):
                # 不可读的可选摘要不证明版本有效，原正式门禁仍独立核验。
                context['current_evidence'][key] = False
    for attempt in range(2):
        # Planner 只提出行动和证据目标，不接触工具；非法决定最多纠正一次。
        response = model_tool_loop(
            db, task, run,
            load_prompt('bug-action-planner'),
            triage["user_feedback"], context, tools, tool_schemas=[],
            history_key=f"bug_planner_{event_id}_{run.id}_{attempt}", runtime_step=Step.product_docs)
        try:
            value = json.loads(response.strip().removeprefix("```json").removeprefix("```")
                               .removesuffix("```").strip())
        except json.JSONDecodeError:
            value = None
        errors = bug_planner_protocol_errors(value, allowed, remaining_files, inspection_refs)
        if not errors:
            action, path = value['action'], value.get('path')
            safe_record_trace(db, task, run, "bug_planner_decision", "succeeded", "Bug 下一行动",
                              action, {"decision": value, "context": context},
                              {"event_id": event_id, "action": action, "path": path})
            if action == "inspect":
                # 缓存恢复同样保存当前 Run 的调查记录，但不再次执行文件 read 或扩充调查额度。
                if path in reusable:
                    content, digest = saved_inspections[path]['content'], saved_inspections[path]['sha256']
                    source_ref = saved_inspections[path]['evidence_ref']
                else:
                    result = tools.execute(ToolCall(str(uuid.uuid4()), "read", {"path": path}))
                    if result.status != "succeeded" or result.output.get("truncated"):
                        raise RuntimeError("bug_inspection_read_failed")
                    content, digest = result.output['content'], hashlib.sha256((root / path).read_bytes()).hexdigest()
                    source_ref = None
                safe_record_trace(db, task, run, "bug_planner_inspect", "succeeded", "读取 Bug 证据",
                                  path, {"path": path, "content": content, "sha256": digest},
                                  {"event_id": event_id, "path": path, "sha256": digest,
                                   "content_source":"saved_inspection" if source_ref else "current_file",
                                   "reused_from":source_ref})
            elif action == "clarify":
                run.status = StepStatus.waiting_user
                task.status = TaskStatus.waiting_user
                add_message(db, task, "assistant", value["clarifying_question"])
            db.commit()
            return action
        # 具体拒绝原因与有效旧正文一并交回，最多一次纠错，不执行非法决定。
        path = value.get('path') if isinstance(value, dict) else None
        if isinstance(path, str) and path in saved_inspections:
            context['inspected_content'][path] = saved_inspections[path]['content']
            context['inspection_refs'][path]['body_in_context'] = True
        context["protocol_error"] = {"attempt": attempt + 1, "response": response, "errors":errors,
                                     "allowed_actions": allowed, "remaining_files":remaining_files}
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
                        load_prompt('product-gate'),
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
                        load_prompt('product-draft-author', {'target': target}),
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
                        load_prompt('product-draft-reviewer', {'review_target': review_target}),
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
                        load_prompt('product-candidate-author', {'candidate_target': candidate_target}),
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
            load_prompt('product-change-coverage'),
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
                load_prompt('initial-design-planner'),
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
    answer_instruction = (load_prompt('worker-answer-instruction-1754-1') if confirmed_answers else "")
    label = "架构设计" if kind == "architecture" else "Dev Design"
    extra = (load_prompt('worker-extra-1757-1') if kind == 'dev_design' else
             load_prompt('worker-extra-1757-2'))
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
            load_prompt('design-transition-planner', {'revise_action': revise_action, 'label': label, 'reuse_action': reuse_action}),
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
            instructions = (load_prompt('worker-instructions-1854-1', {'label': label, 'draft': draft, 'extra': extra, 'answer_instruction': answer_instruction}))
            input_text = previous_text
            context = {"current_upstream": source_text, "upstream_diff": upstream_diff,
                       "transition_decision": transition, **answer_context}
        else:
            instructions = (load_prompt('worker-instructions-1861-1', {'label': label, 'draft': draft, 'extra': extra, 'answer_instruction': answer_instruction}))
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
                        load_prompt('design-candidate-reviewer', {'review': review}),
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
                        load_prompt('design-final-author', {'label': label, 'formal_version': formal_version, 'answer_instruction': answer_instruction}),
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
    instructions = load_prompt('worker-instructions-2026-1')
    if not design_path.is_file():
        instructions += load_prompt('worker-instructions-2034-1')
    if is_repair:
        instructions += load_prompt('worker-instructions-2036-1')
    elif upstream_changed or non_bug_change:
        instructions += load_prompt('worker-instructions-2041-1')
        safe_record_trace(db, task, run, "transition_decision", "succeeded", "开发影响判断",
                          "revise", {"previous_lineage": lineage,
                                     "current_dev_design_hash": dev_design_hash},
                          {"action": "revise", "reason": "implementation_lineage_mismatch"})
    # 等模型完成所有设计文件后再校验，避免入口齐全时截断模块生成。
    stop_when = None
    current_product_files = {
        str(path.relative_to(root)): path.read_text(encoding="utf-8", errors="replace")
        for path in product_files(root)
    } if is_revision else {}
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
                    "current_product_files": current_product_files,
                    "acceptance_triage": acceptance_triage,
                    "previous_product": previous_product,
                    "previous_dev_design": previous_dev_design,
                    "dev_design_diff": dev_design_diff,
                    "previous_dev_design_hash": lineage.get("dev_design_hash"),
                    "repair_round": task.repair_round}
    from .repair_objectives import capture, pending
    if acceptance_triage.get("event_id"):
        capture(root, acceptance_triage)
    base_context["unresolved_acceptance_objectives"] = pending(task)
    repair_feedback = None
    # 旧报告无法证明生成时的代码版本，不把当前哈希伪装成历史验证快照。
    failure_evidence_source = {"step_run_id": previous_failed.id if previous_failed else None,
                               "source": "step_error" if failure_source == Step.start_product.value else str(report_path.relative_to(root)),
                               "file_snapshot": "unknown", "sha256": content_hash(latest_failure_report)}
    max_attempts = MAX_NO_CHANGE_CORRECTIONS + 1 if is_revision else 1
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
            base_context = {**base_context, "latest_failure_report": latest_failure_report,
                            "current_product_files": {
                                str(path.relative_to(root)): content.decode("utf-8", errors="replace")
                                for path, content in attempt_before.items()}}
        model_tool_loop(db, task, run, instructions, product,
                        {**base_context, "repair_feedback": repair_feedback}, tools,
                        stop_when=stop_when, tool_schemas=repair_tools)
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
                validation, command = run_product_browser_validation(db, task, run, tools)
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
            "message": "你已结束本轮返修，但实际产品文件均未产生内容变化。模型文本中的已修改声明不算修改。请根据失败报告重新诊断，并通过 write 实际修改相关文件。",
            "failure_source_step": failure_source,
            "latest_failure_report": latest_failure_report,
            "unchanged_file_sha256": hashes,
        }
        safe_record_trace(db, task, run, "repair_no_change", "failed", "返修未产生文件变化",
                          f"第 {repair_attempt} 次无变化，反馈模型重试",
                          repair_feedback,
                          {"attempt": repair_attempt, "failure_source_step": failure_source})
        db.commit()
        if repair_attempt == max_attempts:
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


def start_product_service(db: Session, task: Task, run: StepRun, tools: ToolRuntime) -> dict:
    # 启动并核对实际服务，返回事实，由调用方保存证据并推进任务。
    from .sandbox import for_workspace
    isolated = for_workspace(tools.workspace)
    if isolated is not None:
        # 新模式只启动可信快照预览，不在宿主运行生成服务脚本。
        service = isolated.start_preview(task)
        safe_record_trace(db, task, run, "validation", "succeeded", "Sandbox 服务与预览健康检查通过",
                          service["url"], service)
        return service
    port = free_port()
    # 在服务子进程中扩大监听队列，避免模块并发建连填满标准库默认的五个位置。
    bootstrap = ("import runpy,socketserver,sys;"
                 "socketserver.TCPServer.request_queue_size=128;"
                 f"sys.argv=['http.server','{port}','--bind','127.0.0.1'];"
                 "runpy.run_module('http.server',run_name='__main__')")
    command = f'python -c "{bootstrap}"'
    result = execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec", {"action": "start", "command": command}))
    if result.status != "succeeded" or not result.output.get("running"):
        raise RuntimeError(result.error or "product_start_failed")
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
        raise RuntimeError(str(exc)) from exc
    safe_record_trace(db, task, run, "validation", "succeeded", "健康检查通过", url,
                      {"url": url, "process_id": result.output["process_id"]})
    return {"url": url, "port": port, "process_id": result.output["process_id"], "command": command}


def handle_start(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 旧入口沿用原启动失败返修策略，新方式可以先保存启动证据再投影。
    try:
        service = start_product_service(db, task, run, tools)
    except RuntimeError as exc:
        fail_or_repair(db, task, run, str(exc))
        return
    task.port = service["port"]
    task.process_id = service["process_id"]
    task.process_command = service["command"]
    task.result_url = service["url"]
    run.output_path = "product/index.html"
    finish_step(db, task, run, Step.verify_product)


def verify_script_preflight(path: Path) -> str | None:
    """在浏览器运行前识别可确定的脚本调用契约与错误断言。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return f"verification_script_syntax_error:{exc.lineno}:{exc.msg}"
    # 使用 argparse 时必须能接收 Worker 传入的位置 URL；直接读取 sys.argv 的脚本不受此检查限制。
    nodes = list(ast.walk(tree))
    parser = next((node for node in nodes if isinstance(node, ast.Call)
                   and ((isinstance(node.func, ast.Attribute) and node.func.attr == "ArgumentParser")
                        or (isinstance(node.func, ast.Name) and node.func.id == "ArgumentParser"))), None)
    arguments = [node for node in nodes if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"]
    uses_argv = any(isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "sys" and node.attr == "argv" for node in nodes)
    # 验证脚本只能访问 Worker 已启动的产品 URL，不能自行开服务绕过传入地址。
    own_server = next((node for node in nodes if isinstance(node, ast.Call)
                       and ((isinstance(node.func, ast.Name) and node.func.id in
                             {"HTTPServer", "ThreadingHTTPServer", "TCPServer"})
                            or (isinstance(node.func, ast.Attribute) and node.func.attr in
                                {"HTTPServer", "ThreadingHTTPServer", "TCPServer"}))), None)
    if own_server:
        return f"verification_script_starts_server:{own_server.lineno}"
    if (parser and arguments and not uses_argv
            and all(node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str) for node in arguments)
            and not any(not node.args[0].value.startswith("-") for node in arguments)):
        return f"verification_script_positional_url_required:{parser.lineno}"
    # sorted(实际值) 不可能等于未排序的固定字符串列表，先反馈脚本错误，避免误修产品。
    for node in nodes:
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
            continue
        for actual, expected in ((node.left, node.comparators[0]),
                                 (node.comparators[0], node.left)):
            if (not isinstance(actual, ast.Call) or not isinstance(actual.func, ast.Name)
                    or actual.func.id != "sorted" or len(actual.args) != 1 or actual.keywords
                    or not isinstance(expected, (ast.List, ast.Tuple))):
                continue
            values = [item.value for item in expected.elts
                      if isinstance(item, ast.Constant) and isinstance(item.value, str)]
            if len(values) == len(expected.elts) and values != sorted(values):
                return f"verification_script_expected_order_invalid:{node.lineno}:{values!r}"
    return None


def run_product_browser_validation(db: Session, task: Task, run: StepRun,
                                   tools: ToolRuntime) -> tuple[ToolResult, str]:
    """先校验生成脚本的确定性错误，再调用受控 Python 执行真实浏览器验证。"""
    command = f"{shlex.quote(sys.executable)} verify_product.py {shlex.quote(task.result_url or '')}"
    issue = verify_script_preflight(workspace_for(task) / "product/verify_product.py")
    if issue:
        # 预检失败只说明验证脚本有错，不把尚未执行的浏览器检查记为产品失败。
        safe_record_trace(db, task, run, "verification_script", "failed", "验证脚本预检失败",
                          issue, {"path": "product/verify_product.py", "error": issue})
        return ToolResult(str(uuid.uuid4()), "verify_script_preflight", "failed",
                          {"exit_code": 1, "stdout": "", "stderr": issue}, issue), command
    return execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
                       {"action": "run", "command": command})), command


def browser_validation_passed(result: ToolResult) -> bool:
    """只有真实浏览器脚本成功执行且未报告跳过时才允许通过。"""
    output = result.output.get("stdout", "") + result.output.get("stderr", "")
    return (result.status == "succeeded" and result.output.get("exit_code") == 0
            and "[skip]" not in output.lower())


def handle_verify(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 在真实浏览器中验证生成软件并保存结果。
    if not check_product_entry(db, task, run):
        return
    # 保存实际验证前的代码版本，原始缺陷不能由另一版本的运行结果关闭。
    verification_hashes = product_code_hashes(task)
    unit = execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
                                 {"action": "run", "command": "node --test"}))
    browser, _ = run_product_browser_validation(db, task, run, tools)
    unit_passed = unit.status == "succeeded" and unit.output.get("exit_code") == 0
    browser_passed = browser_validation_passed(browser)
    passed = unit_passed and browser_passed
    report = workspace_for(task) / "evidence" / "verification-report.md"
    report.write_text("# 验证报告\n\n## JavaScript 单元测试\n\n```json\n" +
                      json.dumps(unit.__dict__, ensure_ascii=False, indent=2) +
                      "\n```\n\n## Playwright 浏览器验证\n\n```json\n" +
                      json.dumps(browser.__dict__, ensure_ascii=False, indent=2) + "\n```\n",
                      encoding="utf-8")
    coverage_error = None
    if passed:
        from .acceptance_standard import load_standard, review_coverage
        standard = load_standard(workspace_for(task))
        if standard:
            # 浏览器脚本或产品代码在返修中变化后，旧覆盖审查不能再次证明当前版本。
            coverage_path = workspace_for(task) / "evidence/acceptance-coverage-review.json"
            old = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.is_file() else {}
            if (old.get("product_hash") != standard["product_hash"]
                    or old.get("product_code_hashes") != product_code_hashes(task)
                    or old.get("review", {}).get("complete") is not True):
                from .slice_workflow import _progress, load_delivery_plan
                root = workspace_for(task)
                progress = _progress(root, load_delivery_plan(root))
                completed = [entry for entry in progress["slices"] if entry.get("status") == "passed"]
                coverage = review_coverage(db, task, run, tools, standard, completed)
                if not coverage["complete"]:
                    passed = False
                    coverage_error = "acceptance_coverage_missing"
    if passed:
        # 原始验收复现须由实际浏览器脚本验证，普通验证成功不能替代。
        from .repair_objectives import pending, verify as verify_repair_objectives
        if pending(task) and verification_hashes != product_code_hashes(task):
            passed = False
            coverage_error = "repair_objective_validation_code_changed"
        elif not verify_repair_objectives(db, task, run, tools, browser):
            passed = False
            coverage_error = "repair_objectives_unresolved"
    safe_record_trace(db, task, run, "validation", "succeeded" if passed else "failed",
                      "真实产品验证", "单元测试、浏览器与行为覆盖均通过" if passed else "产品验证未通过",
                      {"unit_passed": unit_passed, "browser_passed": browser_passed,
                       "coverage_error": coverage_error,
                       "unit": unit.__dict__, "browser": browser.__dict__})
    if not passed:
        fail_or_repair(db, task, run, coverage_error or browser.error or browser.output.get("stderr") or "verification_failed")
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
    """有界调查正式文件及产品片段，保留范围后决定验收反馈处理阶段。"""
    # 同一个 Planner 按反馈连续调查证据，然后直接选择文档、代码或澄清行动。
    root = workspace_for(task)
    inspected: dict = {}
    tools = ToolRuntime(root)
    protocol_error = None
    invalid_count = 0
    for index in range(6):
        remaining = [path for path in candidates if path not in inspected
                     or not inspected[path].get("complete", True)]
        if len(inspected) >= 3:
            remaining = [path for path in remaining if path in inspected]
        allowed = ["clarify", *ACCEPTANCE_ACTIONS]
        if remaining:
            allowed.insert(0, "inspect")
        # Planner 不接触工具；所有正式文档和已读取证据在下一轮规划中继续可见。
        response = model_tool_loop(
            db, task, run,
            load_prompt('acceptance-action-planner'),
            feedback, {"approved_documents": approved_documents, "remaining_files": remaining,
                       "inspection_contract": "inspect 支持 start_line、end_line，默认先读 200 行；证据标注范围与 next_line，禁止重复读已调查范围。",
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
        if action == "inspect" and path in remaining and (path in inspected or len(inspected) < 3):
            # 工具再次解析目标路径，拒绝清单外文件和符号链接逃逸。
            prior = inspected.get(path)
            start = decision.get("start_line", prior["next_line"] if prior else 1)
            end = decision.get("end_line", start + 199 if type(start) is int else None)
            # 分段调查只允许未读范围，避免大文件截断后重复读取全文。
            if (type(start) is not int or type(end) is not int or start < 1 or end < start
                    or end - start >= 200 or (prior and (start < prior["next_line"]
                    or [start, end] in prior["requested_ranges"]))):
                protocol_error = {"message": "范围无效或重复；从 next_line 开始，最多读取 200 行。"}
                continue
            result = tools.execute(ToolCall(call_id=str(uuid.uuid4()), tool_name="read",
                                           parameters={"path": path, "start_line": start, "end_line": end}))
            if result.status != "succeeded":
                safe_record_trace(db, task, run, "acceptance_inspect", "failed", "证据读取失败",
                                  str(path), {"error": result.error, "truncated": result.output.get("truncated")})
                protocol_error = {"message": "证据读取失败，请选择其他证据。", "error": result.error}
                continue
            digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
            output = result.output
            content = output["content"]
            # 字节截断时仅登记完整行，未返回的行仍需后续调查。
            if output["truncated"]:
                content = content[:content.rfind("\n") + 1] if "\n" in content else ""
            next_line = start + len(content.splitlines())
            fragments = (prior["fragments"] if prior else []) + [
                {"start_line": start, "end_line": next_line - 1,
                 "content": content, "truncated": output["truncated"]}]
            inspected[path] = {"content": "\n".join(item["content"] for item in fragments),
                               "sha256": digest, "fragments": fragments,
                               "requested_ranges": (prior["requested_ranges"] if prior else []) + [[start, end]],
                               "total_lines": output["total_lines"], "next_line": next_line,
                               "complete": (not output["truncated"] and next_line > output["total_lines"]
                                            and fragments[0]["start_line"] == 1
                                            and all(a["end_line"] + 1 == b["start_line"]
                                                    for a, b in zip(fragments, fragments[1:])))}
            protocol_error = {"message": "证据为标注范围的片段；inspect 可提供 start_line、end_line；从 next_line 继续，最多 200 行。"}
            safe_record_trace(db, task, run, "acceptance_inspect", "succeeded", "读取验收证据",
                              path, {"path": path, "sha256": digest, "fragment": fragments[-1]},
                              {"path": path, "sha256": digest, "start_line": start,
                               "end_line": next_line - 1, "truncated": output["truncated"]})
            continue
        # 文档变更可依正式文件直接判断；实现缺陷必须有实际读取的产品代码证据。
        code_inspected = any(path.startswith("product/") and Path(path).suffix in {
            ".html", ".css", ".js", ".py"} and inspected[path]["content"] for path in inspected)
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
        load_prompt('acceptance-consistency-validator'),
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
    # 在后续验证覆盖最新报告前独立保存原始验收目标。
    from .repair_objectives import capture
    capture(root, result)
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
    if event.type == "repair_request":
        from .repair_runtime import initialize
        try:
            initialize(task, event)
        except (ValueError, RuntimeError) as exc:
            reject_event(event, str(exc))
            return
        # 新尝试保留原始目标并直接交连续执行会话，不再先调用选卡 Planner。
        from .repair_objectives import capture
        capture(workspace_for(task), {'event_id': event.id, 'classification': 'implementation_defect',
                                    'user_feedback': data['feedback']})
        add_message(db, task, 'user', data['feedback'])
        task.status, task.cur_step = TaskStatus.running, Step.develop
    elif event.type == "document_approval":
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
        from .repair_runtime import load as load_repair, current_submission, save as save_repair
        repair = load_repair(workspace_for(task))
        if repair:
            if repair.get("state") == "accepted" and repair.get("acceptance_event_id") == event.id:
                # 仅修复同一已保存验收事件的数据库投影，不重新批准另一个事件。
                task.status = TaskStatus.succeeded
                event.status = EventStatus.consumed
                event.processed_at = datetime.utcnow()
                return
            if (data.get("submission_id") != repair.get("submission_id")
                    or data.get("expected_task_version") != task.version
                    or repair.get("state") != "awaiting_acceptance"):
                reject_event(event, "repair_acceptance_submission_mismatch")
                return
            try:
                current_submission(workspace_for(task), repair)
            except RuntimeError as exc:
                reject_event(event, str(exc))
                return
            if not data.get("approved"):
                # 新反馈须通过明确的新返修尝试与预算授权，不沿旧事件隐式续费。
                reject_event(event, "repair_feedback_requires_new_request")
                return
            if repair.get('validation_policy') == 'tests_and_browser':
                # 浏览器通过只进入待验收；用户明确批准后才关闭当前原始目标。
                from .repair_objectives import accept_by_user
                accept_by_user(task, event.id)
            repair["state"] = "accepted"
            repair["acceptance_event_id"] = event.id
            save_repair(workspace_for(task), repair)
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
        from .repair_session import answer as answer_repair
        try:
            answered = answer_repair(task, data)
        except (ValueError, RuntimeError) as exc:
            reject_event(event, str(exc))
            return
        add_message(db, task, "user", str(data.get("content", "")))
        if task.status == TaskStatus.waiting_user and not answered:
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
    from .repair_runtime import load as load_repair, pipeline, stop as stop_repair, STEPS as REPAIR_STEPS
    repair = None
    repair_error = None
    try:
        repair = load_repair(workspace_for(task))
    except Exception as exc:
        repair_error = exc
    if repair and repair['state'] == 'waiting_decision':
        # 问题先落盘而 Task 投影未提交时，仅恢复等待，不进入验证或重复调用模型。
        task.status, task.cur_step = TaskStatus.waiting_user, Step.develop
        db.commit()
        return True
    if repair and repair["state"] in REPAIR_STEPS and repair["state"] != "executing":
        # 先修复阶段投影再创建 Run，使恢复后的审计归属真实阶段。
        task.cur_step = REPAIR_STEPS[repair["state"]]
    elif repair and repair["state"] == "executing" and repair.get("last_failure"):
        task.cur_step = Step.develop
    task.status = TaskStatus.running
    task.version += 1
    db.commit()
    tools = ToolRuntime(workspace_for(task))
    run = create_step_run(db, task)
    db.commit()
    try:
        if repair_error:
            raise repair_error
        if repair and repair["state"] == "stopped":
            # 持久停止先于数据库提交时，恢复原停止原因，不重新执行阶段。
            stop_repair(db, task, run, repair["stop_reason"])
            return True
        if repair and repair["state"] == "accepted":
            task.status = TaskStatus.succeeded
            run.status = StepStatus.succeeded
            run.finished_at = datetime.utcnow()
            db.commit()
            return True
        if repair and repair["state"] == "executing" and task.cur_step in {
                Step.test, Step.start_product, Step.verify_product}:
            # 旧开发分支尚未接入新提交时明确停止，不能绕过冻结版本验证。
            stop_repair(db, task, run, "repair_submission_required")
            return True
        if repair and repair['state'] == 'executing':
            # 本任务主会话独立于旧切片与阶段会话，显式提交后才进入固定收尾。
            from .repair_session import execute as execute_repair
            execute_repair(db, task, run)
            return True
        if repair and repair["state"] != "executing":
            # 新方式由冻结提交控制固定阶段，无中间 Planner 或模型 finish。
            pipeline(db, task, run, tools)
            return True
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
        if not repair and active_bug_triage(task) and task.cur_step in {
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
    except BudgetExceeded:
        # 新模式以独立预算原因停止，旧模型协议和失败记录保持。
        stop_repair(db, task, run, "budget_exhausted")
    except Exception as exc:
        if repair:
            stop_repair(db, task, run, str(exc))
            return True
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
