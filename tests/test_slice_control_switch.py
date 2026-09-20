"""用真实 Node 测试验证推进违约后的切换、权限、预算与恢复。"""

import json
import pytest

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime import slice_workflow as sw, worker
from backend.app.runtime.contracts import ModelResult, ToolCall
from backend.app.runtime.unit_workflow import file_hashes, test_passed as node_passed
from backend.app.runtime.tools import ToolRuntime


CORE = "exports.required = v => typeof v === 'string' && v.trim().length > 0;\n"
IMPLEMENTATION = """const {required} = require('./core.cjs');
exports.add = value => { if (!required(value)) throw Error('title'); return value.trim(); };
"""
TEST = """const {test} = require('node:test'); const assert = require('node:assert/strict');
const {add} = require('./materials.cjs');
test('valid, invalid, and recovery', () => {
  assert.equal(add(' first '), 'first'); assert.throws(() => add('  '), /title/);
  assert.equal(add('recovered'), 'recovered');
});
"""


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def fixture(db, root):
    """创建已通过基础依赖和未实现素材卡，不预写待测实现。"""
    tools = ToolRuntime(root)
    files = {
        "product/core.cjs": CORE,
        "product/core.test.cjs": "const {test}=require('node:test'); const assert=require('node:assert/strict');"
                                 "test('required',()=>assert.equal(require('./core.cjs').required(''),false));",
        "product/materials.cjs": "exports.add = () => { throw Error('NotImplemented'); };\n",
        "product/materials.test.cjs": "require('node:test').test.todo('valid, invalid, and recovery');\n",
    }
    for path, content in files.items():
        (root / path).write_text(content)
    card = {"id": "materials-library", "goal": "保存非空标题，拒绝空标题且错误后可恢复",
            "owners": ["materials"], "interfaces": ["Materials.add(value)"],
            "required_interfaces": ["Materials.add(value)", "Validate.required(value)"],
            "implementation_files": ["product/materials.cjs"], "test_files": ["product/materials.test.cjs"],
            "acceptance": ["保存标题，空标题失败，之后可正常保存"],
            "acceptance_interfaces": [{"acceptance": "保存标题，空标题失败，之后可正常保存",
                                       "interfaces": ["Materials.add(value)", "Validate.required(value)"]}]}
    scaffold = {"modules": [
        {"id": "core", "interfaces": ["Validate.required(value)"],
         "implementation_files": ["product/core.cjs"], "test_file": "product/core.test.cjs"},
        {"id": "materials", "interfaces": card["interfaces"],
         "implementation_files": card["implementation_files"], "test_file": card["test_files"][0]},
    ]}
    (root / "docs/scaffold-contract.json").write_text(json.dumps(scaffold))
    core_test = tools.execute(ToolCall('initial-test', 'exec', {'action': 'run', 'command': 'node --test core.test.cjs'}))
    versions = file_hashes(root, list(files))
    assert node_passed(core_test, versions, versions)
    completed = [{"status": "passed", "card": {"id": "core", "goal": "校验非空", "owners": ["core"],
                   "interfaces": ["Validate.required(value)"], "implementation_files": ["product/core.cjs"],
                   "test_files": ["product/core.test.cjs"], "acceptance": ["校验非空"]},
                  "file_hashes": versions, "test": {"passed": True}}]
    task = Task(task_name="slice switch", cur_step=Step.develop, status=TaskStatus.running,
                workspace_path=str(root))
    db.add(task); db.flush()
    run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                  checkpoint_path=str(root / "evidence/checkpoint.json"))
    db.add(run); db.commit()
    scoped = sw.SliceTools(root, card["implementation_files"] + card["test_files"], list(files),
                          submission_files=card["implementation_files"] + card["test_files"],
                          self_test_files=list(files), test_files=["product/core.test.cjs"] + card["test_files"])
    return task, run, card, completed, scoped


def fake_developer(monkeypatch, implement):
    """前三批复现重复读取，之后将调用交给具体实现情景。"""
    calls = []

    def call(runtime, task_id, request):
        calls.append(request)
        if request.context.get("require_unit_submission"):
            assert len(calls) <= 3, "旧对话不得继续第四次调用"
            actions = [ToolCall(f"read-{len(calls)}", "read", {"path": "product/core.cjs"})]
            if len(calls) == 3:
                actions.append(ToolCall("discard-old-write", "write", {
                    "path": "product/materials.cjs", "content": "old dialogue must stop", "overwrite": True}))
            return ModelResult(request.request_id, len(calls), "OLD_DIALOGUE_MARKER", actions, "tool_calls")
        assert request.context["tool_history"] == []
        assert request.context.get("tool_summaries", []) == []
        assert "OLD_DIALOGUE_MARKER" not in json.dumps(request.context)
        assert request.context["current_product_files"]["product/core.cjs"] == CORE
        assert {s["function"]["name"] for s in request.tools} == {"write", "replace", "request_slice_replan"}
        return implement(request, len(calls) - 3)

    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", call)
    return calls


