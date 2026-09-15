import json
import difflib
import hashlib
import shlex
import shutil
import socket
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import Event, EventStatus, Message, Step, StepRun, StepStatus, Task, TaskStatus
from .contracts import ModelRequest, ToolCall, ToolResult
from .model import ModelProtocolError, create_model_runtime
from .tools import TOOL_SCHEMAS, ToolRuntime
from .tracing import safe_record_trace

NEXT_STEP = {
    Step.architecture_docs: Step.dev_design,
    Step.dev_design: Step.develop,
    Step.develop: Step.test,
    Step.test: Step.start_product,
    Step.start_product: Step.verify_product,
}
MAX_MODEL_CALLS_PER_STEP = 100
MAX_TRANSPORT_ATTEMPTS = 3
MAX_REPAIR_ROUNDS = 3
MAX_NO_CHANGE_CORRECTIONS = 2
MAX_IDENTICAL_TOOL_ACTIONS = 2
MAX_REPAIR_ACTIONS_WITHOUT_WRITE = 5

BASE_INSTRUCTIONS = """你是开发团队模拟器中的执行 Agent。严格完成当前 Step，不改变已确认需求、技术栈或流程。
你只能通过提供的工具读写当前任务工作区；不得访问工作区外资源。文件操作必须使用相对路径。
需要操作文件或运行命令时返回工具调用。所有要求完成且无需工具时才结束。"""


def _action_signature(action: ToolCall) -> str:
    # 把工具动作转换为可比较的稳定签名。
    return json.dumps({"tool_name": action.tool_name, "parameters": action.parameters},
                      ensure_ascii=False, sort_keys=True)


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


def execute_tool(db: Session, task: Task, run: StepRun, tools: ToolRuntime, call: ToolCall):
    # 执行工具并记录调用、结果及写入产物。
    started = datetime.utcnow()
    safe_record_trace(db, task, run, "tool_call", "running", f"调用 {call.tool_name}",
                      str(call.parameters.get("path") or call.parameters.get("command") or call.parameters.get("action", "")),
                      {"call_id": call.call_id, "tool_name": call.tool_name, "parameters": call.parameters},
                      started_at=started)
    # 调用受控工具运行时，随后保存完整结果 Trace。
    result = tools.execute(call)
    finished = datetime.utcnow()
    safe_record_trace(db, task, run, "tool_result", result.status,
                      f"{call.tool_name} 执行{'成功' if result.status == 'succeeded' else '失败'}",
                      result.error or str(result.output.get("path") or result.output.get("exit_code") or ""),
                      {"call_id": call.call_id, "tool_name": call.tool_name,
                       "result": result.__dict__}, started_at=started, finished_at=finished)
    record_written_artifact(db, task, run, call, result)
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


def parse_transition_decision(text: str) -> dict:
    # 解析并校验设计阶段 Transition Planner 的动作。
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        value = {}
    action = value.get("action")
    confidence = value.get("confidence", 0)
    if action not in {"revise", "reuse", "clarify"} or not isinstance(confidence, (int, float)):
        action = "clarify"
        confidence = 0
    if confidence < 0.7:
        action = "clarify"
    return {
        "action": action,
        "reason": str(value.get("reason", "证据不足，无法安全决定下一步")),
        "affected_sections": value.get("affected_sections")
        if isinstance(value.get("affected_sections"), list) else [],
        "preserved_sections": value.get("preserved_sections")
        if isinstance(value.get("preserved_sections"), list) else [],
        "confidence": confidence,
        "clarifying_question": value.get("clarifying_question") or
        "请说明这次修改期望改变哪些行为，以及哪些现有行为必须保持不变。",
    }


