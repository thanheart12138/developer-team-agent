import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import Base, SessionLocal, engine
from backend.app.models import (Event, EventStatus, Message, Step, StepRun, StepStatus, Task, TaskStatus,
                                TraceRecord)
from backend.app.runtime.contracts import ModelResult, ToolCall, ToolResult
from backend.app.runtime.model import ModelProtocolError
from backend.app.runtime.tools import ToolRuntime
from backend.app.runtime.worker import (create_step_run, execute_tool, handle_develop, handle_product_docs, handle_verify,
                                        handle_reviewed_doc, model_tool_loop, process_pending_event,
                                        product_feedback_is_decided)


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def waiting_task(db):
    task = Task(task_name="calculator", cur_step=Step.product_docs, status=TaskStatus.waiting_user,
                workspace_path="/tmp/dev-team-simulator-tests/event-task")
    db.add(task)
    db.flush()
    draft = Path(task.workspace_path) / "docs" / "product-v1-draft.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("approved content", encoding="utf-8")
    db.add(StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.waiting_user, attempt=1))
    return task


def test_approval_atomically_promotes_document_and_state():
    with SessionLocal() as db:
        task = waiting_task(db)
        db.add(Event(task_id=task.id, type="document_approval", data={
            "document_type": "product", "document_version": 1, "approved": True, "feedback": ""}))
        db.commit()
    with SessionLocal() as db:
        assert process_pending_event(db) is True
    with SessionLocal() as db:
        task = db.scalar(select(Task))
        event = db.scalar(select(Event))
        assert task.status == TaskStatus.running
        assert task.cur_step == Step.architecture_docs
        assert event.status == EventStatus.consumed
        assert (Path(task.workspace_path) / "docs" / "product.md").read_text() == "approved content"
        assert db.scalar(select(Message).where(Message.role == "user")) is not None


def test_mismatched_document_version_is_rejected_without_state_change():
    with SessionLocal() as db:
        task = waiting_task(db)
        db.add(Event(task_id=task.id, type="document_approval", data={
            "document_type": "product", "document_version": 2, "approved": True}))
        db.commit()
    with SessionLocal() as db:
        process_pending_event(db)
    with SessionLocal() as db:
        task = db.scalar(select(Task))
        event = db.scalar(select(Event))
        assert task.status == TaskStatus.waiting_user
        assert event.status == EventStatus.rejected
        assert event.error == "document_type_or_version_mismatch"


@pytest.mark.parametrize("classification,target", [
    ("requirement_change", Step.product_docs),
    ("architecture_defect", Step.architecture_docs),
    ("dev_design_defect", Step.dev_design),
    ("implementation_defect", Step.develop),
])
def test_acceptance_feedback_is_classified_and_routed(tmp_path, monkeypatch, classification, target):
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product.mkdir(); evidence.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text(name, encoding="utf-8")
    (product / "app.js").write_text("app", encoding="utf-8")
    response = json.dumps({
        "classification": classification,
        "target_step": target.value,
        "reason": "matched evidence",
        "evidence": [{"document": "product.md", "statement": "rule"}],
        "changes": ([{"current_behavior": "old", "expected_behavior": "new",
                      "acceptance_examples": ["example"]}]
                    if classification == "requirement_change" else []),
        "confidence": 0.95,
        "clarifying_question": None,
    })

    def fake_call(runtime, task_id, request):
        assert runtime.provider == "kimi"
        assert request.tools == []
        if "Consistency Validator" in request.instructions:
            consistent = {"consistent": True, "contradictions": [], "clarifying_question": None}
            return ModelResult(request.request_id, 1, json.dumps(consistent), [], "completed")
        return ModelResult(request.request_id, 1, response, [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="triage", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.verify_product,
                       status=StepStatus.succeeded, attempt=1))
        db.add(Event(task_id=task.id, type="acceptance_result",
                     data={"approved": False, "feedback": "reported issue"}))
        db.commit()

        assert process_pending_event(db) is True
        db.refresh(task)
        assert task.status == TaskStatus.running
        assert task.cur_step == target
        saved = json.loads(next(evidence.glob("acceptance-triage-*.json")).read_text())
        assert saved["classification"] == classification
        assert saved["target_step"] == target.value
        trace = db.scalar(select(TraceRecord).where(TraceRecord.type == "acceptance_triage"))
        assert trace.metadata_json["classification"] == classification


