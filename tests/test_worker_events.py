import json
import hashlib
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
                                        handle_reviewed_doc, model_tool_loop, process_pending_event, process_task,
                                        product_feedback_is_decided, plan_bug_action, product_code_hashes,
                                        bug_verified_ready, parse_transition_decision, active_bug_triage,
                                        plan_initial_design_action, skipped_design_evidence)


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


def test_succeeded_task_change_request_enters_product_candidate_without_replacing_formal(tmp_path, monkeypatch):
    # 已验收任务接收新功能后先进入需求候选阶段，保留原正式文档与任务历史。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    docs.mkdir(); product.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text("仅支持加法", encoding="utf-8")
    (product / "app.js").write_text("add only", encoding="utf-8")

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            answer = {"consistent": True, "contradictions": [], "clarifying_question": None}
        else:
            answer = {"action": "update_requirement", "path": None, "reason": "新增乘法属于需求变更",
                      "evidence": [{"document": "product.md", "statement": "仅支持加法"}],
                      "changes": [{"current_behavior": "仅支持加法", "expected_behavior": "同时支持乘法",
                                   "acceptance_examples": ["输入 2×3 得到 6"]}],
                      "confidence": 0.95, "clarifying_question": None}
        return ModelResult(request.request_id, 1, json.dumps(answer, ensure_ascii=False), [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="existing calculator", cur_step=Step.verify_product,
                    status=TaskStatus.succeeded, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.verify_product,
                       status=StepStatus.succeeded, attempt=1))
        db.add(Event(task_id=task.id, type="change_request", data={"feedback": "新增乘法，2×3 得到 6"}))
        db.commit()
        assert process_pending_event(db)
        db.refresh(task)
        assert task.status == TaskStatus.running and task.cur_step == Step.product_docs
        assert (docs / "product.md").read_text(encoding="utf-8") == "仅支持加法"
        assert db.scalar(select(Event)).status == EventStatus.consumed


@pytest.mark.parametrize("status,feedback,error", [
    (TaskStatus.waiting_acceptance, "新增乘法", "task_not_succeeded_for_change_request"),
    (TaskStatus.succeeded, " ", "change_request_feedback_required"),
])
def test_change_request_rejects_invalid_entry(tmp_path, status, feedback, error):
    # 变更入口只接受已验收任务的非空需求，非法事件不改变任务状态。
    with SessionLocal() as db:
        task = Task(task_name="calculator", cur_step=Step.verify_product,
                    status=status, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(Event(task_id=task.id, type="change_request", data={"feedback": feedback}))
        db.commit()
        assert process_pending_event(db)
        db.refresh(task)
        assert task.status == status
        assert db.scalar(select(Event)).error == error


def test_existing_design_defect_cannot_reuse_broken_stage():
    # 已确认设计缺陷时，同一阶段的复用提议必须转为澄清。
    response = json.dumps({"action": "update_dev_design", "reason": "复用现有架构",
                           "confidence": 0.98})
    assert parse_transition_decision(response, "architecture", required_update=True)["action"] == "clarify"
    assert parse_transition_decision(response, "architecture")["action"] == "reuse"


def test_new_task_has_no_existing_change_planner(tmp_path):
    # 新任务没有验收变更证据，仍由固定七阶段入口处理。
    task = Task(task_name="new calculator", cur_step=Step.product_docs,
                status=TaskStatus.pending, workspace_path=str(tmp_path))
    assert active_bug_triage(task) == {}


@pytest.mark.parametrize("step,action,next_step,skipped", [
    (Step.architecture_docs, "modify_code", Step.develop, ["architecture.md", "dev-design.md"]),
    (Step.architecture_docs, "update_dev_design", Step.dev_design, ["architecture.md"]),
    (Step.dev_design, "modify_code", Step.develop, ["dev-design.md"]),
])
def test_initial_design_planner_skips_only_unneeded_documents(
        tmp_path, monkeypatch, step, action, next_step, skipped):
    # Planner 根据正式需求提出具体依据；程序只跳对应设计文档并永久保存决定。
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "product.md").write_text("两个输入，点击加法得结果；错误显示 Error，可继续输入；无存储。",
                                      encoding="utf-8")
    if step == Step.dev_design:
        (docs / "architecture.md").write_text("单模块页面", encoding="utf-8")

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        assert "两个输入" in context["approved_product"]
        assert "原生 HTML" in context["project_constraints"][0]
        return json.dumps({"action": action, "reason": "已批准需求写清行为和错误恢复",
                           "evidence": ["两个输入，点击加法得结果；错误显示 Error，可继续输入"],
                           "unresolved_decisions": [], "confidence": 0.92,
                           "clarifying_question": None}, ensure_ascii=False)

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="simple calculator", cur_step=step,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=step, status=StepStatus.running, attempt=1)
        db.add(run); db.commit()
        assert plan_initial_design_action(db, task, run, ToolRuntime(tmp_path)) == action
        assert task.cur_step == next_step
        assert sorted(skipped_design_evidence(task)) == sorted(skipped)
        assert not (docs / "dev-design.md").is_file()
        if "architecture.md" in skipped:
            assert not (docs / "architecture.md").is_file()