def model_tool_loop(db: Session, task: Task, run: StepRun, instructions: str, input_text: str,
                    context: dict, tools: ToolRuntime,
                    stop_when: Callable[[], bool] | None = None,
                    tool_schemas: list[dict] | None = None,
                    history_key: str = "default",
                    runtime_step: Step | None = None) -> str:
    # 在预算内循环调用模型、执行工具并保存过程证据。
    checkpoint = Path(run.checkpoint_path) if run.checkpoint_path else None
    checkpoint_entries: list[dict] = []
    history: list[dict] = []
    # 恢复已有检查点中的工具历史，避免 Worker 重启后重复执行。
    if checkpoint and checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if isinstance(saved, list):
            checkpoint_entries = saved
            history = [entry for entry in checkpoint_entries
                       if entry.get("result") and entry.get("history_key", "default") == history_key]
    # 根据阶段选择主 Provider，技术失败时才尝试受控降级。
    primary_runtime = create_model_runtime(db, runtime_step or task.cur_step)
    while run.model_call_count < MAX_MODEL_CALLS_PER_STEP:
        # 每次逻辑模型调用先计入阶段预算并持久化。
        run.model_call_count += 1
        db.commit()
        stream_index = 0
        def on_delta(delta: str) -> None:
            # 将模型流式文本增量写入 Trace。
            nonlocal stream_index
            stream_index += 1
            safe_record_trace(db, task, run, "model_stream_delta", "running", "模型流式回答",
                              delta[:120], {"request_id": request.request_id, "delta": delta,
                                           "index": stream_index},
                              {"history_key": history_key, "request_id": request.request_id,
                               "index": stream_index, "delta": delta})
            db.commit()
        # 把当前上下文和已执行工具结果送回模型续写。
        request = ModelRequest(instructions=f"{BASE_INSTRUCTIONS}\n\n{instructions}", input=input_text,
                               context={**context, "tool_history": history},
                               tools=TOOL_SCHEMAS if tool_schemas is None else tool_schemas,
                               request_id=str(uuid.uuid4()), on_delta=on_delta)
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
                               "fallback": provider_index > 0}, started_at=datetime.utcnow())
            last_transport_error: Exception | None = None
            protocol_error = None
            # 传输重试与逻辑调用分别计数，并记录每次失败。
            for transport_attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
                try:
                    # 执行真实模型请求；协议错误与传输错误采用不同处理路径。
                    result = runtime.call(task.id, request)
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
            return result.text
        # 工具执行前保存待办检查点，便于故障恢复。
        for index, action in enumerate(result.actions, start=run.last_completed_action_index + 1):
            entry = {"history_key": history_key, "model_request_id": result.request_id,
                     "action": action.__dict__}
            entries = checkpoint_entries + [entry]
            save_checkpoint(run, entries)
            signature = _action_signature(action)
            repeated = _recent_action_count(checkpoint_entries, history_key, signature)
            repair_without_write = (context.get("repair_round", 0) > 0
                                    and action.tool_name != "write"
                                    and _repair_actions_without_write(checkpoint_entries, history_key)
                                    >= MAX_REPAIR_ACTIONS_WITHOUT_WRITE)
            # 阻止连续重复动作和返修中无写入循环。
            if repeated >= MAX_IDENTICAL_TOOL_ACTIONS or repair_without_write:
                # 阻止连续重复动作和返修中无写入循环。
                code = "repeated_tool_action" if repeated >= MAX_IDENTICAL_TOOL_ACTIONS else "repair_tool_loop_no_write"
                tool_result = ToolResult(action.call_id, action.tool_name, "failed", {}, code)
                safe_record_trace(db, task, run, "tool_guard", "failed", "阻止无效工具循环", code,
                                  {"action": action.__dict__, "reason": code},
                                  {"history_key": history_key, "reason": code})
            else:
                # 受控工具执行后记录调用、结果和文件产物。
                tool_result = execute_tool(db, task, run, tools, action)
            entry["result"] = tool_result.__dict__
            history.append(entry)
            checkpoint_entries.append(entry)
            save_checkpoint(run, checkpoint_entries)
            if tool_result.status == "succeeded":
                run.last_completed_action_index = index
            db.commit()
            if tool_result.status == "succeeded" and stop_when and stop_when():
                return result.text
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
                   ], "unpaired_user_requests": user_messages,
                   "current_product": current_product,
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
                        {"user_messages": user_messages, "previous_product": previous_text,
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
                        {"review": review_text, "user_messages": user_messages,
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
                             "user_messages": user_messages}, tools, tool_schemas=[],
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


def handle_reviewed_doc(db: Session, task: Task, run: StepRun, tools: ToolRuntime, kind: str):
    # 处理架构或 Dev Design 的规划、评审和正式化。
    root = workspace_for(task)
    source = "docs/product.md" if kind == "architecture" else "docs/architecture.md"
    target = "docs/architecture.md" if kind == "architecture" else "docs/dev-design.md"
    revision = run.attempt > 1
    version_suffix = f"-v{run.attempt}" if revision else ""
    draft = target.replace(".md", f"{version_suffix}-draft.md")
    review = target.replace(".md", f"{version_suffix}-review.md")
    formal_version = target.replace(".md", f"-v{run.attempt}.md")
    previous_formal_version = target.replace(".md", f"-v{run.attempt - 1}.md")
    source_text = (root / source).read_text(encoding="utf-8")
    label = "架构设计" if kind == "architecture" else "Dev Design"
    extra = "固定单模块，并明确接口、数据、状态、流程和失败处理。" if kind == "dev_design" else ""
    if not revision and (root / target).is_file():
        # 首版正式文件已经存在时补存版本快照并跳过重复生成。
        if not (root / formal_version).is_file():
            atomic_copy(root / target, root / formal_version)
        run.input_path = source
        run.output_path = target
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
        # 由 Transition Planner 判断下游文档修订、复用或澄清。
        decision_text = model_tool_loop(
            db, task, run,
            f"""你是 {label} Transition Planner，只判断现有{label}是否受本轮上游变化影响，不写文件。
只返回 JSON：action 只能是 revise、reuse、clarify；reason；affected_sections；preserved_sections；confidence（0 到 1）；clarifying_question。
若需修改，必须以旧{label}为基线局部演进；若确认所有上游变化均不影响{label}才返回 reuse；证据不足返回 clarify。""",
            upstream_diff,
            {"previous_upstream": previous_upstream_text, "current_upstream": source_text,
             "upstream_diff": upstream_diff, "previous_artifact": previous_text,
             "acceptance_triage": acceptance_triage},
            tools, tool_schemas=[], history_key=f"{kind}_transition")
        # 程序校验 Planner 的动作和置信度，低置信度转为澄清。
        transition = parse_transition_decision(decision_text)
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
                          {"action": transition["action"], "confidence": transition["confidence"],
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
            finish_step(db, task, run, NEXT_STEP[task.cur_step])
            return

    if not (root / draft).is_file():
        # 修订以旧正式文档为基线；首次生成直接使用当前正式上游。
        if revision:
            instructions = (f"以旧{label}为唯一基线，根据上游差异和影响判断进行局部修订，只写入 {draft}，"
                            f"write 必须使用 overwrite=false。不得重写 preserved_sections，不得引入无上游依据的变化。{extra}")
            input_text = previous_text
            context = {"current_upstream": source_text, "upstream_diff": upstream_diff,
                       "transition_decision": transition}
        else:
            instructions = f"根据正式上游文档生成{label}候选，只写入 {draft}；该文件不存在，必须使用 overwrite=false。{extra}"
            input_text = source_text
            context = {}
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
                                     "upstream_diff": upstream_diff, "transition_decision": transition}, tools,
                        stop_when=lambda: (root / review).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key=f"{kind}_review")
    if not (root / review).is_file():
        raise RuntimeError(f"{kind}_review_missing")
    review_text = (root / review).read_text(encoding="utf-8")
    if not (root / formal_version).is_file():
        # 把评审意见并入正式版本，再同步当前有效文档。
        model_tool_loop(db, task, run,
                        f"根据候选与独立评审生成正式{label}，只写入 {formal_version}，不得改变上游需求；write 必须使用 overwrite=false。",
                        draft_text, {"review": review_text, "upstream": source_text,
                                     "previous_artifact": previous_text,
                                     "transition_decision": transition}, tools,
                        stop_when=lambda: (root / formal_version).is_file(),
                        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "write"],
                        history_key=f"{kind}_formal")
    if not (root / formal_version).is_file():
        raise RuntimeError(f"{kind}_formal_missing")
    atomic_copy(root / formal_version, root / target)
    run.input_path = source
    run.output_path = formal_version
    finish_step(db, task, run, NEXT_STEP[task.cur_step])