def test_low_confidence_acceptance_triage_waits_for_user(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir(); (tmp_path / "product").mkdir(); (tmp_path / "evidence").mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (tmp_path / "docs" / name).write_text(name, encoding="utf-8")

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            consistent = {"consistent": True, "contradictions": [], "clarifying_question": None}
            return ModelResult(request.request_id, 1, json.dumps(consistent), [], "completed")
        result = {"classification": "implementation_defect", "target_step": "develop",
                  "reason": "insufficient", "evidence": [], "confidence": 0.4,
                  "clarifying_question": "请提供复现步骤。"}
        return ModelResult(request.request_id, 1, json.dumps(result), [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="unclear", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.verify_product,
                       status=StepStatus.succeeded, attempt=1))
        db.add(Event(task_id=task.id, type="acceptance_result",
                     data={"approved": False, "feedback": "不好用"}))
        db.commit()

        process_pending_event(db)
        db.refresh(task)
        assert task.status == TaskStatus.waiting_user
        assert task.cur_step == Step.verify_product
        question = db.scalar(select(Message).where(Message.role == "assistant")
                             .order_by(Message.id.desc()))
        assert question.content == "请提供复现步骤。"


def test_requirement_change_without_behavior_contract_waits_for_user(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir(); (tmp_path / "product").mkdir(); (tmp_path / "evidence").mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (tmp_path / "docs" / name).write_text(name, encoding="utf-8")

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            consistent = {"consistent": False, "contradictions": ["行为方向不明确"],
                          "clarifying_question": "你期望支持连续输入吗？"}
            return ModelResult(request.request_id, 1, json.dumps(consistent), [], "completed")
        result = {"classification": "requirement_change", "target_step": "product_docs",
                  "reason": "ambiguous complaint", "evidence": [], "changes": [],
                  "confidence": 0.95, "clarifying_question": "你期望支持连续输入吗？"}
        return ModelResult(request.request_id, 1, json.dumps(result), [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="ambiguous", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.verify_product,
                       status=StepStatus.succeeded, attempt=1))
        db.add(Event(task_id=task.id, type="acceptance_result",
                     data={"approved": False, "feedback": "不支持连续输入"}))
        db.commit()

        process_pending_event(db)
        db.refresh(task)
        assert task.status == TaskStatus.waiting_user
        assert task.cur_step == Step.verify_product


def test_reviewed_document_revision_does_not_skip_existing_formal_file(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "product.md").write_text("revised product", encoding="utf-8")
    (docs / "architecture.md").write_text("old architecture", encoding="utf-8")
    calls = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        calls.append(instructions)
        if "Transition Planner" in instructions:
            return json.dumps({"action": "revise", "reason": "product changed",
                               "affected_sections": ["flow"], "preserved_sections": ["runtime"],
                               "confidence": 0.95, "clarifying_question": None})
        if "architecture-v2-draft.md" in instructions:
            (docs / "architecture-v2-draft.md").write_text("new draft", encoding="utf-8")
        elif "architecture-v2-review.md" in instructions:
            (docs / "architecture-v2-review.md").write_text("new review", encoding="utf-8")
        else:
            (docs / "architecture-v2.md").write_text("new architecture", encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="architecture revision", cur_step=Step.architecture_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.architecture_docs,
                      status=StepStatus.running, attempt=2)
        db.add(run); db.commit()

        handle_reviewed_doc(db, task, run, ToolRuntime(tmp_path), "architecture")

        assert len(calls) == 4
        assert "overwrite=false" in calls[-1]
        assert (docs / "architecture-v1.md").read_text() == "old architecture"
        assert (docs / "architecture-v2.md").read_text() == "new architecture"
        assert (docs / "architecture.md").read_text() == "new architecture"
        assert (tmp_path / "evidence" / "architecture-transition-v2.json").is_file()
        assert task.cur_step == Step.dev_design


def test_reviewed_document_revision_can_reuse_previous_formal(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "product.md").write_text("same product", encoding="utf-8")
    (docs / "product-v1.md").write_text("same product", encoding="utf-8")
    (docs / "architecture.md").write_text("stable architecture", encoding="utf-8")
    calls = 0

    def fake_loop(*args, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps({"action": "reuse", "reason": "no impact",
                           "affected_sections": [], "preserved_sections": ["all"],
                           "confidence": 0.98, "clarifying_question": None})

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="architecture reuse", cur_step=Step.architecture_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.architecture_docs,
                      status=StepStatus.running, attempt=2)
        db.add(run); db.commit()

        handle_reviewed_doc(db, task, run, ToolRuntime(tmp_path), "architecture")

        assert calls == 1
        assert (docs / "architecture-v2.md").read_text() == "stable architecture"
        assert not (docs / "architecture-v2-draft.md").exists()
        assert task.cur_step == Step.dev_design


def test_running_step_is_reused_after_worker_restart():
    with SessionLocal() as db:
        task = Task(task_name="calculator", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path="/tmp/dev-team-simulator-tests/recovery-task")
        db.add(task)
        db.flush()
        original = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                           model_call_count=3, last_completed_action_index=2)
        db.add(original)
        db.commit()
        recovered = create_step_run(db, task)
        assert recovered.id == original.id
        assert recovered.model_call_count == 3
        assert recovered.last_completed_action_index == 2


def test_model_loop_stops_when_program_validates_required_output(tmp_path, monkeypatch):
    calls = 0

    def fake_call(runtime, task_id, request):
        nonlocal calls
        calls += 1
        return ModelResult(request.request_id, 1, "", [ToolCall(
            "write-1", "write", {"path": "docs/output.md", "content": "done", "overwrite": False}
        )], "tool_calls")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="stop-condition", cur_step=Step.product_docs, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()
        model_tool_loop(db, task, run, "write output", "input", {}, ToolRuntime(tmp_path),
                        stop_when=lambda: (tmp_path / "docs/output.md").is_file())
        assert calls == 1
        assert run.model_call_count == 1


def test_model_loop_allows_the_one_hundredth_logical_call(tmp_path, monkeypatch):
    calls = 0

    def fake_call(runtime, task_id, request):
        nonlocal calls
        calls += 1
        return ModelResult(request.request_id, 1, "DONE", [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="hundred calls", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                      model_call_count=99,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run); db.commit()

        assert model_tool_loop(db, task, run, "finish", "input", {}, ToolRuntime(tmp_path),
                               tool_schemas=[]) == "DONE"
        assert calls == 1
        assert run.model_call_count == 100


def test_model_loop_blocks_third_identical_tool_action(tmp_path, monkeypatch):
    calls = 0

    def fake_call(runtime, task_id, request):
        nonlocal calls
        calls += 1
        if calls <= 3:
            return ModelResult(request.request_id, calls, "", [ToolCall(
                f"exec-{calls}", "exec", {"action": "run", "command": "pwd"}
            )], "tool_calls")
        return ModelResult(request.request_id, calls, "DONE", [], "completed")

    class FakeTools:
        def execute(self, call):
            return ToolResult(call.call_id, call.tool_name, "succeeded", {"exit_code": 0})

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="repeat guard", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run); db.commit()

        assert model_tool_loop(db, task, run, "work", "input", {}, FakeTools()) == "DONE"
        guards = list(db.scalars(select(TraceRecord).where(
            TraceRecord.task_id == task.id, TraceRecord.type == "tool_guard")).all())
        assert len(guards) == 1
        assert guards[0].summary == "repeated_tool_action"


def test_repair_loop_blocks_sixth_non_write_action(tmp_path, monkeypatch):
    calls = 0

    def fake_call(runtime, task_id, request):
        nonlocal calls
        calls += 1
        if calls <= 6:
            return ModelResult(request.request_id, calls, "", [ToolCall(
                f"exec-{calls}", "exec", {"action": "run", "command": f"diagnose-{calls}"}
            )], "tool_calls")
        return ModelResult(request.request_id, calls, "DONE", [], "completed")

    class FakeTools:
        def execute(self, call):
            return ToolResult(call.call_id, call.tool_name, "succeeded", {"exit_code": 0})

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="repair guard", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path=str(tmp_path), repair_round=1)
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=2,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run); db.commit()

        assert model_tool_loop(db, task, run, "repair", "input", {"repair_round": 1}, FakeTools()) == "DONE"
        guard = db.scalar(select(TraceRecord).where(
            TraceRecord.task_id == task.id, TraceRecord.type == "tool_guard"))
        assert guard is not None
        assert guard.summary == "repair_tool_loop_no_write"