def test_initial_design_planner_cannot_skip_confirmed_architecture_defect(tmp_path, monkeypatch):
    # 验收已判定架构缺陷后，可选集合不再包含跳过架构的行动。
    (tmp_path / "docs").mkdir(); (tmp_path / "evidence").mkdir()
    (tmp_path / "docs/product.md").write_text("明确需求", encoding="utf-8")
    (tmp_path / "evidence/acceptance-triage-7.json").write_text(json.dumps({
        "event_id": 7, "classification": "architecture_defect",
        "planner_action": "update_architecture", "user_feedback": "缺少必要模块"}), encoding="utf-8")

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        assert context["allowed_actions"] == ["update_architecture", "clarify"]
        return json.dumps({"action": "modify_code", "reason": "误跳过",
                           "evidence": ["明确需求"], "unresolved_decisions": [],
                           "confidence": 0.95})

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="defective design", cur_step=Step.architecture_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.architecture_docs,
                      status=StepStatus.running, attempt=2)
        db.add(run); db.commit()
        assert plan_initial_design_action(db, task, run, ToolRuntime(tmp_path)) == "clarify"
        assert task.status == TaskStatus.waiting_user
        assert task.cur_step == Step.architecture_docs


def test_process_task_uses_initial_planner_before_generating_design(tmp_path, monkeypatch):
    # 产品需求已批准后，Worker 可以直接跳过两份设计并进入开发。
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/product.md").write_text("两个输入加法，错误后可继续，Clear 显示 0。",
                                                encoding="utf-8")

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        return json.dumps({"action": "modify_code", "reason": "行为、错误和恢复已明确",
                           "evidence": ["两个输入加法，错误后可继续，Clear 显示 0"],
                           "unresolved_decisions": [], "confidence": 0.9,
                           "clarifying_question": None}, ensure_ascii=False)

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="simple new task", cur_step=Step.architecture_docs,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.product_docs,
                       status=StepStatus.succeeded, attempt=1))
        db.commit()
        assert process_task(db)
        db.refresh(task)
        assert task.cur_step == Step.develop
        assert not (tmp_path / "docs/architecture.md").is_file()
        assert not (tmp_path / "docs/dev-design.md").is_file()
        assert db.scalar(select(TraceRecord).where(
            TraceRecord.type == "initial_design_plan")).metadata_json["action"] == "modify_code"


