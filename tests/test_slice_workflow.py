import json
from pathlib import Path

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime import slice_workflow, worker
from backend.app.runtime.tools import ToolRuntime


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def make_task(db, root: Path, step: Step):
    (root / "docs").mkdir(parents=True)
    (root / "docs/product.md").write_text("实现可保存的素材新增和列表展示。", encoding="utf-8")
    (root / "docs/architecture.md").write_text(
        "materials 拥有素材数据，提供 create/list；storage 拥有持久化。", encoding="utf-8")
    task = Task(task_name="slice", status=TaskStatus.running, cur_step=step, workspace_path=str(root))
    db.add(task); db.flush()
    run = StepRun(task_id=task.id, step=step, status=StepStatus.running, attempt=1,
                  checkpoint_path=str(root / "evidence/checkpoint.json"))
    db.add(run); db.commit()
    return task, run


def card():
    return {
        "id": "material-create",
        "goal": "用户新增素材后可以看到并在刷新后保留",
        "owners": ["materials", "storage"],
        "interfaces": ["materials.create", "materials.list", "storage.save"],
        "implementation_files": [
            "product/index.html", "product/materials.js", "product/implementation.md",
            "product/verify_product.py",
        ],
        "test_files": ["product/material-create.test.js"],
        "acceptance": ["新增素材后列表展示", "刷新后素材仍存在", "空标题失败后可以继续新增"],
        "reason": "形成第一个端到端业务结果",
    }


def test_card_rejects_test_or_document_only_slice():
    value = card()
    value["id"] = "verification-only"
    try:
        slice_workflow.validate_card(value, set())
        assert False, "verification slice must be rejected"
    except ValueError as exc:
        assert str(exc) == "slice_non_business_id"


def test_internal_validation_error_cannot_be_escalated_to_user(tmp_path, monkeypatch):
    """纯验证切片被拒后必须由 Planner自行修正，不能转成用户澄清。"""
    responses = [
        {"action": "implement", "card": {**card(), "id": "browser-verification"}},
        {"action": "clarify", "question": "请用户决定是否修正内部切片 ID"},
        {"action": "implement", "card": {**card(), "id": "app-delivery"}},
    ]

    def fake_loop(*args, **kwargs):
        return json.dumps(responses.pop(0), ensure_ascii=False)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.dev_design)
        slice_workflow.ensure_delivery_plan(db, task, run, ToolRuntime(tmp_path))
        plan = slice_workflow.load_delivery_plan(tmp_path)
        progress = {"workflow": "slice-v1", "product_hash": plan["product_hash"],
                    "architecture_hash": plan["architecture_hash"], "slices": [], "complete": False}
        decision = slice_workflow.plan_next_slice(db, task, run, ToolRuntime(tmp_path), plan, progress)
        assert decision["card"]["id"] == "app-delivery"
        assert task.status == TaskStatus.running


def test_complete_with_missing_product_entries_is_corrected_to_delivery_slice(tmp_path, monkeypatch):
    """固定产品入口缺失时不得结束任务，Planner 必须继续规划交付切片。"""
    responses = [
        {"action": "complete", "coverage_summary": ["业务能力已覆盖"]},
        {"action": "clarify", "question": "是否需要固定入口"},
        {"action": "implement", "card": {**card(), "id": "app-delivery"}},
    ]

    def fake_loop(*args, **kwargs):
        context = args[5]
        assert "verify_product.py" in context["missing_product_entries"]
        assert "implementation.md" in context["missing_product_entries"]
        return json.dumps(responses.pop(0), ensure_ascii=False)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.dev_design)
        (tmp_path / "product").mkdir()
        (tmp_path / "product/index.html").write_text("<!doctype html><main>ok</main>", encoding="utf-8")
        (tmp_path / "product/product.test.js").write_text("", encoding="utf-8")
        slice_workflow.ensure_delivery_plan(db, task, run, ToolRuntime(tmp_path))
        plan = slice_workflow.load_delivery_plan(tmp_path)
        progress = {"workflow": "slice-v1", "product_hash": plan["product_hash"],
                    "architecture_hash": plan["architecture_hash"], "slices": [], "complete": False}
        decision = slice_workflow.plan_next_slice(db, task, run, ToolRuntime(tmp_path), plan, progress)
        assert decision["card"]["id"] == "app-delivery"
        assert task.status == TaskStatus.running


def test_slice_workflow_plans_one_slice_then_uses_real_test_before_next(tmp_path, monkeypatch):
    planner_calls = 0

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        nonlocal planner_calls
        if getattr(instructions, "name", None) == "slice-planner":
            planner_calls += 1
            if planner_calls == 1:
                return json.dumps({"action": "implement", "card": card()}, ensure_ascii=False)
            assert context["passed_slices"][0]["card"]["id"] == "material-create"
            assert context["latest_test_result"]["passed"] is True
            return json.dumps({"action": "complete", "coverage_summary": [
                "material-create 的真实测试覆盖新增、列表、持久化和错误恢复",
            ]}, ensure_ascii=False)
        assert getattr(instructions, "name", None) == "slice-developer"
        contents = {
            "product/index.html": "<!doctype html><main>Materials</main>",
            "product/materials.js": "export const create = x => x;\n",
            "product/implementation.md": "# Implementation\n",
            "product/verify_product.py": "print('ok')\n",
            "product/material-create.test.js": (
                "const test=require('node:test');const assert=require('node:assert');"
                "test('material create',()=>assert.equal(1,1));\n"
            ),
        }
        for path, content in contents.items():
            result = tools._write(path, content, False)
            assert result["path"] == path
        tested = tools._run_unit_tests()
        assert tested["passed"] is True
        tools._submit_unit_for_test()
        return "SUBMITTED"

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, architecture_run = make_task(db, tmp_path, Step.architecture_docs)
        slice_workflow.ensure_delivery_plan(db, task, architecture_run, ToolRuntime(tmp_path))
        architecture_run.status = StepStatus.succeeded
        design_run = StepRun(task_id=task.id, step=Step.dev_design, status=StepStatus.running, attempt=1,
                             checkpoint_path=str(tmp_path / "evidence/design.json"))
        db.add(design_run); task.cur_step = Step.dev_design; db.commit()
        slice_workflow.handle_design(db, task, design_run, ToolRuntime(tmp_path))
        assert task.cur_step == Step.develop
        progress = json.loads((tmp_path / "evidence/slice-progress.json").read_text())
        assert len(progress["slices"]) == 1

        develop_run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                              checkpoint_path=str(tmp_path / "evidence/develop.json"))
        db.add(develop_run); db.commit()
        slice_workflow.handle_develop(db, task, develop_run, ToolRuntime(tmp_path))
        assert task.cur_step == Step.test
        assert develop_run.status == StepStatus.succeeded
        progress = json.loads((tmp_path / "evidence/slice-progress.json").read_text())
        assert progress["complete"] is True
        assert progress["slices"][0]["status"] == "passed"
        assert planner_calls == 2