def test_product_revision_receives_complete_user_history(tmp_path, monkeypatch):
    captured = {}

    def fake_call(runtime, task_id, request):
        if request.tools == []:
            return ModelResult(request.request_id, 1, "READY", [], "completed")
        if "Product Reviewer" in request.instructions:
            path, content = "docs/product-v1-review.md", "## 阻塞问题\n无\n## 普通问题\n无\n## 建议\n无"
        elif "Product Author" in request.instructions:
            path, content = "docs/product-v1-candidate.md", "reviewed candidate"
        else:
            captured.update(request.context)
            captured["tools"] = request.tools
            path, content = "docs/product-v1-draft.md", "revised"
        return ModelResult(request.request_id, 1, "", [ToolCall(
            f"write-{path}", "write", {"path": path, "content": content, "overwrite": False}
        )], "tool_calls")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="history", cur_step=Step.product_docs, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        db.add_all([Message(task_id=task.id, role="user", content="initial"),
                    Message(task_id=task.id, role="user", content="first answer"),
                    Message(task_id=task.id, role="user", content="second answer")])
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()
        handle_product_docs(db, task, run, ToolRuntime(tmp_path))
        assert captured["conversation_history"] == []
        assert captured["unpaired_user_requests"] == ["initial", "first answer", "second answer"]
        assert [tool["function"]["name"] for tool in captured["tools"]] == ["write"]
        assert (tmp_path / "docs/product-v1-review.md").is_file()
        assert (tmp_path / "docs/product-v1-candidate.md").read_text() == "reviewed candidate"
        assert run.output_path == "docs/product-v1-candidate.md"