def writes(request, implementation=IMPLEMENTATION, test=TEST):
    return ModelResult(request.request_id, 1, "", [
        ToolCall("implementation", "write", {"path": "product/materials.cjs", "content": implementation, "overwrite": True}),
        ToolCall("tests", "write", {"path": "product/materials.test.cjs", "content": test, "overwrite": True}),
    ], "tool_calls")


def run_fixture(db, parts):
    task, run, card, completed, scoped = parts
    return sw.run_slice_developer(db, task, run, card, completed, scoped, "slice:materials-library:1")


def saved(root):
    return json.loads(next((root / "evidence/slices").glob("developer-*.json")).read_text())


def test_switch_runs_complete_batch_tests_submits_and_restores_without_calls(tmp_path, monkeypatch):
    calls = fake_developer(monkeypatch, lambda request, index: writes(request))
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        assert run_fixture(db, parts) == "SUBMITTED_FOR_TEST"
        state = saved(tmp_path)
        assert state["used_calls"] == 1 and state["phase"] == "submitted"
        assert state["submission"]["self_test"]["passed"] is True
        assert state["inputs"]["interface_files"]["Validate.required(value)"]["implementation_files"] == ["product/core.cjs"]
        assert len(calls) == parts[1].model_call_count == 4
        assert (tmp_path / "product/core.cjs").read_text() == CORE
        parts[-1].submitted_hashes = None
        assert run_fixture(db, parts) == "SUBMITTED_FOR_TEST"
        assert len(calls) == 4 and parts[-1].submitted_hashes
        # 按原独立回归再次运行实际 Node，不能只依赖提交状态。
        before = file_hashes(tmp_path, parts[-1].self_test_files)
        result = ToolRuntime(tmp_path).execute(ToolCall('independent', 'exec', {
            'action': 'run', 'command': parts[-1].self_test_command()}))
        assert node_passed(result, before, file_hashes(tmp_path, parts[-1].self_test_files))


def test_failed_test_uses_fresh_evidence_in_new_call(tmp_path, monkeypatch):
    def implement(request, index):
        if index == 1:
            return writes(request, "exports.add = value => value;\n")
        assert request.context["unit_test_feedback"]["passed"] is False
        assert "first" in request.context["unit_test_feedback"]["result"]["output"]["stdout"]
        assert request.context["current_product_files"]["product/materials.cjs"] == "exports.add = value => value;\n"
        return writes(request)

    calls = fake_developer(monkeypatch, implement)
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        assert run_fixture(db, parts) == "SUBMITTED_FOR_TEST"
        assert saved(tmp_path)["used_calls"] == 2 and len(calls) == 5


@pytest.mark.parametrize("problem", ["missing", "stale", "unknown"])
def test_invalid_dependency_blocks_before_restricted_model(tmp_path, monkeypatch, problem):
    calls = fake_developer(monkeypatch, lambda request, index: pytest.fail("invalid dependency must block"))
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        if problem == "missing":
            contract = json.loads((tmp_path / "docs/scaffold-contract.json").read_text())
            contract["modules"][0]["implementation_files"] = ["product/missing.cjs"]
            parts[3][0]["card"]["implementation_files"] = ["product/missing.cjs"]
            parts[-1].readable.add(tmp_path / "product/missing.cjs")
            (tmp_path / "docs/scaffold-contract.json").write_text(json.dumps(contract))
        elif problem == "stale":
            parts[3][0]["file_hashes"]["product/core.cjs"] = "outdated"
        else:
            parts[2]["required_interfaces"].append("Unknown.api()")
        with pytest.raises(ValueError, match="slice_(dependency|required_interface)"):
            run_fixture(db, parts)
        assert len(calls) == 3 and saved(tmp_path)["used_calls"] == 0


def test_restricted_tools_reject_reads_exec_submission_and_dependency_write(tmp_path):
    with SessionLocal() as db:
        *_, scoped = fixture(db, tmp_path)
        restricted = sw.RestrictedImplementationTools(tmp_path, scoped.submission_files, ["product/core.cjs"])
        for name in ["read", "exec", "run_unit_tests", "submit_unit_for_test", "get_tool_execution_detail"]:
            result = restricted.execute(ToolCall(name, name, {}))
            assert result.error == "restricted_implementation_tool_not_allowed"
        result = restricted.execute(ToolCall("dependency", "write", {
            "path": "product/core.cjs", "content": "changed", "overwrite": True}))
        assert result.error == "unit_write_outside_owned_files"
        assert (tmp_path / "product/core.cjs").read_text() == CORE


@pytest.mark.parametrize("no_change", ["read", "text"])
def test_no_change_stops_without_restarting_same_attempt(tmp_path, monkeypatch, no_change):
    def implement(request, index):
        actions = [ToolCall('illegal', 'read', {'path': 'product/core.cjs'})] if no_change == 'read' else []
        return ModelResult(request.request_id, 1, "I will implement", actions, "completed")
    calls = fake_developer(monkeypatch, implement)
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="slice_restricted_no_file_change"):
                run_fixture(db, parts)
        assert len(calls) == 4 and saved(tmp_path)["used_calls"] == 1


