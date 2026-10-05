import json
from pathlib import Path
import pytest

from backend.app.runtime.context_relay import DeepSeekContextRelay
from backend.app.runtime.contracts import ToolCall
from backend.app.runtime.unit_workflow import UnitTools
from backend.app.runtime.worker import duplicate_read_error


def entry(tools, request_id, call_id, name, parameters):
    call = ToolCall(call_id, name, parameters)
    return {"model_request_id": request_id, "action": call.__dict__,
            "reasoning_content": "保留的历史思考", "result": tools.execute(call).__dict__}


def test_relay_refreshes_merged_known_ranges_and_restores_complete_boundary(tmp_path):
    tools = UnitTools(tmp_path, ["product/a.js"], ["product/b.js"])
    tools._write("product/a.js", "one\ntwo\nthree\nfour\nfive\n", False)
    (tmp_path / "product/b.js").write_text("dependency\n")
    history = [entry(tools, "read", "r1", "read", {"path": "product/a.js", "start_line": 1, "end_line": 2}),
               entry(tools, "read", "r2", "read", {"path": "product/a.js", "start_line": 2, "end_line": 3}),
               entry(tools, "read", "r3", "read", {"path": "product/b.js"}),
               entry(tools, "edit", "w1", "replace", {"path": "product/a.js", "old": "two", "new": "TWO"})]
    original = json.dumps(history)
    relay = DeepSeekContextRelay(tools, 7, "repair")
    relay.complete_batch(history, "edit", ["w1"], {"detail_path": "evidence/diagnostic.json"})
    replay, context = relay.project(history)
    assert replay == []
    files = {value["path"]: value for value in context["carried_file_context"]}
    assert files["product/a.js"]["content"] == "one\nTWO\nthree\n"
    assert files["product/a.js"]["covered_end_line"] == 3
    assert files["product/b.js"]["content"] == "dependency\n"
    assert duplicate_read_error(ToolCall("repeat", "read", {"path": "product/a.js", "start_line": 2, "end_line": 3}), history, context, tools)
    assert duplicate_read_error(ToolCall("new", "read", {"path": "product/a.js", "start_line": 4, "end_line": 5}), history, context, tools) is None
    assert duplicate_read_error(ToolCall("whole", "read", {"path": "product/a.js"}), history, context, tools) is None
    later = entry(tools, "next", "r4", "read", {"path": "product/a.js", "start_line": 4, "end_line": 5})
    restored = DeepSeekContextRelay(tools, 7, "repair")
    assert restored.project(history + [later])[0] == [later]
    assert json.dumps(history) == original
    # 同一边界缺任意结果时拒绝切开，不能重建成半批协议消息。
    incomplete = [*history[:-1], {**history[-1], "result": None}]
    assert restored.project(incomplete) == (incomplete, {})


def test_relay_does_not_claim_truncated_missing_or_out_of_scope_files(tmp_path):
    tools = UnitTools(tmp_path, ["product/large.js", "product/missing.js"], [])
    content = "a" * (110 * 1024) + "\nlast\n"
    history = [entry(tools, "write", "w", "write", {"path": "product/large.js", "content": content, "overwrite": False})]
    relay = DeepSeekContextRelay(tools, 8, "repair")
    relay.complete_batch(history, "write", ["w"], {})
    _, context = relay.project(history)
    carried = context["carried_file_context"][0]
    assert carried["truncated"] is True and carried["covered_end_line"] == 0
    assert duplicate_read_error(ToolCall("read", "read", {"path": "product/large.js", "start_line": 1, "end_line": 1}), history, context, tools) is None
    partial = entry(tools, "read", "partial", "read", {"path": "product/large.js", "start_line": 1, "end_line": 2})
    assert duplicate_read_error(ToolCall("read", "read", {"path": "product/large.js", "start_line": 1, "end_line": 1}),
                                [partial], {"reasoning_tool_history": [partial]}, tools) is None
    # 读取范围恢复后仍按当前权限和路径检查，缺失内容也不作为正文。
    history = [entry(tools, "missing", "m", "write", {"path": "product/missing.js", "content": "known", "overwrite": False})]
    relay.complete_batch(history, "missing", ["m"], {})
    (tmp_path / "product/missing.js").rename(tmp_path / "product/moved.js")
    _, context = relay.project(history)
    assert context["carried_file_context"][0]["status"] == "unavailable"
    tools.readable.clear()
    _, context = relay.project(history)
    assert "content" not in context["carried_file_context"][0]


