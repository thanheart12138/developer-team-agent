"""新返修提交、程序固定推进及实际 HTTP 预算的隔离回归。"""

import json

import httpx
import pytest
from sqlalchemy import select

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Event, EventStatus, Step, StepRun, Task, TaskStatus
from backend.app.runtime import repair_runtime as repair, worker
from backend.app.runtime.contracts import ModelRequest, ToolCall, ToolResult
from backend.app.runtime.model import DeepSeekRuntime
from backend.app.runtime.tools import ToolRuntime
from backend.app.runtime.unit_workflow import UnitTools


@pytest.fixture
def attempt(tmp_path, monkeypatch):
    """准备完整合成产品与显式授权，隔离门禁仅在单元夹具中替换。"""
    Base.metadata.drop_all(engine)
    # 第一批机制夹具使用可信合成脚本，真实 sandbox 在独立契约／容器探针验证。
    from backend.app.runtime import sandbox
    monkeypatch.setattr(sandbox, "for_workspace", lambda workspace: None)
    Base.metadata.create_all(engine)
    root = tmp_path
    tools = ToolRuntime(root)
    files = {"index.html": "<h1>fixture</h1>", "implementation.md": "fixture",
             "app.test.js": "const {test}=require('node:test'); test('real fixture',()=>{});",
             "verify_product.py": "import sys\nurl=sys.argv[1]\nprint('PASS fixture')\n"}
    for path, content in files.items():
        (root / "product" / path).write_text(content)
    (root / "docs/product.md").write_text("批准需求：展示 fixture")
    (root / "docs/dev-design.md").write_text("原生静态页面")
    with SessionLocal() as db:
        task = Task(task_name="repair fixture", workspace_path=str(root), status=TaskStatus.failed,
                    cur_step=Step.develop)
        db.add(task)
        db.flush()
        authorization = {"task_id": task.id, "provider": "deepseek", "historical_attempts": 7,
                         "total_limit": 10, "review_reserve": 1, "data_scope": "synthetic fixture only"}
        ref = "evidence/repair-authorization-fixture.json"
        (root / ref).write_text(json.dumps(authorization))
        event = Event(task_id=task.id, type="repair_request", data={"workflow": "repair-v1",
                      "feedback": "修复 fixture", "expected_task_version": task.version,
                      "budget_authorization_ref": ref})
        db.add(event)
        db.flush()
        monkeypatch.setattr(repair, "isolation_ready", lambda: True)
        repair.initialize(task, event)
        db.commit()
        yield root, db, task, event, tools
    for pid, process in tools._processes.items():
        if process.poll() is None:
            tools._exec("stop", process_id=pid)


def submit(root, task):
    """实际执行固定 Node 自测并调用原显式提交工具。"""
    paths = [str(p.relative_to(root)) for p in (root / "product").iterdir()]
    scoped = UnitTools(root, paths, paths, paths, paths, ["product/app.test.js"])
    result = scoped.execute(ToolCall("self-test", "run_unit_tests", {}))
    assert result.status == "succeeded" and result.output["passed"]
    result = scoped.execute(ToolCall("submit", "submit_unit_for_test", {}))
    assert result.status == "succeeded"
    repair.persist_submission(task, scoped)
    return scoped


def test_real_entry_refuses_until_execution_isolation_selected(attempt, monkeypatch):
    root, db, task, event, _ = attempt
    # 原尝试不动，另一个事件在真实门禁拒绝，不能沿新版本自动迁移。
    event2 = Event(task_id=task.id, type="repair_request", data=event.data)
    db.add(event2)
    db.flush()
    before = (root / repair.RUNTIME_PATH).read_bytes()
    monkeypatch.setattr(repair, "isolation_ready", lambda: False)
    worker.consume_event(db, event2, task)
    assert event2.status == EventStatus.rejected
    assert event2.error == "repair_execution_isolation_pending"
    assert task.status == TaskStatus.failed
    assert (root / repair.RUNTIME_PATH).read_bytes() == before


def test_same_event_keeps_original_attempt_and_budget(attempt):
    root, _, task, event, _ = attempt
    repair.reserve_request(root, "deepseek", "first")
    before = (root / repair.RUNTIME_PATH).read_bytes()
    assert repair.initialize(task, event)["budget"]["attempts_used"] == 8
    assert (root / repair.RUNTIME_PATH).read_bytes() == before