def test_four_call_budget_cannot_reset_on_resume(tmp_path, monkeypatch):
    calls = fake_developer(monkeypatch, lambda request, index: writes(
        request, f"exports.add = () => {index};\n"))
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="slice_restricted_call_budget_exceeded"):
                run_fixture(db, parts)
        assert saved(tmp_path)["used_calls"] == 4 and len(calls) == 7
        assert parts[-1].submitted_hashes is None


def test_step_budget_is_shared_with_old_dialogue(tmp_path, monkeypatch):
    calls = fake_developer(monkeypatch, lambda request, index: writes(request, "exports.add = () => 0;\n"))
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        parts[1].model_call_count = worker.MAX_MODEL_CALLS_PER_STEP - 4
        db.commit()
        with pytest.raises(RuntimeError, match="model_call_limit_exceeded"):
            run_fixture(db, parts)
        assert saved(tmp_path)["used_calls"] == 1 and len(calls) == 4


def test_todo_is_never_submitted(tmp_path, monkeypatch):
    calls = fake_developer(monkeypatch, lambda request, index: writes(
        request, IMPLEMENTATION + f"// round {index}\n", "require('node:test').test.todo('unfinished');\n"))
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        with pytest.raises(RuntimeError, match="slice_restricted_call_budget_exceeded"):
            run_fixture(db, parts)
        assert parts[-1].submitted_hashes is None and len(calls) == 7


@pytest.mark.parametrize("signal", ["replan", "blocked"])
def test_replan_or_business_block_stops_and_persists(tmp_path, monkeypatch, signal):
    def implement(request, index):
        actions = [ToolCall('replan', 'request_slice_replan', {'reason': 'need topic interface'})] if signal == 'replan' else []
        return ModelResult(request.request_id, 1, "BLOCKED: need a business decision", actions, "completed")
    calls = fake_developer(monkeypatch, implement)
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        first = run_fixture(db, parts)
        assert first.startswith("REPLAN:" if signal == 'replan' else "BLOCKED:")
        assert run_fixture(db, parts) == first
        assert len(calls) == 4 and saved(tmp_path)["phase"] == signal


@pytest.mark.parametrize("interrupt_phase", ["tested", "implementing"])
def test_crash_does_not_repeat_model_or_reset_budget(tmp_path, monkeypatch, interrupt_phase):
    calls = fake_developer(monkeypatch, lambda request, index: writes(request))
    original = worker.write_json_atomic
    interrupted = False

    def interrupt(path, value):
        nonlocal interrupted
        original(path, value)
        if str(path.name).startswith('developer-') and value.get('phase') == interrupt_phase and not interrupted:
            interrupted = True
            raise SystemExit('simulated process termination')

    monkeypatch.setattr(worker, 'write_json_atomic', interrupt)
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        with pytest.raises(SystemExit):
            run_fixture(db, parts)
        before = len(calls)
        if interrupt_phase == 'tested':
            assert run_fixture(db, parts) == 'SUBMITTED_FOR_TEST'
        else:
            with pytest.raises(RuntimeError, match='slice_restricted_no_file_change'):
                run_fixture(db, parts)
        assert len(calls) == before and saved(tmp_path)['used_calls'] == 1


def test_crash_after_guard_recovers_switch_without_old_dialogue_call(tmp_path, monkeypatch):
    calls = fake_developer(monkeypatch, lambda request, index: writes(request))
    original = worker.write_json_atomic
    interrupted = False

    def interrupt(path, value):
        nonlocal interrupted
        if path.name.startswith('developer-') and not interrupted:
            interrupted = True
            raise SystemExit('before switch state save')
        original(path, value)

    monkeypatch.setattr(worker, 'write_json_atomic', interrupt)
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        with pytest.raises(SystemExit):
            run_fixture(db, parts)
        assert len(calls) == 3
        assert run_fixture(db, parts) == 'SUBMITTED_FOR_TEST'
        assert len(calls) == 4


def test_handle_develop_resumes_same_attempt_and_runs_independent_regression(tmp_path, monkeypatch):
    calls = fake_developer(monkeypatch, lambda request, index: writes(request))
    with SessionLocal() as db:
        parts = fixture(db, tmp_path)
        task, run, card, completed, scoped = parts
        assert run_fixture(db, parts) == 'SUBMITTED_FOR_TEST'
        current = {'card': card, 'card_path': 'docs/slices/materials.json', 'status': 'developing', 'attempt': 1}
        progress = {'slices': completed + [current]}
        for entry in completed:
            entry['card_path'] = 'docs/slices/core.json'
        plan = {'product_hash': 'product', 'architecture_hash': 'architecture'}
        monkeypatch.setattr(sw, 'load_delivery_plan', lambda root: plan)
        monkeypatch.setattr(sw, '_progress', lambda root, plan: progress)
        monkeypatch.setattr(sw, 'plan_next_slice', lambda *args, **kwargs: {
            'action': 'complete', 'coverage_summary': ['materials verified']})
        monkeypatch.setattr(worker, 'missing_product_files', lambda root: [])
        sw.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert len(calls) == 4 and current['attempt'] == 1
        assert current['status'] == 'passed' and current['test']['passed'] is True
        assert task.cur_step == Step.test