def test_relay_carries_diagnostic_references_without_old_report_bodies(tmp_path):
    """旧诊断不得冒充当前代码知识；报告原文仍可按原权限读取。"""
    old = "evidence/slice-repair-diagnostic-7-old.json"
    current = "evidence/slice-repair-diagnostic-7-current.json"
    tools = UnitTools(tmp_path, ["product/a.js"], [old, current, "evidence/contract.json"])
    tools._write("product/a.js", "before", False)
    for path, body in [(old, '"obsolete failure"'), (current, '"current detail"'),
                       ("evidence/contract.json", '"approved contract"')]:
        (tmp_path / path).write_text(body)
    history = [entry(tools, "read", name, "read", {"path": path})
               for name, path in [("old", old), ("current", current), ("contract", "evidence/contract.json")]]
    history.append(entry(tools, "edit", "write", "write", {
        "path": "product/a.js", "content": "after", "overwrite": True}))
    original = json.dumps(history)
    relay = DeepSeekContextRelay(tools, 7, "repair")
    relay.complete_batch(history, "edit", ["write"], {"detail_path": current})
    _, context = relay.project(history)
    assert {item["path"] for item in context["carried_file_context"]} == {
        "product/a.js", "evidence/contract.json"}
    refs = {item["path"]: item for item in context["diagnostic_report_refs"]}
    assert refs[old]["relation_to_boundary"] == "historical_report"
    assert refs[current]["relation_to_boundary"] == "boundary_diagnostic"
    assert "obsolete failure" not in json.dumps(context)
    assert duplicate_read_error(ToolCall("lookup", "read", {"path": old}), history, context, tools) is None
    assert tools.execute(ToolCall("lookup", "read", {"path": old})).output["content"] == '"obsolete failure"'
    assert json.dumps(history) == original


def test_worker_restart_preserves_relay_budget_and_does_not_repeat_write(tmp_path, monkeypatch):
    from backend.app.database import Base, SessionLocal, engine
    from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
    from backend.app.runtime import worker
    from backend.app.runtime.contracts import ModelResult
    from backend.app.runtime.model import build_messages
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    tools = UnitTools(tmp_path, ["product/a.js"], [], self_test_files=["product/a.js"])
    tools._write("product/a.js", "before", False)
    requests = []
    writes = []
    original_execute = worker.execute_tool

    def execute(*args, **kwargs):
        if args[4].tool_name == "write":
            writes.append(args[4].call_id)
        return original_execute(*args, **kwargs)

    def diagnostic():
        versions = tools.self_test_versions()
        return {"passed": False, "file_hashes_before": versions, "file_hashes_after": versions,
                "detail_path": "evidence/diagnostic.json"}

    def call(runtime, task_id, request):
        requests.append(request)
        assert request.context["model_call_budget"] == {
            "unit": "logical_model_call", "limit": 100, "used_including_current": len(requests),
            "remaining_after_current": 100 - len(requests), "transport_retries_counted": False}
        if len(requests) == 1:
            return ModelResult(request.request_id, 1, "", [
                ToolCall("read", "read", {"path": "product/a.js"}),
                ToolCall("write", "write", {"path": "product/a.js", "content": "after", "overwrite": True})],
                "tool_calls", {"reasoning_content": "首轮完整思考"})
        if len(requests) == 2:
            raise RuntimeError("simulated_worker_exit")
        assert len(build_messages(request, include_reasoning=True)) == 2
        assert request.context["carried_file_context"][0]["content"] == "after"
        assert request.context["repair_task"]["goal"] == "original goal"
        return ModelResult(request.request_id, 1, "BLOCKED:测试结束", [], "stop")

    monkeypatch.setattr(worker, "execute_tool", execute)
    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", call)
    with SessionLocal() as db:
        task = Task(task_name="resume", cur_step=Step.develop, status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                      checkpoint_path=str(tmp_path / "evidence/checkpoint.json"))
        db.add(run); db.commit()
        context = {"repair_task": {"goal": "original goal"}, "unit_file_scope": ["product/a.js"],
                   "owned_files": ["product/a.js"], "require_unit_submission": True, "unit_diagnostic": diagnostic()}
        args = (db, task, run, "repair", "input", context, tools)
        with pytest.raises(RuntimeError, match="model_transport_failed"):
            worker.model_tool_loop(*args, history_key="repair", refresh_diagnostic=diagnostic)
        assert run.model_call_count == 2
        saved = Path(run.checkpoint_path).read_text()
        assert worker.model_tool_loop(*args, history_key="repair", refresh_diagnostic=diagnostic) == "BLOCKED:测试结束"
        assert run.model_call_count == 3 and writes == ["write"]
        assert Path(run.checkpoint_path).read_text() == saved
