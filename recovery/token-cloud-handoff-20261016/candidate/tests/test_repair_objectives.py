import json
from types import SimpleNamespace

from backend.app.runtime import repair_objectives, worker
from backend.app.runtime.contracts import ToolResult


def fixture(tmp_path):
    (tmp_path / "product").mkdir()
    (tmp_path / "evidence").mkdir()
    (tmp_path / "product/index.html").write_text("original")
    (tmp_path / "product/verify_product.py").write_text(
        "page.get_by_role('button', name='编辑').click()\n"
        "assert page.locator('#note').inner_text() == '新笔记'\n")
    (tmp_path / "evidence/verification-report.md").write_text("素材缺编辑入口")
    task = SimpleNamespace(workspace_path=str(tmp_path), repair_round=1)
    triage = {"event_id": 7, "classification": "implementation_defect",
              "user_feedback": "已有素材无法编辑，编辑并保存后应看到新笔记。",
              "changes": [{"current_behavior": "素材缺编辑入口", "expected_behavior": "已有素材可编辑并保存",
                           "acceptance_examples": ["打开已有素材，修改笔记，保存后再次查看"]}]}
    repair_objectives.capture(tmp_path, triage)
    return task, triage


def test_latest_script_error_cannot_replace_original_goal(tmp_path):
    task, triage = fixture(tmp_path)
    (tmp_path / "evidence/verification-report.md").write_text("脚本 URL 参数错误")
    repair_objectives.capture(tmp_path, {**triage, "user_feedback": "被覆盖的反馈"})
    repair_objectives.record_blocker(task, "verification_script_positional_url_required")
    ledger = repair_objectives.load(tmp_path)
    assert len(ledger["items"]) == 1
    assert ledger["items"][0]["original_feedback"] == triage["user_feedback"]
    assert ledger["items"][0]["original_verification_report"] == "素材缺编辑入口"
    assert ledger["blockers"][0]["reason"] == "verification_script_positional_url_required"


def test_browser_failure_cannot_close_goal_or_call_reviewer(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path)
    monkeypatch.setattr(worker, "model_tool_loop", lambda *a, **kw: (_ for _ in ()).throw(AssertionError()))
    result = ToolResult("x", "exec", "failed", {"exit_code": 1})
    assert not repair_objectives.verify(None, task, None, None, result)
    assert repair_objectives.pending(task)[0]["status"] == "open"


def test_generic_pass_and_missing_edit_assertion_leave_goal_open(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path)
    monkeypatch.setattr(worker, "model_tool_loop", lambda *a, **kw: json.dumps({"results": [
        {"id": "E7-1", "covered": False, "reason": "脚本只检查页面标题，没有编辑操作"}]}))
    monkeypatch.setattr(worker, "safe_record_trace", lambda *a, **kw: None)
    db = SimpleNamespace(commit=lambda: None)
    run = SimpleNamespace(id=1)
    result = ToolResult("x", "exec", "succeeded", {"exit_code": 0})
    assert not repair_objectives.verify(db, task, run, None, result)
    assert repair_objectives.pending(task)[0]["latest_review"]["covered"] is False


def test_false_script_quote_cannot_close_goal(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path)
    monkeypatch.setattr(worker, "model_tool_loop", lambda *a, **kw: json.dumps({"results": [
        {"id": "E7-1", "covered": True, "reason": "声称已测", "operation_quote": "不存在的操作",
         "assertion_quote": "不存在的断言"}]}))
    monkeypatch.setattr(worker, "safe_record_trace", lambda *a, **kw: None)
    result = ToolResult("x", "exec", "succeeded", {"exit_code": 0})
    assert not repair_objectives.verify(SimpleNamespace(commit=lambda: None), task,
                                        SimpleNamespace(id=1), None, result)
    assert repair_objectives.pending(task)


def test_closed_goal_reopens_when_script_or_product_changes(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path)
    script = (tmp_path / "product/verify_product.py").read_text().splitlines()
    monkeypatch.setattr(worker, "model_tool_loop", lambda *a, **kw: json.dumps({"results": [
        {"id": "E7-1", "covered": True, "reason": "实际编辑和新笔记断言", "operation_quote": script[0],
         "assertion_quote": script[1]}]}))
    monkeypatch.setattr(worker, "safe_record_trace", lambda *a, **kw: None)
    result = ToolResult("x", "exec", "succeeded", {"exit_code": 0})
    assert repair_objectives.verify(SimpleNamespace(commit=lambda: None), task,
                                    SimpleNamespace(id=1), None, result)
    assert not repair_objectives.pending(task)
    (tmp_path / "product/verify_product.py").write_text("pass")
    assert repair_objectives.pending(task)