@pytest.mark.parametrize("field,value,reason", [
    ("expected_task_version", -1, "repair_task_version_mismatch"),
    ("feedback", "  ", "repair_feedback_required"),
    ("budget_authorization_ref", "evidence/../outside.json", "repair_authorization_ref_invalid"),
])
def test_bad_entry_does_not_change_runtime(attempt, field, value, reason):
    root, db, task, event, _ = attempt
    other = Event(task_id=task.id, type="repair_request", data={**event.data, field: value})
    db.add(other); db.flush()
    before = (root / repair.RUNTIME_PATH).read_bytes()
    with pytest.raises(ValueError, match=reason):
        repair.initialize(task, other)
    assert (root / repair.RUNTIME_PATH).read_bytes() == before


def test_new_budget_has_no_review_reserve_and_keeps_total_cap(attempt):
    """新尝试可用原总额度，不增加总上限或允许审查阶段调用。"""
    root, _, _, _, _ = attempt
    assert repair.load(root)['budget']['review_reserve'] == 0
    assert [repair.reserve_request(root, 'deepseek', 'execute') for _ in range(3)] == [8, 9, 10]
    with pytest.raises(repair.BudgetExceeded):
        repair.reserve_request(root, 'deepseek', 'overflow')
    state = repair.load(root)
    state['state'] = 'reviewing'
    repair.save(root, state)
    with pytest.raises(RuntimeError, match='repair_model_call_outside_phase'):
        repair.reserve_request(root, 'deepseek', 'review')


def test_budget_reserve_and_reload_never_reset_count(attempt):
    root, _, _, _, _ = attempt
    state = repair.load(root)
    state.pop('validation_policy')
    state['budget']['review_reserve'] = 1
    repair.save(root, state)
    assert repair.reserve_request(root, "deepseek", "retry-same-request") == 8
    assert repair.reserve_request(root, "deepseek", "retry-same-request") == 9
    with pytest.raises(repair.BudgetExceeded):
        repair.reserve_request(root, "deepseek", "blocked")
    state = repair.load(root)
    assert state["budget"]["attempts_used"] == 9
    assert state["budget"]["requests"][0]["status"] == "send_unknown"
    state["state"] = "reviewing"
    repair.save(root, state)
    assert repair.reserve_request(root, "deepseek", "review") == 10
    with pytest.raises(repair.BudgetExceeded):
        repair.reserve_request(root, "deepseek", "review-retry")


def test_provider_counts_actual_retry_and_does_not_send_after_budget(attempt, monkeypatch):
    root, db, task, _, _ = attempt
    state = repair.load(root)
    state.pop('validation_policy')
    state['budget']['review_reserve'] = 1
    repair.save(root, state)
    monkeypatch.setattr(DeepSeekRuntime, "get_api_key", lambda self: "fixture")
    sent = []

    class BrokenClient:
        """只替换外部传输，在实际 stream 边界观察已落盘的次数。"""
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def stream(self, *args, **kwargs):
            sent.append(repair.load(root)["budget"]["attempts_used"])
            raise httpx.ConnectError("fixture transport failure")

    monkeypatch.setattr("backend.app.runtime.model.httpx.Client", BrokenClient)
    request = ModelRequest("fixture", "fixture", {}, [], "same-logical-request")
    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            DeepSeekRuntime(db).call(task.id, request)
    with pytest.raises(repair.BudgetExceeded):
        DeepSeekRuntime(db).call(task.id, request)
    assert sent == [8, 9]
    assert all(item["status"] == "failed" for item in repair.load(root)["budget"]["requests"])


def test_budget_error_bypasses_worker_transport_retry(attempt, monkeypatch):
    root, db, task, _, tools = attempt
    calls = []
    class Runtime:
        provider = "deepseek"
        model_name = "fixture"
        def build_payload(self, request):
            return {}
        def call(self, *args):
            calls.append(1)
            raise repair.BudgetExceeded()
    monkeypatch.setattr(worker, "create_model_runtime", lambda *args: Runtime())
    run = worker.create_step_run(db, task)
    with pytest.raises(repair.BudgetExceeded):
        worker.model_tool_loop(db, task, run, "fixture", "fixture", {}, tools, tool_schemas=[])
    assert calls == [1]


def test_self_test_alone_does_not_submit(attempt):
    root, _, task, _, _ = attempt
    paths = ["product/app.test.js"]
    scoped = UnitTools(root, paths, paths, paths, paths, paths)
    assert scoped._run_unit_tests()["passed"]
    with pytest.raises(RuntimeError, match="self_test_required"):
        repair.persist_submission(task, scoped)
    assert repair.load(root)["state"] == "executing"