def handle_develop(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 根据当前设计开发或返修生成软件并核对实现血缘。
    root = workspace_for(task)
    dev_design = (root / "docs" / "dev-design.md").read_text(encoding="utf-8")
    product = (root / "docs" / "product.md").read_text(encoding="utf-8")
    existing = [str(path.relative_to(root)) for path in (root / "product").rglob("*") if path.is_file()]
    required = ["index.html", "styles.css", "app.js", "calculator.test.js", "verify_product.py", "implementation.md"]
    is_repair = task.repair_round > 0
    required_paths = [root / "product" / name for name in required]
    lineage_path = root / "evidence" / "implementation-lineage.json"
    lineage = json.loads(lineage_path.read_text(encoding="utf-8")) if lineage_path.is_file() else {}
    dev_design_hash = content_hash(dev_design)
    upstream_changed = (all(path.is_file() for path in required_paths)
                        and lineage.get("dev_design_hash") != dev_design_hash)
    # 文件齐全也要核对设计血缘；上游设计变化时仍必须增量修改。
    is_revision = is_repair or upstream_changed
    if not is_revision and all(path.is_file() for path in required_paths):
        run.output_path = "product/implementation.md"
        finish_step(db, task, run, Step.test)
        return
    instructions = """实现固定的原生 HTML、CSS、JavaScript 单模块软件。先在 text 中给出简短计划，再用 write 创建或覆盖文件。
write/read 的路径相对任务工作区，不是 product 工作目录。必须生成以下精确路径：product/index.html、product/styles.css、product/app.js、product/calculator.test.js、product/verify_product.py、product/implementation.md。
不存在的文件必须使用 overwrite=false；只有 existing_product_files 明确列出的已有文件才使用 overwrite=true。不要把文件写到工作区根目录。
优先确保六个必需文件全部存在，再使用 exec 调试；不要在必需文件未齐时反复运行测试或临时诊断命令。正式测试和失败返修由后续 test Step 负责。
calculator.test.js 使用 Node 内置测试框架；verify_product.py 使用 Python Playwright 验证真实浏览器中的加减乘除、异常输入和错误后恢复。
可使用 exec 执行 node --test calculator.test.js。不得引入生成产品依赖。"""
    if is_repair:
        instructions += """
这是失败后的返修，不是首次生成。正式 Dev Design、失败来源、对应的完整失败报告和全部当前产品文件内容已经完整放在 context 中；不要读取文件，直接逐项判断失败来自实现、测试还是两者。测试期望与 Dev Design 冲突时修测试，实现偏离时修实现。
必须优先解决 failure_source_step 指向的失败：若为 verify_product，重点检查 Playwright 输出、verify_product.py 是否使用系统传入的 HTTP URL，以及浏览器脚本是否真实加载；不得只运行 Node 测试后宣称完成。
至少使用 overwrite=true 实际修改一个 existing_product_files 中的文件。可以用 exec 运行 Node 测试，但不要查找、安装或尝试切换 Python／Playwright 环境；系统会在你结束本轮后使用受控 Python 自动复跑原失败验证。完成必要写入和 Node 测试后立即结束，不得因为六个文件已经存在就宣称完成。"""
    elif upstream_changed:
        instructions += """
这是上游需求或设计变化后的增量开发。当前产品文件基于旧 Dev Design；必须比较 previous_dev_design 与当前 dev_design，以现有代码为基线，只修改受差异影响的代码和测试，不得推倒重写无关部分。
至少使用 overwrite=true 修改一个 existing_product_files 中的文件，并用 exec 运行更新后的相关测试。不得因为六个文件已经存在就宣称完成。"""
        safe_record_trace(db, task, run, "transition_decision", "succeeded", "开发影响判断",
                          "revise", {"previous_lineage": lineage,
                                     "current_dev_design_hash": dev_design_hash},
                          {"action": "revise", "reason": "implementation_lineage_mismatch"})
    stop_when = None if is_revision else lambda: all(path.is_file() for path in required_paths)
    current_product_files = {
        str(path.relative_to(root)): path.read_text(encoding="utf-8", errors="replace")
        for path in required_paths if path.is_file()
    } if is_revision else {}
    versioned_designs = sorted((root / "docs").glob("dev-design-v*.md"))
    previous_dev_design = versioned_designs[-2].read_text(encoding="utf-8") if len(versioned_designs) >= 2 else ""
    dev_design_diff = unified_text_diff(previous_dev_design, dev_design,
                                        versioned_designs[-2].name if len(versioned_designs) >= 2 else "previous-missing",
                                        "dev-design.md")
    triage_files = sorted((root / "evidence").glob("acceptance-triage-*.json"))
    acceptance_triage = json.loads(triage_files[-1].read_text(encoding="utf-8")) if triage_files else {}
    repair_tools = [schema for schema in TOOL_SCHEMAS
                    if schema["function"]["name"] in {"write", "exec"}] if is_revision else None
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
                    "dev_design": dev_design, "existing_product_files": existing,
                    "current_product_files": current_product_files,
                    "acceptance_triage": acceptance_triage,
                    "previous_dev_design": previous_dev_design,
                    "dev_design_diff": dev_design_diff,
                    "previous_dev_design_hash": lineage.get("dev_design_hash"),
                    "repair_round": task.repair_round}
    repair_feedback = None
    max_attempts = MAX_NO_CHANGE_CORRECTIONS + 1 if is_revision else 1
    for repair_attempt in range(1, max_attempts + 1):
        attempt_before = {path: path.read_bytes() for path in required_paths if path.is_file()}
        model_tool_loop(db, task, run, instructions, product,
                        {**base_context, "repair_feedback": repair_feedback}, tools,
                        stop_when=stop_when, tool_schemas=repair_tools)
        missing = [name for name, path in zip(required, required_paths) if not path.is_file()]
        if missing:
            raise RuntimeError(f"implementation_files_missing:{','.join(missing)}")
        changed = not is_revision or any(attempt_before.get(path) != path.read_bytes() for path in required_paths)
        if changed and is_repair and failure_source in {Step.test.value, Step.verify_product.value}:
            if failure_source == Step.verify_product.value and task.result_url:
                command = f"{shlex.quote(sys.executable)} verify_product.py {shlex.quote(task.result_url)}"
            else:
                command = "node --test calculator.test.js"
            validation = execute_tool(db, task, run, tools, ToolCall(
                str(uuid.uuid4()), "exec", {"action": "run", "command": command}))
            validation_passed = (validation.status == "succeeded"
                                 and validation.output.get("exit_code") == 0
                                 and "[SKIP]" not in validation.output.get("stdout", ""))
            if validation_passed:
                break
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
                  for path in required_paths}
        repair_feedback = {
            "attempt": repair_attempt,
            "message": "你已结束本轮返修，但六个必需文件均未产生实际内容变化。模型文本中的已修改声明不算修改。请根据失败报告重新诊断，并通过 write 实际修改相关文件。",
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
            raise RuntimeError("repair_made_no_changes")
    # 更新实现所依据的 Dev Design 哈希与血缘。
    write_json_atomic(lineage_path, {"dev_design_hash": dev_design_hash,
                                    "develop_attempt": run.attempt,
                                    "product_hash": content_hash(product)})
    run.output_path = "product/implementation.md"
    finish_step(db, task, run, Step.test)


def handle_test(db: Session, task: Task, run: StepRun, tools: ToolRuntime):
    # 运行生成软件测试并据结果推进或返修。
    result = execute_tool(db, task, run, tools, ToolCall(call_id=str(uuid.uuid4()), tool_name="exec",
                                   parameters={"action": "run", "command": "node --test calculator.test.js"}))
    report = workspace_for(task) / "evidence" / "test-report.md"
    report.write_text("# 测试报告\n\n```text\n" + json.dumps(result.__dict__, ensure_ascii=False, indent=2) + "\n```\n",
                      encoding="utf-8")
    run.output_path = "evidence/test-report.md"
    if result.status == "succeeded" and result.output.get("exit_code") == 0:
        safe_record_trace(db, task, run, "validation", "succeeded", "单元测试通过",
                          "node --test calculator.test.js 返回 0", result.__dict__)
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
    unit = execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), "exec",
                                 {"action": "run", "command": "node --test calculator.test.js"}))
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
    report = workspace_for(task) / "evidence" / "verification-report.md"
    report.write_text("# 验证报告\n\n## JavaScript 单元测试\n\n```json\n" +
                      json.dumps(unit.__dict__, ensure_ascii=False, indent=2) +
                      "\n```\n\n## Playwright 浏览器验证\n\n```json\n" +
                      json.dumps(browser.__dict__, ensure_ascii=False, indent=2) + "\n```\n",
                      encoding="utf-8")
    if not passed:
        fail_or_repair(db, task, run, browser.error or browser.output.get("stderr") or "verification_failed")
        return
    readme = workspace_for(task) / "product" / "README.md"
    readme.write_text(f"# 生成的软件\n\n访问地址：{task.result_url}\n\n启动命令：`{task.process_command}`\n",
                      encoding="utf-8")
    run.output_path = "evidence/verification-report.md"
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