def test_product_context_keeps_question_and_answer_together_and_uses_current_product(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir(); (tmp_path / "evidence").mkdir()
    (tmp_path / "docs" / "product.md").write_text("当前正式需求：结果 5 后按 + 显示 5+", encoding="utf-8")
    captured = {}

    def fake_call(runtime, task_id, request):
        captured["input"] = request.input
        captured["context"] = request.context
        return ModelResult(request.request_id, 1, "BLOCKED\n还有问题？", [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="paired context", cur_step=Step.product_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add_all([
            Message(task_id=task.id, role="user", content="最初需求"),
            Message(task_id=task.id, role="assistant", content="结果为 5 后按 + 时如何处理？"),
            Message(task_id=task.id, role="user", content="显示 5+"),
        ])
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=2,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run); db.commit()

        handle_product_docs(db, task, run, ToolRuntime(tmp_path))

        assert captured["input"] == "当前正式需求：结果 5 后按 + 显示 5+"
        pair = captured["context"]["conversation_history"][0]
        assert pair["question"]["content"] == "结果为 5 后按 + 时如何处理？"
        assert pair["answer"]["content"] == "显示 5+"
        ledger = json.loads((tmp_path / "evidence/conversation-turns.json").read_text())
        assert ledger[0]["status"] == "answered"


def test_successful_write_records_artifact_and_links_answered_turn(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    ledger = [{"turn_id": "qa-1-2", "question": {"message_id": 1, "content": "写什么？"},
               "answer": {"message_id": 2, "content": "写需求"}, "status": "answered",
               "step_run_id": 1, "actions": []}]
    (evidence / "conversation-turns.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    with SessionLocal() as db:
        task = Task(task_name="artifact", cur_step=Step.product_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1)
        db.add(run); db.commit()
        call = ToolCall("write-artifact", "write", {
            "path": "docs/result.md", "content": "result", "overwrite": False})

        result = execute_tool(db, task, run, ToolRuntime(tmp_path), call)

        assert result.status == "succeeded"
        artifacts = json.loads((evidence / "artifacts.json").read_text())
        assert artifacts[0]["requested_path"] == "docs/result.md"
        assert artifacts[0]["name"] == "result.md"
        assert artifacts[0]["turn_id"] == "qa-1-2"
        assert len(artifacts[0]["sha256"]) == 64
        turns = json.loads((evidence / "conversation-turns.json").read_text())
        assert turns[0]["actions"][0]["tool_call_id"] == "write-artifact"


def test_product_candidate_is_blocked_when_requirement_change_is_reversed(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir(); (tmp_path / "evidence").mkdir()
    (tmp_path / "docs" / "product.md").write_text("不支持连续输入", encoding="utf-8")
    triage = {"classification": "requirement_change", "changes": [{
        "current_behavior": "当前软件不支持连续输入 2+3*4",
        "expected_behavior": "支持连续输入 2+3*4",
        "acceptance_examples": ["输入 2+3*4 后能够计算"],
    }]}
    (tmp_path / "evidence" / "acceptance-triage-1.json").write_text(
        json.dumps(triage, ensure_ascii=False), encoding="utf-8")
    seen_contexts = []

    def fake_call(runtime, task_id, request):
        seen_contexts.append(request.context)
        if request.tools == [] and "Coverage Validator" not in request.instructions:
            return ModelResult(request.request_id, 1, "READY", [], "completed")
        if "Product Reviewer" in request.instructions:
            path, content = "docs/product-v2-review.md", "## 阻塞问题\n无\n## 普通问题\n无\n## 建议\n无"
        elif "Product Author" in request.instructions:
            path, content = "docs/product-v2-candidate.md", "仍然不支持连续输入"
        elif "Coverage Validator" in request.instructions:
            result = {"items": [{"index": 1, "covered": False,
                                  "reason": "候选保留了被推翻的旧行为"}],
                      "all_covered": False}
            return ModelResult(request.request_id, 1, json.dumps(result, ensure_ascii=False), [], "completed")
        else:
            path, content = "docs/product-v2-draft.md", "仍然不支持连续输入"
        return ModelResult(request.request_id, 1, "", [ToolCall(
            f"write-{path}", "write", {"path": path, "content": content, "overwrite": False}
        )], "tool_calls")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="reversed change", cur_step=Step.product_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(Message(task_id=task.id, role="user", content="不支持连续输入，比如 2+3*4"))
        run = StepRun(task_id=task.id, step=Step.product_docs,
                      status=StepStatus.running, attempt=2,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run); db.commit()

        with pytest.raises(RuntimeError, match="product_change_coverage_failed"):
            handle_product_docs(db, task, run, ToolRuntime(tmp_path))

        assert any(context.get("acceptance_triage") == triage for context in seen_contexts)
        saved = json.loads((tmp_path / "evidence" / "product-v2-change-coverage.json").read_text())
        assert saved["validated"] is False


def test_product_gate_has_no_write_tool(tmp_path, monkeypatch):
    captured = {}

    def fake_call(runtime, task_id, request):
        captured["tools"] = request.tools
        return ModelResult(request.request_id, 1, "BLOCKED\n请确认输入方式。", [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="gate", cur_step=Step.product_docs, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        db.add(Message(task_id=task.id, role="user", content="做一个计算器"))
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()

        handle_product_docs(db, task, run, ToolRuntime(tmp_path))

        assert captured["tools"] == []
        assert task.status == TaskStatus.waiting_user
        assert not (tmp_path / "docs/product-v1-draft.md").exists()


def test_task24_explicit_acceptance_changes_do_not_repeat_confirmation(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    evidence = tmp_path / "evidence"
    docs.mkdir(); evidence.mkdir()
    (docs / "product.md").write_text("结果固定两位小数；显示当前操作数", encoding="utf-8")
    feedback = ("1.去掉尾部的无用的 0，比如5.00变成5，5.10变成5.1\n"
                "2.输入全部显示到显示框中，计算1+2，我想要显示成 1→1+→1+2")
    triage = {"classification": "requirement_change", "confidence": 0.95,
              "clarifying_question": None, "user_feedback": feedback,
              "consistency_validation": {"consistent": True, "contradictions": [],
                                         "clarifying_question": None},
              "changes": [
                  {"current_behavior": "5.00", "expected_behavior": "5",
                   "acceptance_examples": ["5.00→5", "5.10→5.1"]},
                  {"current_behavior": "1→+→2", "expected_behavior": "1→1+→1+2",
                   "acceptance_examples": ["按 1、+、2 依次显示 1、1+、1+2"]}]}
    (evidence / "acceptance-triage-49.json").write_text(
        json.dumps(triage, ensure_ascii=False), encoding="utf-8")
    calls = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        calls.append(instructions)
        raise RuntimeError("draft_started")

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="task24 feedback", cur_step=Step.product_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(Message(task_id=task.id, role="user", content=feedback))
        run = StepRun(task_id=task.id, step=Step.product_docs,
                      status=StepStatus.running, attempt=2)
        db.add(run); db.commit()

        with pytest.raises(RuntimeError, match="draft_started"):
            handle_product_docs(db, task, run, ToolRuntime(tmp_path))

    assert len(calls) == 1
    assert "product-v2-draft.md" in calls[0]
    assert product_feedback_is_decided("旧产品文档", triage)
    assert not product_feedback_is_decided("旧产品文档", {**triage, "confidence": 0.4})
    assert not product_feedback_is_decided("旧产品文档", {**triage, "consistency_validation": {
        "consistent": False, "contradictions": ["反馈含糊"]}})


def test_product_clarification_resumes_same_step_run(tmp_path, monkeypatch):
    def ask_question(runtime, task_id, request):
        return ModelResult(request.request_id, 1, "结果需要保留几位小数？", [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", ask_question)
    with SessionLocal() as db:
        task = Task(task_name="clarification", cur_step=Step.product_docs, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        db.add(Message(task_id=task.id, role="user", content="做一个计算器"))
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()

        handle_product_docs(db, task, run, ToolRuntime(tmp_path))
        assert task.status == TaskStatus.waiting_user
        assert run.status == StepStatus.waiting_user
        assert not (tmp_path / "docs/product-v1-draft.md").exists()

        db.add(Event(task_id=task.id, type="user_message", data={"content": "保留两位小数"}))
        db.commit()
        assert process_pending_event(db) is True
        assert task.status == TaskStatus.running
        assert run.status == StepStatus.running
        assert create_step_run(db, task).id == run.id


def test_product_approval_is_rejected_before_draft_exists(tmp_path):
    with SessionLocal() as db:
        task = Task(task_name="no-draft", cur_step=Step.product_docs, status=TaskStatus.waiting_user,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        db.add(StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.waiting_user, attempt=1))
        db.add(Event(task_id=task.id, type="document_approval", data={
            "document_type": "product", "document_version": 1, "approved": True,
        }))
        db.commit()

        assert process_pending_event(db) is True
        event = db.scalar(select(Event))
        assert event.status == EventStatus.rejected
        assert event.error == "product_draft_not_available"
        assert task.status == TaskStatus.waiting_user


def test_model_loop_retries_transport_error_without_consuming_logical_call_limit(tmp_path, monkeypatch):
    calls = 0

    def fake_call(runtime, task_id, request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("disconnected")
        return ModelResult(request.request_id, 1, "", [ToolCall(
            "write-1", "write", {"path": "docs/output.md", "content": "done", "overwrite": False}
        )], "tool_calls")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="retry", cur_step=Step.product_docs, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()
        model_tool_loop(db, task, run, "write output", "input", {}, ToolRuntime(tmp_path),
                        stop_when=lambda: (tmp_path / "docs/output.md").is_file())
        assert calls == 2
        assert run.model_call_count == 1


def test_model_loop_reports_transport_error_after_three_retries(tmp_path, monkeypatch):
    calls = 0

    def always_fails(runtime, task_id, request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", always_fails)
    monkeypatch.setattr("backend.app.runtime.worker.time.sleep", lambda seconds: None)
    with SessionLocal() as db:
        task = Task(task_name="transport-failure", cur_step=Step.product_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()

        with pytest.raises(RuntimeError, match="model_transport_failed:ConnectError"):
            model_tool_loop(db, task, run, "gate", "input", {}, ToolRuntime(tmp_path))

        assert calls == 6
        assert run.model_call_count == 1
        fallback = db.scalar(select(TraceRecord).where(
            TraceRecord.task_id == task.id, TraceRecord.type == "model_fallback"))
        assert fallback.metadata_json["from_provider"] == "kimi"
        assert fallback.metadata_json["to_provider"] == "deepseek"


def test_kimi_transport_failure_falls_back_to_deepseek_in_same_logical_call(tmp_path, monkeypatch):
    kimi_calls = 0
    deepseek_calls = 0

    def kimi_fails(runtime, task_id, request):
        nonlocal kimi_calls
        kimi_calls += 1
        raise httpx.ConnectError("kimi offline")

    def deepseek_succeeds(runtime, task_id, request):
        nonlocal deepseek_calls
        deepseek_calls += 1
        return ModelResult(request.request_id, 1, "FALLBACK_OK", [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", kimi_fails)
    monkeypatch.setattr("backend.app.runtime.model.DeepSeekRuntime.call", deepseek_succeeds)
    monkeypatch.setattr("backend.app.runtime.worker.time.sleep", lambda seconds: None)
    with SessionLocal() as db:
        task = Task(task_name="fallback", cur_step=Step.product_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run); db.commit()

        result = model_tool_loop(db, task, run, "gate", "input", {}, ToolRuntime(tmp_path),
                                 tool_schemas=[])

        assert result == "FALLBACK_OK"
        assert kimi_calls == 3
        assert deepseek_calls == 1
        assert run.model_call_count == 1
        providers = list(db.scalars(select(TraceRecord).where(
            TraceRecord.task_id == task.id, TraceRecord.type == "model_request"
        ).order_by(TraceRecord.sequence)))
        assert [row.metadata_json["provider"] for row in providers] == ["kimi", "deepseek"]


def test_model_loop_retries_invalid_tool_call_as_new_logical_call(tmp_path, monkeypatch):
    calls = 0

    def invalid_then_valid(runtime, task_id, request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ModelProtocolError("invalid_tool_call", {"choices": [{"message": {
                "tool_calls": [{"function": {"arguments": "{broken"}}],
            }}]})
        return ModelResult(request.request_id, 1, "", [ToolCall(
            "write-1", "write", {"path": "docs/output.md", "content": "done", "overwrite": False}
        )], "tool_calls")

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", invalid_then_valid)
    with SessionLocal() as db:
        task = Task(task_name="protocol-retry", cur_step=Step.develop,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()

        model_tool_loop(db, task, run, "write output", "input", {}, ToolRuntime(tmp_path),
                        stop_when=lambda: (tmp_path / "docs/output.md").is_file())

        assert calls == 2
        assert run.model_call_count == 2
        failed = db.scalar(select(TraceRecord).where(
            TraceRecord.task_id == task.id,
            TraceRecord.type == "model_response",
            TraceRecord.status == "failed",
        ))
        assert failed.summary == "invalid_tool_call"


def test_model_loop_isolates_tool_history_between_step_phases(tmp_path, monkeypatch):
    captured = {}

    def fake_call(runtime, task_id, request):
        captured.update(request.context)
        return ModelResult(request.request_id, 1, "review complete", [], "completed")

    checkpoint = tmp_path / "evidence/checkpoint.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text('[{"history_key":"architecture_draft","result":{"status":"succeeded"}}]',
                          encoding="utf-8")
    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="isolated-history", cur_step=Step.architecture_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.architecture_docs, status=StepStatus.running,
                      attempt=1, checkpoint_path=str(checkpoint))
        db.add(run)
        db.commit()

        model_tool_loop(db, task, run, "review", "draft", {}, ToolRuntime(tmp_path),
                        history_key="architecture_review")

        assert captured["tool_history"] == []


def test_kimi_provider_is_recorded_in_model_traces(tmp_path, monkeypatch):
    def fake_call(runtime, task_id, request):
        return ModelResult(request.request_id, 1, "done", [], "completed")

    monkeypatch.setattr(settings, "model_provider", "kimi")
    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="kimi-trace", cur_step=Step.product_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.product_docs, status=StepStatus.running,
                      attempt=1, checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run)
        db.commit()

        model_tool_loop(db, task, run, "gate", "input", {}, ToolRuntime(tmp_path))

        traces = db.scalars(select(TraceRecord).where(
            TraceRecord.task_id == task.id,
            TraceRecord.type.in_(["model_request", "model_response"]),
        )).all()
        assert len(traces) == 2
        assert all(trace.metadata_json["provider"] == "kimi" for trace in traces)
        assert all(trace.metadata_json["model"] == "kimi-for-coding" for trace in traces)


def test_browser_verification_skip_cannot_pass_acceptance(tmp_path, monkeypatch):
    (tmp_path / "evidence").mkdir()

    class FakeTools:
        def execute(self, call):
            from backend.app.runtime.contracts import ToolResult

            if call.parameters["command"].startswith("node"):
                output = {"exit_code": 0, "stdout": "tests passed", "stderr": ""}
            else:
                output = {"exit_code": 0, "stdout": "[SKIP] 未安装 playwright", "stderr": ""}
            return ToolResult(call.call_id, call.tool_name, "succeeded", output)

    monkeypatch.setattr("backend.app.runtime.worker.fail_or_repair",
                        lambda db, task, run, error: setattr(run, "error", error))
    with SessionLocal() as db:
        task = Task(task_name="verify-skip", cur_step=Step.verify_product, status=TaskStatus.running,
                    workspace_path=str(tmp_path), result_url="http://127.0.0.1:8000")
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.verify_product, status=StepStatus.running, attempt=1)
        db.add(run)
        db.commit()

        handle_verify(db, task, run, FakeTools())

        assert task.status == TaskStatus.running
        assert run.error == "verification_failed"


def test_repair_runs_develop_even_when_all_required_files_exist(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    product_dir = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir()
    product_dir.mkdir()
    evidence.mkdir()
    (docs / "product.md").write_text("product", encoding="utf-8")
    (docs / "dev-design.md").write_text("design", encoding="utf-8")
    (evidence / "test-report.md").write_text("three failures", encoding="utf-8")
    required = ["index.html", "styles.css", "app.js", "calculator.test.js",
                "verify_product.py", "implementation.md"]
    for name in required:
        (product_dir / name).write_text("old", encoding="utf-8")
    captured = {}

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        captured.update(context)
        captured["tool_schemas"] = kwargs.get("tool_schemas")
        (product_dir / "app.js").write_text("fixed", encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="repair", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path=str(tmp_path), repair_round=1)
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=2)
        db.add(run)
        db.commit()

        handle_develop(db, task, run, ToolRuntime(tmp_path))

        assert captured["repair_round"] == 1
        assert captured["latest_failure_report"] == "three failures"
        assert captured["current_product_files"]["product/app.js"] == "old"
        assert {schema["function"]["name"] for schema in captured["tool_schemas"]} == {"write", "exec"}
        assert (product_dir / "app.js").read_text(encoding="utf-8") == "fixed"
        assert task.cur_step == Step.test


def test_verify_repair_uses_verification_report_and_retries_no_change(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    product_dir = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product_dir.mkdir(); evidence.mkdir()
    (docs / "product.md").write_text("product", encoding="utf-8")
    (docs / "dev-design.md").write_text("design", encoding="utf-8")
    (evidence / "test-report.md").write_text("node passed", encoding="utf-8")
    (evidence / "verification-report.md").write_text("browser failed: buttons stay at 0.00", encoding="utf-8")
    required = ["index.html", "styles.css", "app.js", "calculator.test.js",
                "verify_product.py", "implementation.md"]
    for name in required:
        (product_dir / name).write_text("old", encoding="utf-8")
    contexts = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        contexts.append(context)
        if len(contexts) == 2:
            (product_dir / "verify_product.py").write_text("raise SystemExit(0)", encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="verify repair", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path=str(tmp_path), repair_round=2,
                    result_url="http://127.0.0.1:8000")
        db.add(task); db.flush()
        failed = StepRun(task_id=task.id, step=Step.verify_product,
                         status=StepStatus.failed, attempt=2, error="verification_failed")
        db.add(failed); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop,
                      status=StepStatus.running, attempt=3)
        db.add(run); db.commit()

        handle_develop(db, task, run, ToolRuntime(tmp_path))

        assert len(contexts) == 2
        assert contexts[0]["failure_source_step"] == "verify_product"
        assert contexts[0]["latest_failure_report"] == "browser failed: buttons stay at 0.00"
        assert contexts[1]["repair_feedback"]["attempt"] == 1
        assert "unchanged_file_sha256" in contexts[1]["repair_feedback"]
        assert task.cur_step == Step.test


def test_repair_fails_only_after_three_no_change_attempts(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    product_dir = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product_dir.mkdir(); evidence.mkdir()
    (docs / "product.md").write_text("product", encoding="utf-8")
    (docs / "dev-design.md").write_text("design", encoding="utf-8")
    for name in ["index.html", "styles.css", "app.js", "calculator.test.js",
                 "verify_product.py", "implementation.md"]:
        (product_dir / name).write_text("old", encoding="utf-8")
    calls = []
    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop",
                        lambda db, task, run, instructions, input_text, context, tools, **kwargs: calls.append(context))
    with SessionLocal() as db:
        task = Task(task_name="no change", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path=str(tmp_path), repair_round=1)
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop,
                      status=StepStatus.running, attempt=2)
        db.add(run); db.commit()

        try:
            handle_develop(db, task, run, ToolRuntime(tmp_path))
        except RuntimeError as exc:
            assert str(exc) == "repair_made_no_changes"
        else:
            raise AssertionError("three unchanged attempts must fail")

        assert len(calls) == 3
        assert calls[2]["repair_feedback"]["attempt"] == 2


def test_upstream_design_change_runs_develop_even_when_files_exist(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    product_dir = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product_dir.mkdir(); evidence.mkdir()
    (docs / "product.md").write_text("product v2", encoding="utf-8")
    (docs / "dev-design-v1.md").write_text("design v1", encoding="utf-8")
    (docs / "dev-design-v2.md").write_text("design v2", encoding="utf-8")
    (docs / "dev-design.md").write_text("design v2", encoding="utf-8")
    required = ["index.html", "styles.css", "app.js", "calculator.test.js",
                "verify_product.py", "implementation.md"]
    for name in required:
        (product_dir / name).write_text("old", encoding="utf-8")
    captured = {}

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        captured.update(context)
        (product_dir / "app.js").write_text("updated for design v2", encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="upstream revision", cur_step=Step.develop,
                    status=TaskStatus.running, workspace_path=str(tmp_path), repair_round=0)
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop,
                      status=StepStatus.running, attempt=2)
        db.add(run); db.commit()

        handle_develop(db, task, run, ToolRuntime(tmp_path))

        assert captured["previous_dev_design"] == "design v1"
        assert "-design v1" in captured["dev_design_diff"]
        assert "+design v2" in captured["dev_design_diff"]
        assert (product_dir / "app.js").read_text(encoding="utf-8") == "updated for design v2"
        assert (evidence / "implementation-lineage.json").is_file()
        assert task.cur_step == Step.test