@pytest.mark.parametrize("mutation", ["new-file", "changed-code", "deleted-file", "changed-requirement", "changed-authorization"])
def test_frozen_submission_rejects_all_version_changes(attempt, mutation):
    root, _, task, _, _ = attempt
    submit(root, task)
    if mutation == "new-file":
        (root / "product/asset.txt").write_text("new")
    elif mutation == "changed-code":
        (root / "product/index.html").write_text("changed")
    elif mutation == "deleted-file":
        # 仅在测试临时夹具模拟外部删除，不删除项目文件。
        (root / "product/implementation.md").unlink()
    elif mutation == "changed-requirement":
        (root / "docs/product.md").write_text("new requirement")
    else:
        (root / "evidence/repair-authorization-fixture.json").write_text("{}")
    with pytest.raises(RuntimeError, match="version_changed"):
        repair.current_submission(root, repair.load(root))


def test_program_pipeline_uses_real_node_http_and_no_planner(attempt, monkeypatch):
    root, db, task, _, tools = attempt
    submit(root, task)
    task.status = TaskStatus.running
    task.cur_step = Step.test
    db.commit()
    monkeypatch.setattr(worker, "ToolRuntime", lambda _: tools)
    def forbidden(*args, **kwargs):
        raise AssertionError("fixed actions must not invoke Planner")
    monkeypatch.setattr(worker, "plan_bug_action", forbidden)
    monkeypatch.setattr(worker, "model_tool_loop", forbidden)
    browser_calls = []
    def browser(*args):
        browser_calls.append(1)
        return ToolResult("browser", "exec", "succeeded", {"exit_code": 0, "stdout": "PASS fixture"}), "fixture"
    monkeypatch.setattr(worker, "run_product_browser_validation", browser)
    for _ in range(3):
        assert worker.process_task(db)
        assert task.status != TaskStatus.failed, task.failure_reason
    assert task.status == TaskStatus.waiting_acceptance
    assert repair.load(root)["state"] == "awaiting_acceptance"
    assert browser_calls == [1]
    assert repair.load(root)["budget"]["attempts_used"] == 7
    assert len(db.scalars(select(StepRun)).all()) == 3
    with httpx.Client(trust_env=False) as client:
        assert client.get(task.result_url).text == "<h1>fixture</h1>"


def test_unknown_command_intent_stops_without_replay(attempt, monkeypatch):
    root, db, task, _, tools = attempt
    submit(root, task)
    state = repair.load(root)
    state.update(state="testing", intent="testing")
    repair.save(root, state)
    run = worker.create_step_run(db, task)
    def forbidden(*args):
        raise AssertionError("must not replay command")
    monkeypatch.setattr(worker, "execute_tool", forbidden)
    repair.pipeline(db, task, run, tools)
    assert task.status == TaskStatus.failed
    assert repair.load(root)["stop_reason"] == "unknown_side_effect"


def test_saved_stage_result_recovers_projection_without_retesting(attempt, monkeypatch):
    root, db, task, _, tools = attempt
    submit(root, task)
    state = repair.load(root)
    state.update(state="testing", intent="testing")
    repair.save(root, state)
    worker.write_json_atomic(root / state["validation_ref"], {
        "submission_id": state["submission_id"], "stages": {"testing": {"passed": True}}})
    run = worker.create_step_run(db, task)
    def forbidden(*args):
        raise AssertionError("saved result must not rerun")
    monkeypatch.setattr(worker, "execute_tool", forbidden)
    repair.pipeline(db, task, run, tools)
    assert repair.load(root)["state"] == "starting"
    assert task.cur_step == Step.start_product


def test_stale_acceptance_event_cannot_approve_current_submission(attempt):
    root, db, task, _, _ = attempt
    submit(root, task)
    state = repair.load(root)
    state["state"] = "awaiting_acceptance"
    repair.save(root, state)
    task.status = TaskStatus.waiting_acceptance
    event = Event(task_id=task.id, type="acceptance_result", data={"approved": True,
                  "submission_id": "stale", "expected_task_version": task.version})
    db.add(event); db.flush()
    worker.consume_event(db, event, task)
    assert event.status == EventStatus.rejected
    assert task.status == TaskStatus.waiting_acceptance


def test_old_workspace_does_not_create_new_state(tmp_path):
    assert repair.reserve_request(tmp_path, "deepseek", "legacy") is None
    assert repair.load(tmp_path) is None
    assert not (tmp_path / repair.RUNTIME_PATH).exists()