def test_develop_uses_approved_product_when_dev_design_was_explicitly_skipped(tmp_path, monkeypatch):
    # 没有 Dev Design 时开发依据来自已批准需求和跳过证据，血缘记录真实来源。
    (tmp_path / "docs").mkdir(); (tmp_path / "product").mkdir(); (tmp_path / "evidence").mkdir()
    (tmp_path / "docs/product.md").write_text("两个输入加法，2+3 得 5，错误后恢复。", encoding="utf-8")
    (tmp_path / "evidence/initial-architecture-decision-v1.json").write_text(json.dumps({
        "action": "modify_code", "reason": "已确认简单行为", "evidence": ["2+3 得 5"],
        "document_hashes": {"product": "test"},
        "skipped_documents": ["architecture.md", "dev-design.md"]}), encoding="utf-8")
    seen = {}

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        seen.update(context)
        for name in ("index.html", "styles.css", "app.js", "calculator.test.js",
                     "verify_product.py", "implementation.md"):
            (tmp_path / "product" / name).write_text(name, encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="simple task", cur_step=Step.develop,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop,
                      status=StepStatus.running, attempt=1)
        db.add(run); db.commit()
        handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert task.cur_step == Step.test
        assert seen["design_source"] == "approved_product_and_constraints"
        assert "2+3 得 5" in seen["dev_design"]
        assert json.loads((tmp_path / "evidence/implementation-lineage.json").read_text())[
            "design_source"] == "approved_product_and_constraints"


def test_acceptance_bug_can_route_after_both_design_documents_were_skipped(tmp_path, monkeypatch):
    # 缺失文档有明确跳过决定时，验收 Bug 仍可调查代码并进入开发返修。
    (tmp_path / "docs").mkdir(); (tmp_path / "product").mkdir(); (tmp_path / "evidence").mkdir()
    (tmp_path / "docs/product.md").write_text("Clear 显示 0", encoding="utf-8")
    (tmp_path / "product/app.js").write_text("display='BROKEN'", encoding="utf-8")
    (tmp_path / "evidence/initial-architecture-decision-v1.json").write_text(json.dumps({
        "action": "modify_code", "reason": "需求与固定约束足够",
        "evidence": ["Clear 显示 0"], "document_hashes": {"product": "test"},
        "skipped_documents": ["architecture.md", "dev-design.md"]}), encoding="utf-8")

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            answer = {"consistent": True, "contradictions": [], "clarifying_question": None}
        elif not request.context["inspected_files"]:
            answer = {"action": "inspect", "path": "product/app.js"}
        else:
            assert request.context["skipped_design"]["dev-design.md"]["reason"]
            answer = {"action": "modify_code", "path": None, "reason": "Clear 实现偏离正式需求",
                      "evidence": [{"document": "product.md", "statement": "Clear 显示 0"}],
                      "changes": [], "confidence": 0.94, "clarifying_question": None}
        return ModelResult(request.request_id, 1, json.dumps(answer, ensure_ascii=False), [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="simple clear", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.verify_product,
                       status=StepStatus.succeeded, attempt=1))
        db.add(Event(task_id=task.id, type="acceptance_result", data={
            "approved": False, "feedback": "Clear 当前显示 BROKEN，期望 0"}))
        db.commit()
        assert process_pending_event(db)
        db.refresh(task)
        assert task.cur_step == Step.develop and task.status == TaskStatus.running