TRIAGE_TARGETS = {
    "requirement_change": Step.product_docs,
    "architecture_defect": Step.architecture_docs,
    "dev_design_defect": Step.dev_design,
    "implementation_defect": Step.develop,
}


def parse_triage_result(text: str) -> dict:
    # 解析并校验人工验收问题的分类结果。
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        return {"classification": "unclear", "reason": "模型未返回合法 JSON",
                "evidence": [], "changes": [], "confidence": 0,
                "clarifying_question": "请补充期望行为、实际行为和复现步骤。"}
    classification = value.get("classification")
    confidence = value.get("confidence", 0)
    if classification not in {*TRIAGE_TARGETS, "unclear"} or not isinstance(confidence, (int, float)):
        classification = "unclear"
    if confidence < 0.7:
        classification = "unclear"
    changes = []
    for item in value.get("changes", []):
        if not isinstance(item, dict):
            continue
        current = item.get("current_behavior")
        expected = item.get("expected_behavior")
        examples = item.get("acceptance_examples")
        if isinstance(current, str) and current.strip() and isinstance(expected, str) and expected.strip() \
                and isinstance(examples, list) and examples and all(isinstance(x, str) and x.strip() for x in examples):
            changes.append({"current_behavior": current.strip(), "expected_behavior": expected.strip(),
                            "acceptance_examples": [x.strip() for x in examples]})
    if classification == "requirement_change" and not changes:
        classification = "unclear"
    return {
        "classification": classification,
        "reason": str(value.get("reason", "证据不足")),
        "evidence": value.get("evidence") if isinstance(value.get("evidence"), list) else [],
        "changes": changes,
        "confidence": confidence,
        "clarifying_question": (value.get("clarifying_question") or
                                 "请补充期望行为、实际行为和复现步骤。")
        if classification == "unclear" else None,
    }