def test_submitted_file_tools_are_frozen(attempt):
    root, _, task, _, _ = attempt
    scoped = submit(root, task)
    result = scoped.execute(ToolCall("late-write", "write", {
        "path": "product/index.html", "content": "late change", "overwrite": True}))
    assert result.error == "repair_submission_frozen"
    assert (root / "product/index.html").read_text() == "<h1>fixture</h1>"


@pytest.mark.parametrize("stdout", ["# tests 0", "# tests 1\n# skipped 1", "# tests 1\n# todo 1"])
def test_zero_or_skipped_tests_cannot_advance(attempt, monkeypatch, stdout):
    root, db, task, _, tools = attempt
    submit(root, task)
    run = worker.create_step_run(db, task)
    monkeypatch.setattr(worker, "execute_tool", lambda *args: ToolResult(
        "test", "exec", "succeeded", {"exit_code": 0, "stdout": stdout}))
    repair.pipeline(db, task, run, tools)
    assert repair.load(root)["state"] == "executing"
    assert task.cur_step == Step.develop
    assert task.repair_round == 1
    assert run.error == "repair_testing_failed"


@pytest.mark.parametrize("status,output", [("failed", {}), ("succeeded", {"exit_code": 127})])
def test_environment_failure_does_not_request_product_repair(attempt, monkeypatch, status, output):
    root, db, task, _, tools = attempt
    submit(root, task)
    run = worker.create_step_run(db, task)
    monkeypatch.setattr(worker, "execute_tool", lambda *args: ToolResult(
        "test", "exec", status, output, error="node unavailable"))
    repair.pipeline(db, task, run, tools)
    assert repair.load(root)["stop_reason"] == "repair_test_environment_error"
    assert task.repair_round == 0
    assert task.status == TaskStatus.failed


def test_changes_during_test_invalidate_result(attempt, monkeypatch):
    root, db, task, _, tools = attempt
    submit(root, task)
    run = worker.create_step_run(db, task)
    def changed(*args):
        (root / "product/index.html").write_text("externally edited during test")
        return ToolResult("test", "exec", "succeeded", {"exit_code": 0, "stdout": "# tests 1"})
    monkeypatch.setattr(worker, "execute_tool", changed)
    repair.pipeline(db, task, run, tools)
    assert repair.load(root)["stop_reason"] == "repair_submission_version_changed"
    assert task.status == TaskStatus.failed


def test_real_browser_pipeline_waits_for_user_without_model_review(attempt, monkeypatch):
    """真实Chrome通过后直接待验收，原目标仅用户批准后关闭。"""
    root, db, task, _, tools = attempt
    (root / "product/index.html").write_text('<link rel="icon" href="data:,"><h1>fixture</h1>')
    script = '''import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(sys.argv[1])
    assert page.locator("h1").inner_text() == "fixture"
    assert errors == []
    browser.close()
print("PASS real Chrome and console checks")
'''
    (root / "product/verify_product.py").write_text(script)
    from backend.app.runtime.repair_objectives import capture, load as load_objectives
    capture(root, {"event_id": 99, "classification": "implementation_defect", "user_feedback": "展示 fixture"})
    submit(root, task)
    task.status = TaskStatus.running
    task.cur_step = Step.test
    db.commit()
    monkeypatch.setattr(worker, "ToolRuntime", lambda _: tools)
    def independent_review(*args, **kwargs):
        """任何模型审查调用都使回归失败，不能靠假审查通过。"""
        pytest.fail('new repair must not invoke model review')
    monkeypatch.setattr(worker, "model_tool_loop", independent_review)
    for _ in range(3):
        assert worker.process_task(db)
        assert task.status != TaskStatus.failed, task.failure_reason
    assert task.status == TaskStatus.waiting_acceptance
    assert load_objectives(root)["items"][0]["status"] == "open"
    assert 'reviewing' not in json.loads((root / repair.load(root)['validation_ref']).read_text())['stages']
    assert repair.load(root)["budget"]["attempts_used"] == 7
    # 用户验收还必须绑定当前提交和任务版本。
    event = Event(task_id=task.id, type="acceptance_result", data={"approved": True,
                  "submission_id": repair.load(root)["submission_id"], "expected_task_version": task.version})
    db.add(event); db.flush()
    worker.consume_event(db, event, task)
    assert task.status == TaskStatus.succeeded
    assert repair.load(root)["state"] == "accepted"
    objective = load_objectives(root)['items'][0]
    assert objective['status'] == 'closed' and objective['verification_source'] == 'user_acceptance'
    assert objective['acceptance_event_id'] == event.id