def test_dev_design_can_be_generated_directly_from_product_after_architecture_skip(
        tmp_path, monkeypatch):
    # 只有 Dev Design 必要时，不依赖不存在的架构文件即可生成正式设计。
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "product.md").write_text("单模块计时器，开始／暂停／恢复／完成状态已确认。",
                                      encoding="utf-8")
    seen = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        history = kwargs.get("history_key")
        seen.append((history, input_text))
        if history.startswith("initial_dev_design_plan"):
            return json.dumps({"action": "update_dev_design", "reason": "计时状态转换需要实现设计",
                               "evidence": ["开始／暂停／恢复／完成状态"],
                               "unresolved_decisions": [], "confidence": 0.94,
                               "clarifying_question": None}, ensure_ascii=False)
        target = {"dev_design_draft": "dev-design-draft.md",
                  "dev_design_review": "dev-design-review.md",
                  "dev_design_formal": "dev-design-v1.md"}[history]
        (docs / target).write_text("计时设计", encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="timer", cur_step=Step.dev_design,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.architecture_docs,
                       status=StepStatus.succeeded, attempt=1))
        db.commit()
        assert process_task(db)
        db.refresh(task)
        assert task.cur_step == Step.develop
        assert not (docs / "architecture.md").is_file()
        assert (docs / "dev-design.md").read_text(encoding="utf-8") == "计时设计"
        assert seen[1][1] == (docs / "product.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("classification,target", [
    ("requirement_change", Step.product_docs),
    ("architecture_defect", Step.architecture_docs),
    ("dev_design_defect", Step.dev_design),
    ("implementation_defect", Step.develop),
])
def test_acceptance_planner_action_routes_to_earliest_stage(tmp_path, monkeypatch, classification, target):
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product.mkdir(); evidence.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text(name, encoding="utf-8")
    (product / "app.js").write_text("app", encoding="utf-8")
    action = {"requirement_change": "update_requirement", "architecture_defect": "update_architecture",
              "dev_design_defect": "update_dev_design", "implementation_defect": "modify_code"}[classification]
    response = json.dumps({
        "action": action, "path": None,
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
        if not request.context["inspected_files"]:
            return ModelResult(request.request_id, 1, json.dumps({"action": "inspect", "path": "product/app.js"}),
                               [], "completed")
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
        assert saved["planner_action"] == action
        assert saved["target_step"] == target.value
        inspect_trace = db.scalar(select(TraceRecord).where(TraceRecord.type == "acceptance_inspect"))
        assert inspect_trace.metadata_json["path"] == "product/app.js"
        trace = db.scalar(select(TraceRecord).where(TraceRecord.type == "acceptance_plan"))
        assert trace.metadata_json["classification"] == classification
        assert trace.metadata_json["planner_action"] == action


def test_acceptance_planner_inspects_multiple_files_before_routing(tmp_path, monkeypatch):
    # 两次读取均产生证据后才能分类，拒绝只凭短句进入开发阶段。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    docs.mkdir(); product.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text("清除后显示 0", encoding="utf-8")
    (product / "app.js").write_text("display = ''", encoding="utf-8")
    (product / "calculator.test.js").write_text("clear should display 0", encoding="utf-8")
    seen = []

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            assert len(request.context["initial_triage"]["evidence"]) == 2
            return ModelResult(request.request_id, 1, json.dumps({"consistent": True, "contradictions": []}),
                               [], "completed")
        seen.append(request.context["inspected_files"].copy())
        if len(request.context["inspected_files"]) < 2:
            remaining = request.context["remaining_files"]
            path = "product/app.js" if "product/app.js" in remaining else "product/calculator.test.js"
            return ModelResult(request.request_id, 1, json.dumps({"action": "inspect", "path": path}),
                               [], "completed")
        return ModelResult(request.request_id, 1, json.dumps({
            "action": "modify_code", "reason": "代码偏离正式需求",
            "evidence": ["product/app.js", "product/calculator.test.js"], "changes": [],
            "confidence": 0.95}), [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="clear bug", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(Event(task_id=task.id, type="acceptance_result",
                     data={"approved": False, "feedback": "清除后显示不对"}))
        db.commit()
        assert process_pending_event(db)
        db.refresh(task)
        assert task.cur_step == Step.develop
        assert len(seen) == 3 and len(seen[1]) == 1 and len(seen[2]) == 2
        traces = db.scalars(select(TraceRecord).where(TraceRecord.type == "acceptance_inspect")).all()
        assert [trace.metadata_json["path"] for trace in traces] == [
            "product/app.js", "product/calculator.test.js"]


def test_acceptance_planner_rejects_unlisted_file(tmp_path, monkeypatch):
    # 模型要求清单外文件时程序拒绝读取，并保持等待澄清状态。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    docs.mkdir(); product.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text(name, encoding="utf-8")
    (product / "app.js").write_text("app", encoding="utf-8")

    def fake_call(runtime, task_id, request):
        assert "Consistency Validator" not in request.instructions
        return ModelResult(request.request_id, 1, json.dumps({"action": "inspect", "path": "../ROADMAP.md"}),
                           [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="unsafe inspect", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(Event(task_id=task.id, type="acceptance_result",
                     data={"approved": False, "feedback": "清除后显示不对"}))
        db.commit()
        assert process_pending_event(db)
        db.refresh(task)
        assert task.status == TaskStatus.waiting_user
        assert task.cur_step == Step.verify_product
        assert db.scalar(select(TraceRecord).where(TraceRecord.type == "acceptance_inspect")).status == "failed"


def test_acceptance_planner_can_update_requirement_from_formal_documents(tmp_path, monkeypatch):
    # 用户明确改变正式需求时，Planner 不应被迫读取无关代码或误转澄清。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    docs.mkdir(); product.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text("清除后显示 0", encoding="utf-8")
    (product / "app.js").write_text("display = 0", encoding="utf-8")

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            return ModelResult(request.request_id, 1, json.dumps({"consistent": True,
                                                                  "contradictions": []}), [], "completed")
        return ModelResult(request.request_id, 1, json.dumps({
            "action": "update_requirement", "path": None, "reason": "用户明确改变已确认行为",
            "evidence": ["product.md"], "confidence": 0.95,
            "changes": [{"current_behavior": "显示 0", "expected_behavior": "显示为空",
                         "acceptance_examples": ["点击清除后显示为空"]}]}), [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="Clear change", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(Event(task_id=task.id, type="acceptance_result",
                     data={"approved": False, "feedback": "清除后改为显示为空"}))
        db.commit()
        assert process_pending_event(db)
        db.refresh(task)
        assert task.cur_step == Step.product_docs
        assert task.status == TaskStatus.running
        assert db.scalar(select(TraceRecord).where(TraceRecord.type == "acceptance_inspect")) is None
        assert (docs / "product.md").read_text(encoding="utf-8") == "清除后显示 0"


def test_acceptance_planner_requires_code_read_before_modify(tmp_path, monkeypatch):
    # 即使模型先声称是代码缺陷，程序也会要求取得代码证据后再放行。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    docs.mkdir(); product.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text("清除后显示 0", encoding="utf-8")
    (product / "app.js").write_text("display = BROKEN", encoding="utf-8")
    calls = []

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            return ModelResult(request.request_id, 1, json.dumps({"consistent": True,
                                                                  "contradictions": []}), [], "completed")
        calls.append(request.context)
        action = "inspect" if request.context["protocol_error"] else "modify_code"
        if request.context["inspected_files"]:
            action = "modify_code"
        return ModelResult(request.request_id, 1, json.dumps({
            "action": action, "path": "product/app.js" if action == "inspect" else None,
            "reason": "代码偏离正式设计", "evidence": ["product/app.js"], "confidence": 0.95}),
            [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="clear bug", cur_step=Step.verify_product,
                    status=TaskStatus.waiting_acceptance, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        db.add(Event(task_id=task.id, type="acceptance_result",
                     data={"approved": False, "feedback": "清除后显示错误"}))
        db.commit()
        assert process_pending_event(db)
        db.refresh(task)
        assert task.cur_step == Step.develop
        assert len(calls) == 3 and calls[1]["protocol_error"]
        assert db.scalar(select(TraceRecord).where(TraceRecord.type == "acceptance_inspect",
                                TraceRecord.status == "succeeded")) is not None


def test_bug_next_action_planner_inspects_then_runs_test(tmp_path, monkeypatch):
    # 开发行动结束后，Planner 可以先追加检查，再根据新增内容选择正式测试。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product.mkdir(); evidence.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text("清除后显示 0", encoding="utf-8")
    (product / "app.js").write_text("display = 0", encoding="utf-8")
    (evidence / "acceptance-triage-42.json").write_text(json.dumps({
        "event_id": 42, "user_feedback": "清除后显示不对", "classification": "implementation_defect",
        "planner_action": "modify_code",
        "inspected_evidence": {}}), encoding="utf-8")
    calls = []

    def fake_call(runtime, task_id, request):
        calls.append(request.context)
        assert "modify_code" not in request.context["allowed_actions"]
        action = ("inspect" if not request.context["inspected_content"] else "run_test")
        path = "product/app.js" if action == "inspect" else None
        return ModelResult(request.request_id, 1, json.dumps({
            "action": action, "path": path, "reason": "检查修复结果",
            "evidence_refs": ["product/app.js"]}), [], "completed")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", fake_call)
    with SessionLocal() as db:
        task = Task(task_name="clear bug", cur_step=Step.test, status=TaskStatus.running,
                    workspace_path=str(tmp_path), repair_round=1)
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.develop,
                       status=StepStatus.succeeded, attempt=1, output_path="product/app.js"))
        run = create_step_run(db, task)
        db.commit()
        tools = ToolRuntime(tmp_path)
        assert plan_bug_action(db, task, run, tools) == "inspect"
        assert plan_bug_action(db, task, run, tools) == "run_test"
        assert calls[1]["inspected_content"]["product/app.js"] == "display = 0"
        assert "product/app.js" not in calls[1]["remaining_files"]


def test_bug_finish_rejects_old_or_changed_verification(tmp_path):
    # 上轮浏览器成功和旧文件哈希不能充当本轮 Bug 的完成证据。
    (tmp_path / "product").mkdir()
    (tmp_path / "evidence").mkdir()
    app = tmp_path / "product" / "app.js"
    app.write_text("display = 0", encoding="utf-8")
    with SessionLocal() as db:
        task = Task(task_name="clear bug", cur_step=Step.verify_product,
                    status=TaskStatus.running, workspace_path=str(tmp_path),
                    result_url="http://127.0.0.1:12345")
        db.add(task); db.flush()
        db.add(StepRun(task_id=task.id, step=Step.verify_product,
                       status=StepStatus.succeeded, attempt=1))
        db.add(StepRun(task_id=task.id, step=Step.develop,
                       status=StepStatus.succeeded, attempt=1))
        db.flush()
        hashes = product_code_hashes(task)
        for name in ("bug-tested-code-hashes.json", "bug-verified-code-hashes.json"):
            (tmp_path / "evidence" / name).write_text(json.dumps(hashes), encoding="utf-8")
        assert not bug_verified_ready(db, task)
        db.add(StepRun(task_id=task.id, step=Step.verify_product,
                       status=StepStatus.succeeded, attempt=2))
        db.flush()
        assert bug_verified_ready(db, task)
        app.write_text("display = BROKEN", encoding="utf-8")
        assert not bug_verified_ready(db, task)


def test_bug_planner_blocks_start_after_code_changes(tmp_path, monkeypatch):
    # 测试通过后的文件若又变化，程序在请求 Planner 前就阻止启动。
    docs = tmp_path / "docs"
    evidence = tmp_path / "evidence"
    product = tmp_path / "product"
    docs.mkdir(); evidence.mkdir(); product.mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (docs / name).write_text(name, encoding="utf-8")
    (evidence / "acceptance-triage-5.json").write_text(json.dumps({
        "event_id": 5, "user_feedback": "清除显示错误", "classification": "implementation_defect",
        "planner_action": "modify_code",
        "inspected_evidence": {}}), encoding="utf-8")
    app = product / "app.js"
    app.write_text("display = 0", encoding="utf-8")

    def no_model_call(runtime, task_id, request):
        pytest.fail("测试证据过期时不能请求 Planner 或启动服务")

    monkeypatch.setattr("backend.app.runtime.model.KimiRuntime.call", no_model_call)
    with SessionLocal() as db:
        task = Task(task_name="clear bug", cur_step=Step.start_product,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        (evidence / "bug-tested-code-hashes.json").write_text(
            json.dumps(product_code_hashes(task)), encoding="utf-8")
        app.write_text("display = BROKEN", encoding="utf-8")
        run = create_step_run(db, task)
        db.commit()
        with pytest.raises(RuntimeError, match="bug_test_evidence_stale"):
            plan_bug_action(db, task, run, ToolRuntime(tmp_path))


def test_low_confidence_acceptance_triage_waits_for_user(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir(); (tmp_path / "product").mkdir(); (tmp_path / "evidence").mkdir()
    for name in ("product.md", "architecture.md", "dev-design.md"):
        (tmp_path / "docs" / name).write_text(name, encoding="utf-8")
    (tmp_path / "product" / "app.js").write_text("display = BROKEN", encoding="utf-8")

    def fake_call(runtime, task_id, request):
        if "Consistency Validator" in request.instructions:
            consistent = {"consistent": True, "contradictions": [], "clarifying_question": None}
            return ModelResult(request.request_id, 1, json.dumps(consistent), [], "completed")
        if not request.context["inspected_files"]:
            return ModelResult(request.request_id, 1,
                               json.dumps({"action": "inspect", "path": "product/app.js"}), [], "completed")
        result = {"action": "modify_code", "path": None,
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
        result = {"action": "update_requirement", "path": None,
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
        if "Next Action Planner" in instructions:
            return json.dumps({"action": "update_architecture", "reason": "product changed",
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
        return json.dumps({"action": "update_dev_design", "reason": "no impact",
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


def test_existing_feature_requires_real_code_and_test_change_even_when_design_reused(tmp_path, monkeypatch):
    # 复用 Dev Design 的小功能仍须实际修改实现和验证用例，不能因文件齐全跳过。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product.mkdir(); evidence.mkdir()
    (docs / "product.md").write_text("支持加法和乘法", encoding="utf-8")
    (docs / "product-v1.md").write_text("仅支持加法", encoding="utf-8")
    (docs / "product-v2.md").write_text("支持加法和乘法", encoding="utf-8")
    (docs / "dev-design.md").write_text("原生 JavaScript 计算器", encoding="utf-8")
    required = ("index.html", "styles.css", "app.js", "calculator.test.js",
                "verify_product.py", "implementation.md")
    for name in required:
        (product / name).write_text("old", encoding="utf-8")
    (evidence / "acceptance-triage-3.json").write_text(json.dumps({
        "event_id": 3, "planner_action": "update_requirement", "classification": "requirement_change",
        "user_feedback": "新增乘法"}), encoding="utf-8")
    seen = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        seen.append(context)
        (product / "app.js").write_text("add and multiply", encoding="utf-8")
        (product / "calculator.test.js").write_text("test multiply", encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="existing calculator", cur_step=Step.develop,
                    status=TaskStatus.running, workspace_path=str(tmp_path), repair_round=0)
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop,
                      status=StepStatus.running, attempt=2)
        db.add(run); db.commit()
        handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert task.cur_step == Step.test
        assert seen[0]["previous_product"] == "仅支持加法"
        assert (product / "app.js").read_text() == "add and multiply"
        assert (product / "calculator.test.js").read_text() == "test multiply"


@pytest.mark.parametrize("classification,planner_action", [
    ("architecture_defect", "update_architecture"),
    ("dev_design_defect", "update_dev_design"),
])
def test_existing_design_change_cannot_skip_develop_when_design_text_reused(
        tmp_path, monkeypatch, classification, planner_action):
    # 已确认设计变更即使最终 Dev Design 文本相同，也须进入增量开发。
    docs = tmp_path / "docs"
    product = tmp_path / "product"
    evidence = tmp_path / "evidence"
    docs.mkdir(); product.mkdir(); evidence.mkdir()
    (docs / "product.md").write_text("calculator", encoding="utf-8")
    (docs / "dev-design.md").write_text("same design", encoding="utf-8")
    for name in ("index.html", "styles.css", "app.js", "calculator.test.js",
                 "verify_product.py", "implementation.md"):
        (product / name).write_text("old", encoding="utf-8")
    (evidence / "implementation-lineage.json").write_text(json.dumps({
        "dev_design_hash": hashlib.sha256("same design".encode()).hexdigest()}), encoding="utf-8")
    (evidence / "acceptance-triage-2.json").write_text(json.dumps({
        "event_id": 2, "classification": classification, "planner_action": planner_action,
        "user_feedback": "修订设计"}), encoding="utf-8")
    called = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        called.append(context)
        (product / "app.js").write_text("updated", encoding="utf-8")
        return "done"

    monkeypatch.setattr("backend.app.runtime.worker.model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task = Task(task_name="design change", cur_step=Step.develop,
                    status=TaskStatus.running, workspace_path=str(tmp_path), repair_round=0)
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=2)
        db.add(run); db.commit()
        handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert called and task.cur_step == Step.test