def classify_acceptance_feedback(db: Session, task: Task, event: Event, feedback: str):
    # 使用模型和正式设计证据分类验收反馈。
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
        safe_record_trace(db, task, run, "step", "running", "验收分类开始",
                          f"Event {event.id} 使用独立调用预算",
                          {"event_id": event.id, "attempt": attempt}, started_at=run.started_at)
    inputs = {}
    for name in ("product.md", "architecture.md", "dev-design.md"):
        path = root / "docs" / name
        inputs[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    verification = root / "evidence" / "verification-report.md"
    context = {
        "approved_documents": inputs,
        "product_files": sorted(str(path.relative_to(root)) for path in (root / "product").rglob("*") if path.is_file()),
        "latest_verification_report": verification.read_text(encoding="utf-8") if verification.is_file() else "",
    }
    # 读取正式设计和验证证据，取得验收问题分类建议。
    response = model_tool_loop(
        db, task, run,
        """你负责人工验收问题分流，不修改任何文件，也不解决问题。比较用户反馈与三份正式文档，寻找最早失效产物。用户是在报告当前软件问题，短句可能省略“当前软件”这一主语；必须结合报告问题的对话行为、例子和对比句区分当前行为与期望行为，不得孤立按字面把缺陷描述当成用户要求保留的约束。编号或分条反馈必须逐条解释、逐条形成 changes，再选择所有条目中最早失效的阶段作为总体 classification。
只返回一个 JSON 对象，不要 Markdown：classification 只能是 requirement_change、architecture_defect、dev_design_defect、implementation_defect、unclear；target_step 填建议阶段；reason 简述判断；evidence 列出引用的文档与原文依据；changes 为数组，每项包含 current_behavior、expected_behavior、acceptance_examples；confidence 为 0 到 1；只有 unclear 才填写 clarifying_question。
改变或新增产品可见行为属于 requirement_change；需求不变但架构冲突属于 architecture_defect；架构成立但 Dev Design 冲突或缺失属于 dev_design_defect；三份文档都支持期望行为但软件不符才属于 implementation_defect。不得仅凭用户使用“缺陷”一词判为实现缺陷。""",
        feedback, context, ToolRuntime(root), tool_schemas=[],
        history_key=f"acceptance_triage_{event.id}", runtime_step=Step.product_docs)
    result = parse_triage_result(response)
    # 再次核对行为变更契约与分类是否一致。
    consistency_text = model_tool_loop(
        db, task, run,
        """你是独立 Acceptance Interpretation Consistency Validator，不重新解决产品问题，也不修改文件。
检查初步分类是否忠实且自洽：用户是在“报告问题”，每个编号项都必须解释；current_behavior 必须是用户观察到的现状，expected_behavior 必须是用户希望改变后的行为。若某项被解释出的 expected_behavior 与现有正式需求相同，但初步分类又无法说明实际实现如何违反它，该解释通常把缺陷描述反当成期望；若原句方向存在两种合理解释，也必须判为不一致并要求澄清。总体 classification 必须采用所有条目中最早失效的阶段。
只返回 JSON：consistent 为布尔值；contradictions 为字符串数组；clarifying_question 在不一致时只问一个能消除行为方向歧义的问题，一致时为 null。""",
        feedback, {"approved_documents": inputs, "initial_triage": result},
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
        result["clarifying_question"] = (consistency.get("clarifying_question")
                                           if isinstance(consistency, dict) else None) or \
                                          "请明确说明当前行为和你期望修改后的行为。"
    result["consistency_validation"] = consistency
    result.update({"event_id": event.id, "user_feedback": feedback})
    target = TRIAGE_TARGETS.get(result["classification"])
    result["target_step"] = target.value if target else None
    evidence_path = root / "evidence" / f"acceptance-triage-{event.id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    safe_record_trace(db, task, run, "acceptance_triage",
                      "waiting" if target is None else "succeeded", "验收问题分类",
                      f"{result['classification']} → {result['target_step'] or 'waiting_user'}",
                      {"input": {"feedback": feedback, **context}, "model_response": response,
                       "validated_result": result},
                      {"classification": result["classification"], "target_step": result["target_step"],
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
        if target == Step.develop:
            task.repair_round += 1
        else:
            task.repair_round = 0
        add_message(db, task, "assistant",
                    f"问题已识别为 {result['classification']}，将从 {target.value} 阶段重新处理。")
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
            classify_acceptance_feedback(db, task, event, feedback)
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
                classify_acceptance_feedback(db, task, event, combined)
            else:
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