def test_review_missing_original_goal_returns_to_development(attempt, monkeypatch):
    root, db, task, _, tools = attempt
    from backend.app.runtime.repair_objectives import capture, load as load_objectives
    capture(root, {"event_id": 99, "classification": "implementation_defect", "user_feedback": "原始问题"})
    submit(root, task)
    state = repair.load(root)
    state.pop('validation_policy')
    state["state"] = "reviewing"
    repair.save(root, state)
    worker.write_json_atomic(root / state["validation_ref"], {"submission_id": state["submission_id"], "stages": {
        "testing": {"passed": True}, "starting": {"passed": True, "url": "http://127.0.0.1:1"},
        "verifying": {"passed": True, "result": ToolResult("browser", "exec", "succeeded",
                     {"exit_code": 0, "stdout": "PASS fixture"}).__dict__}}})
    monkeypatch.setattr(worker, "model_tool_loop", lambda *args, **kwargs: json.dumps({"results": [
        {"id": "E99-1", "covered": False, "reason": "原始问题没有覆盖"}]}))
    run = worker.create_step_run(db, task)
    repair.pipeline(db, task, run, tools)
    assert repair.load(root)["state"] == "executing"
    assert load_objectives(root)["items"][0]["original_feedback"] == "原始问题"
    assert load_objectives(root)["items"][0]["status"] == "open"
    assert task.cur_step == Step.develop


def test_api_explains_isolation_gate_without_enqueuing(attempt, monkeypatch):
    root, db, task, _, _ = attempt
    from fastapi import HTTPException
    from backend.app.api import create_event, get_task
    from backend.app.schemas import CreateEventRequest
    monkeypatch.setattr(repair, "isolation_ready", lambda: False)
    before = len(db.scalars(select(Event)).all())
    with pytest.raises(HTTPException) as exc:
        create_event(task.id, CreateEventRequest(type="repair_request", data={}), db)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "repair_execution_isolation_pending"
    assert len(db.scalars(select(Event)).all()) == before
    response = get_task(task.id, db)
    assert response.execution_mode == "repair-v1"
    assert response.budget["attempts_used"] == 7
    assert "requests" not in response.budget
    assert response.task_version == task.version


def test_worker_budget_stop_keeps_typed_reason_and_original_count(attempt, monkeypatch):
    root, db, task, _, _ = attempt
    task.status = TaskStatus.running
    db.commit()
    def exhausted(*args):
        raise repair.BudgetExceeded()
    from backend.app.runtime import repair_session
    monkeypatch.setattr(repair_session, "execute", exhausted)
    assert worker.process_task(db)
    assert task.failure_reason == "budget_exhausted"
    assert repair.load(root)["stop_reason"] == "budget_exhausted"
    assert repair.load(root)["budget"]["attempts_used"] == 7
    assert not worker.process_task(db)


def test_new_attempt_cannot_reset_saved_actual_attempts(attempt):
    root, db, task, event, _ = attempt
    repair.reserve_request(root, "deepseek", "spent")
    other = Event(task_id=task.id, type="repair_request", data=event.data)
    db.add(other); db.flush()
    with pytest.raises(ValueError, match="historical_attempts_mismatch"):
        repair.initialize(task, other)
    assert repair.load(root)["budget"]["attempts_used"] == 8


def test_successful_saved_stage_repairs_stale_step_before_new_run(attempt, monkeypatch):
    root, db, task, _, tools = attempt
    submit(root, task)
    task.status = TaskStatus.running
    task.cur_step = Step.develop
    db.commit()
    assert worker.process_task(db)
    assert db.scalars(select(StepRun)).first().step == Step.test
    assert repair.load(root)["state"] == "starting"


def test_old_step_projection_cannot_bypass_explicit_submission(attempt, monkeypatch):
    root, db, task, _, _ = attempt
    task.status = TaskStatus.running
    task.cur_step = Step.test
    db.commit()
    def forbidden(*args):
        raise AssertionError("unsubmitted code must not enter validation")
    monkeypatch.setattr(worker, "handle_test", forbidden)
    assert worker.process_task(db)
    assert task.status == TaskStatus.failed
    assert repair.load(root)["stop_reason"] == "repair_submission_required"
