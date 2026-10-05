import json
from pathlib import Path
import pytest

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime import acceptance_standard, scaffold_workflow, slice_workflow, worker
from backend.app.runtime.tools import ToolRuntime
from backend.app.runtime.contracts import ToolCall, ToolResult


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
        "required_interfaces": ["materials.create", "materials.list", "storage.save"],
        "implementation_files": [
            "product/index.html", "product/styles.css", "product/materials.js", "product/implementation.md",
            "product/verify_product.py",
        ],
        "test_files": ["product/material-create.test.js"],
        "acceptance": ["新增素材后列表展示", "刷新后素材仍存在", "空标题失败后可以继续新增"],
        "acceptance_interfaces": [
            {"acceptance": "新增素材后列表展示", "interfaces": ["materials.create", "materials.list"]},
            {"acceptance": "刷新后素材仍存在", "interfaces": ["storage.save"]},
            {"acceptance": "空标题失败后可以继续新增", "interfaces": ["materials.create"]},
        ],
        "reason": "形成第一个端到端业务结果",
    }


def test_completed_project_design_repair_creates_event_card(tmp_path, monkeypatch):
    """旧切片通过后，设计返修仍必须规划新卡并保存原始目标。"""
    from backend.app.runtime import repair_objectives
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.dev_design)
        tools = ToolRuntime(tmp_path)
        slice_workflow.ensure_delivery_plan(db, task, run, tools)
        plan = slice_workflow.load_delivery_plan(tmp_path)
        progress = slice_workflow._progress(tmp_path, plan)
        old = slice_workflow._append_card(tmp_path, progress, card())
        old["status"] = "passed"
        progress["complete"] = True
        slice_workflow._save_progress(tmp_path, progress)
        triage = {"classification": "dev_design_defect", "planner_action": "update_dev_design",
                  "event_id": 42, "user_feedback": "favicon 404，刷新页面应无资源错误"}
        worker.write_json_atomic(tmp_path / "evidence/acceptance-triage-42.json", triage)
        repair_objectives.capture(tmp_path, triage)
        repair_objectives.capture(tmp_path, triage)
        calls = []

        def fake_loop(*args, **kwargs):
            """先模拟错误宣布完成，再按校验反馈返回真正返修卡。"""
            context = args[5]
            calls.append(context)
            assert context["current_acceptance_feedback"] == triage
            assert context["pending_repair_objectives"][0]["original_feedback"] == triage["user_feedback"]
            if len(calls) == 1:
                return json.dumps({"action": "complete", "coverage_summary": ["旧功能通过"]})
            assert context["validation_feedback"]["error"] == "slice_design_repair_not_delivered"
            return json.dumps({"action": "implement", "card": {**card(), "id": "material-resource-repair"}})

        monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
        slice_workflow.handle_design(db, task, run, tools)
        saved = slice_workflow._progress(tmp_path, plan)
        assert len(saved["slices"]) == 2 and saved["slices"][0]["status"] == "passed"
        assert saved["slices"][1]["repair_event_id"] == 42 and saved["complete"] is False
        slice_workflow.handle_design(db, task, run, tools)
        assert len(calls) == 2
        assert len(repair_objectives.pending(task)) == 1
        saved["slices"][1]["status"] = "passed"
        slice_workflow._save_progress(tmp_path, saved)
        # 执行卡通过不核销目标；核销仍等待真实浏览器与独立审查。
        assert repair_objectives.pending(task)[0]["status"] == "open"


def test_card_rejects_test_or_document_only_slice():
    value = card()
    value["id"] = "verification-only"
    try:
        slice_workflow.validate_card(value, set())
        assert False, "verification slice must be rejected"
    except ValueError as exc:
        assert str(exc) == "slice_non_business_id"


def test_card_dependencies_reject_unimplemented_external_interface():
    """验收依赖未交付模块时，当前卡必须同时拥有该模块实现和测试。"""
    value = card()
    value["owners"] = ["topic"]
    value["interfaces"] = ["topic.deleteTopic", "task.hasTaskForTopic"]
    value["required_interfaces"] = ["topic.deleteTopic", "task.hasTaskForTopic"]
    value["acceptance"] = ["有来源任务时删除选题返回 HAS_TASK"]
    value["acceptance_interfaces"] = [{"acceptance": value["acceptance"][0],
                                        "interfaces": value["required_interfaces"]}]
    value["implementation_files"] = ["product/topic.js"]
    value["test_files"] = ["product/topic.test.js"]
    scaffold = {"modules": [
        {"id": "topic", "interfaces": ["topic.deleteTopic"],
         "implementation_files": ["product/topic.js"], "test_file": "product/topic.test.js"},
        {"id": "task", "interfaces": ["task.hasTaskForTopic"],
         "implementation_files": ["product/task.js"], "test_file": "product/task.test.js"},
    ]}
    try:
        slice_workflow.validate_card_dependencies(value, scaffold, [])
        assert False, "unimplemented task interface must be rejected"
    except ValueError as exc:
        assert str(exc) == "slice_required_interfaces_unavailable:task.hasTaskForTopic"

    value["owners"].append("task")
    value["implementation_files"].append("product/task.js")
    value["test_files"].append("product/task.test.js")
    slice_workflow.validate_card_dependencies(value, scaffold, [])


def test_card_dependencies_use_exact_contract_when_operation_names_repeat():
    """不同模块同名操作必须按完整接口契约归属，不能被后声明模块覆盖。"""
    value = card()
    value["owners"] = ["materials"]
    value["interfaces"] = ["list() -> Material[]"]
    value["required_interfaces"] = ["list() -> Material[]"]
    value["acceptance"] = ["素材列表返回全部素材"]
    value["acceptance_interfaces"] = [{"acceptance": value["acceptance"][0],
                                        "interfaces": value["required_interfaces"]}]
    value["implementation_files"] = ["product/materials.js"]
    value["test_files"] = ["product/materials.test.js"]
    scaffold = {"modules": [
        {"id": "materials", "interfaces": ["list() -> Material[]"],
         "implementation_files": ["product/materials.js"], "test_file": "product/materials.test.js"},
        {"id": "topics", "interfaces": ["list() -> Topic[]"],
         "implementation_files": ["product/topics.js"], "test_file": "product/topics.test.js"},
    ]}
    slice_workflow.validate_card_dependencies(value, scaffold, [])


def test_card_dependencies_resolve_each_operation_in_combined_contract():
    """组合声明中的第二个操作也应能被切片依赖单独引用。"""
    value = card()
    value["owners"] = ["tasks"]
    value["interfaces"] = ["getTopic(id)"]
    value["required_interfaces"] = ["getTopic(id)"]
    value["acceptance"] = ["任务读取来源选题"]
    value["acceptance_interfaces"] = [{"acceptance": value["acceptance"][0],
                                        "interfaces": value["required_interfaces"]}]
    value["implementation_files"] = ["product/tasks.js"]
    value["test_files"] = ["product/tasks.test.js"]
    scaffold = {"modules": [{
        "id": "topics",
        "interfaces": ["listTopics() / getTopic(id)"],
        "implementation_files": ["product/topics.js"],
        "test_file": "product/topics.test.js",
    }]}
    completed = [{"card": {**card(), "implementation_files": ["product/topics.js"],
                            "test_files": ["product/topics.test.js"]}}]

    slice_workflow.validate_card_dependencies(value, scaffold, completed)


def test_card_acceptance_mapping_treats_combined_and_individual_operations_as_equivalent():
    """验收映射可逐个引用 required_interfaces 中的组合公共操作。"""
    value = card()
    value["interfaces"] = ["listTopics() / getTopic(id)"]
    value["required_interfaces"] = ["listTopics() / getTopic(id)"]
    value["acceptance"] = ["列表并读取选题"]
    value["acceptance_interfaces"] = [{
        "acceptance": value["acceptance"][0],
        "interfaces": ["listTopics()", "getTopic(id)"],
    }]

    slice_workflow.validate_card(value, set())


def test_completion_accepts_structured_coverage_summary():
    """新版 Planner 的需求覆盖表应与 Runtime 完成契约一致。"""
    value = [
        {"requirement": "素材可新增", "covered_by": "materials 测试"},
        {"requirement": "选题可删除", "covered_by": ["topics-core", "app-shell-integration"]},
        {"acceptance": "任务可查看来源选题", "covered_by": ["app-shell-integration"]},
    ]

    assert slice_workflow._validate_coverage_summary(value) == value


def test_acceptance_standard_revises_merged_user_actions_without_changing_product(tmp_path, monkeypatch):
    """内部审查发现复合操作漏拆时纠正，产品原文保持不变。"""
    responses = [
        {"items": [{"source_quote": "通过关键词找到其中一条并修改笔记",
                    "action": "找到并修改素材", "observable_result": "素材已变化"}]},
        {"complete": False, "issues": [{"source_quote": "通过关键词找到其中一条并修改笔记",
                                       "problem": "检索和编辑是两个独立操作"}]},
        {"add": [], "replace": [{"id": "A001", "items": [
            {"source_quote": "通过关键词找到其中一条并修改笔记",
             "action": "按关键词找到素材", "observable_result": "显示匹配素材"},
            {"source_quote": "通过关键词找到其中一条并修改笔记",
             "action": "编辑已有素材笔记", "observable_result": "显示修改后的笔记"}]}]},
        {"complete": True, "issues": []},
    ]
    seen = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        seen.append((instructions.name, context))
        return json.dumps(responses.pop(0), ensure_ascii=False)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.architecture_docs)
        product = "新建三条素材，通过关键词找到其中一条并修改笔记。"
        (tmp_path / "docs/product.md").write_text(product, encoding="utf-8")
        standard = acceptance_standard.ensure_standard(db, task, run, ToolRuntime(tmp_path))
        assert [item["id"] for item in standard["items"]] == ["A001", "A002"]
        assert seen[2][1]["issues"][0]["problem"] == "检索和编辑是两个独立操作"
        assert (tmp_path / "docs/product.md").read_text(encoding="utf-8") == product
        assert acceptance_standard.load_standard(tmp_path) == standard


def test_acceptance_standard_resumes_saved_review_feedback(tmp_path, monkeypatch):
    """审查中断后从下一轮继续，不重复已经付费的提取与审查。"""
    import hashlib

    product = "删除已关联素材后，任务仍可查看。"
    feedback = {"issues": [{"source_quote": product, "problem": "缺少任务可查看"}]}
    responses = [
        {"add": [{"source_quote": product, "action": "删除已关联素材后查看任务",
                  "observable_result": "任务仍可查看"}], "replace": []},
        {"complete": True, "issues": []},
    ]
    seen = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        seen.append((context, kwargs["history_key"]))
        return json.dumps(responses.pop(0), ensure_ascii=False)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.architecture_docs)
        (tmp_path / "docs/product.md").write_text(product, encoding="utf-8")
        (tmp_path / "evidence").mkdir(exist_ok=True)
        (tmp_path / "evidence/acceptance-standard-progress.json").write_text(json.dumps({
            "workflow_version": 2, "product_hash": hashlib.sha256(product.encode()).hexdigest(),
            "next_attempt": 1, "candidate_items": [
                {"id": "A001", "source_quote": product, "action": "删除已关联素材",
                 "observable_result": "素材被删除"}],
            "issues": feedback["issues"], "review_pending": False,
            "patch": None, "changed_items": [],
        }, ensure_ascii=False))
        standard = acceptance_standard.ensure_standard(db, task, run, ToolRuntime(tmp_path))
    assert len(seen) == 2
    assert seen[0][0]["issues"] == feedback["issues"]
    assert seen[0][1].endswith(":1")
    assert standard["review"] == {"complete": True, "issues": []}
    assert [item["id"] for item in standard["items"]] == ["A001", "A002"]


def test_acceptance_patch_preserves_untouched_items_and_ids():
    """局部补漏不能让已有的无关行为在下一轮消失。"""
    product = "打开已保存来源链接。删除已关联素材后任务仍可查看。"
    items = acceptance_standard._items({"items": [
        {"source_quote": "打开已保存来源链接", "action": "打开来源链接",
         "observable_result": "链接被打开"},
        {"source_quote": "删除已关联素材后任务仍可查看", "action": "删除已关联素材",
         "observable_result": "素材被删除"},
    ]}, product)
    patch = {"add": [{"source_quote": "删除已关联素材后任务仍可查看",
                       "action": "删除后查看任务", "observable_result": "任务仍可查看"}],
             "replace": []}
    merged, changed = acceptance_standard._merge_patch(items, patch, product)
    assert merged[:2] == items
    assert changed == [merged[2]]
    assert merged[2]["id"] == "A003"


def test_acceptance_standard_resumes_pending_review_without_repeating_patch(tmp_path, monkeypatch):
    """局部修正写入断点后，只重试尚未完成的独立复查。"""
    import hashlib

    seen = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        seen.append(instructions.name)
        return json.dumps({"complete": True, "issues": []})

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.architecture_docs)
        product = (tmp_path / "docs/product.md").read_text()
        items = acceptance_standard._items({"items": [
            {"source_quote": product, "action": "新增素材", "observable_result": "素材可查看"},
        ]}, product)
        patch = {"add": [{"source_quote": product, "action": "查看素材",
                          "observable_result": "显示素材"}], "replace": []}
        merged, changed = acceptance_standard._merge_patch(items, patch, product)
        worker.write_json_atomic(tmp_path / "evidence/acceptance-standard-progress.json", {
            "workflow_version": 2, "product_hash": hashlib.sha256(product.encode()).hexdigest(),
            "next_attempt": 1, "candidate_items": merged,
            "issues": [{"source_quote": product, "problem": "缺少查看"}],
            "review_pending": True, "patch": patch, "changed_items": changed,
        })
        standard = acceptance_standard.ensure_standard(db, task, run, ToolRuntime(tmp_path))
    assert seen == ["acceptance-correction-reviewer"]
    assert len(standard["items"]) == 2


def test_acceptance_standard_rejects_unquoted_requirement():
    """模型不能从没有原文依据的行为生成内部标准。"""
    try:
        acceptance_standard._items({"items": [{"source_quote": "页面支持批量导出",
            "action": "导出", "observable_result": "获得文件"}]}, "页面支持新增素材")
        assert False, "unsupported behavior must be rejected"
    except ValueError as exc:
        assert str(exc) == "acceptance_source_quote_missing"


def test_foundation_slice_can_defer_behavior_ids_until_user_flow_is_complete():
    """共享基础切片可以尚未交付用户行为，但最终覆盖门禁仍保留缺口。"""
    standard = {"items": [{"id": "A001"}]}
    foundation = {"id": "storage", "acceptance_ids": []}
    acceptance_standard.validate_card_ids(foundation, standard)
    assert acceptance_standard.coverage_gap(standard, [{"card": foundation}]) == ["A001"]


def test_new_architecture_prepares_internal_standard_before_scaffold(tmp_path, monkeypatch):
    """新任务的内部标准先于骨架和第一张切片产生，旧入口不受影响。"""
    order = []
    monkeypatch.setattr(acceptance_standard, "ensure_standard",
                        lambda *args: order.append("standard"))
    monkeypatch.setattr(scaffold_workflow, "ensure_scaffold",
                        lambda *args: order.append("scaffold"))
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.architecture_docs)
        (tmp_path / "docs/product-v1.md").write_text(
            (tmp_path / "docs/product.md").read_text(encoding="utf-8"), encoding="utf-8")
        slice_workflow.prepare_architecture_delivery(db, task, run, ToolRuntime(tmp_path))
        assert order == ["standard", "scaffold"]
        assert (tmp_path / "docs/delivery-plan.json").is_file()


def test_missing_page_edit_coverage_replans_after_data_update_passed(tmp_path, monkeypatch):
    """旧故障形态中数据层 update 已通过，页面编辑缺口仍必须生成下一张卡。"""
    standard = {"items": [
        {"id": "A001", "source_quote": "编辑素材", "action": "修改已有素材笔记",
         "observable_result": "页面显示修改后的笔记"},
    ]}
    responses = [
        {"action": "complete", "coverage_summary": ["materials.update 已通过"]},
        {"action": "implement", "card": {**card(), "id": "material-page-edit",
                                          "acceptance_ids": ["A001"]}},
    ]
    seen = []

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        seen.append(context)
        return json.dumps(responses.pop(0), ensure_ascii=False)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.dev_design)
        (tmp_path / "docs/product.md").write_text("用户可以编辑素材。", encoding="utf-8")
        standard["items"][0]["source_quote"] = "编辑素材"
        import hashlib
        standard["product_hash"] = hashlib.sha256("用户可以编辑素材。".encode()).hexdigest()
        (tmp_path / "docs/acceptance-standard.json").write_text(
            json.dumps({**standard, "review": {"complete": True, "issues": []}}, ensure_ascii=False), encoding="utf-8")
        for name in ("index.html", "styles.css", "verify_product.py", "implementation.md",
                     "material-data.test.js"):
            (tmp_path / "product").mkdir(exist_ok=True)
            (tmp_path / "product" / name).write_text("existing", encoding="utf-8")
        slice_workflow.ensure_delivery_plan(db, task, run, ToolRuntime(tmp_path))
        plan = slice_workflow.load_delivery_plan(tmp_path)
        progress = {"workflow": "slice-v1", "product_hash": plan["product_hash"],
                    "architecture_hash": plan["architecture_hash"], "complete": False,
                    "slices": [{"card": {**card(), "id": "material-data-update",
                                          "acceptance_ids": []}, "status": "passed",
                                "test": {"passed": True}}]}
        result = slice_workflow.plan_next_slice(db, task, run, ToolRuntime(tmp_path), plan, progress)
        assert result["card"]["id"] == "material-page-edit"
        assert "A001" in seen[1]["validation_feedback"]["error"]
        assert seen[1]["verification_execution_contract"] == worker.VERIFICATION_EXECUTION_CONTRACT


def test_claimed_edit_id_without_browser_operation_fails_independent_coverage_review(tmp_path, monkeypatch):
    """引用了行为编号仍不能用仓储 update 测试冒充页面编辑证据。"""
    standard = {"product_hash": "test-hash", "items": [{"id": "A001", "source_quote": "编辑素材",
        "action": "修改已有素材笔记", "observable_result": "页面显示新笔记"}]}
    completed = [{"card": {**card(), "id": "material-data", "acceptance_ids": ["A001"],
                           "acceptance": ["仓储 update 修改笔记"]}, "status": "passed",
                  "test": {"passed": True}}]

    def fake_loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        assert instructions.name == "acceptance-coverage-reviewer"
        assert context["passed_slices"][0]["acceptance"] == ["仓储 update 修改笔记"]
        assert context["browser_script"] == "print('page loads')"
        return json.dumps({"complete": False, "issues": [{"acceptance_id": "A001",
            "problem": "页面脚本没有编辑已有素材并断言保存结果"}]}, ensure_ascii=False)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.develop)
        (tmp_path / "product").mkdir()
        (tmp_path / "product/verify_product.py").write_text("print('page loads')", encoding="utf-8")
        review = acceptance_standard.review_coverage(db, task, run, ToolRuntime(tmp_path),
                                                      standard, completed)
        assert review["complete"] is False
        assert review["issues"][0]["acceptance_id"] == "A001"


def test_card_dependencies_resolve_identical_contract_to_current_owner():
    """多个模块接口全文相同时，当前卡唯一 owner 应消除歧义。"""
    value = card()
    value["owners"] = ["materials"]
    value["interfaces"] = ["init(data) -> { ok }"]
    value["required_interfaces"] = ["init(data) -> { ok }"]
    value["acceptance"] = ["素材模块初始化"]
    value["acceptance_interfaces"] = [{"acceptance": value["acceptance"][0],
                                        "interfaces": value["required_interfaces"]}]
    value["implementation_files"] = ["product/materials.js"]
    value["test_files"] = ["product/materials.test.js"]
    scaffold = {"modules": [
        {"id": "materials", "interfaces": ["init(data) -> { ok }"],
         "implementation_files": ["product/materials.js"], "test_file": "product/materials.test.js"},
        {"id": "topics", "interfaces": ["init(data) -> { ok }"],
         "implementation_files": ["product/topics.js"], "test_file": "product/topics.test.js"},
    ]}
    slice_workflow.validate_card_dependencies(value, scaffold, [])


def test_card_dependencies_prefer_scoped_module_over_passed_owner():
    """卡片错误重复列出已通过 owner 时，应按当前实现与测试范围识别同名接口。"""
    value = card()
    value["owners"] = ["materials", "topics"]
    value["interfaces"] = ["init(data) -> { ok }"]
    value["required_interfaces"] = ["init(data) -> { ok }"]
    value["acceptance"] = ["选题模块初始化"]
    value["acceptance_interfaces"] = [{"acceptance": value["acceptance"][0],
                                        "interfaces": value["required_interfaces"]}]
    value["implementation_files"] = ["product/topics.js"]
    value["test_files"] = ["product/topics.test.js"]
    scaffold = {"modules": [
        {"id": "materials", "interfaces": ["init(data) -> { ok }"],
         "implementation_files": ["product/materials.js"], "test_file": "product/materials.test.js"},
        {"id": "topics", "interfaces": ["init(data) -> { ok }"],
         "implementation_files": ["product/topics.js"], "test_file": "product/topics.test.js"},
    ]}
    completed = [{"card": {**card(), "implementation_files": ["product/materials.js"],
                            "test_files": ["product/materials.test.js"]}}]
    slice_workflow.validate_card_dependencies(value, scaffold, completed)


def test_control_signal_accepts_analysis_before_replan():
    """模型先解释再给独立 REPLAN 行时，Runtime 仍应识别内部重规划。"""
    signal, detail = slice_workflow._control_signal(
        "分析：当前 task 接口尚未实现。\n\nREPLAN: 合并 topic、task 与 app 装配文件。")
    assert signal == "REPLAN"
    assert detail == "合并 topic、task 与 app 装配文件。"


def test_replan_uses_history_isolated_from_initial_plan(tmp_path, monkeypatch):
    """同一切片的内部重规划不能复用首次规划响应。"""
    keys = []

    def fake_loop(*args, **kwargs):
        keys.append(kwargs["history_key"])
        return json.dumps({"action": "implement", "card": card()}, ensure_ascii=False)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.dev_design)
        slice_workflow.ensure_delivery_plan(db, task, run, ToolRuntime(tmp_path))
        plan = slice_workflow.load_delivery_plan(tmp_path)
        progress = {"workflow": "slice-v1", "product_hash": plan["product_hash"],
                    "architecture_hash": plan["architecture_hash"], "slices": [], "complete": False}
        slice_workflow.plan_next_slice(db, task, run, ToolRuntime(tmp_path), plan, progress)
        slice_workflow.plan_next_slice(db, task, run, ToolRuntime(tmp_path), plan, progress,
                                       blocker="缺少 task.hasTaskForTopic", current_card=card())
        assert keys[0] != keys[1]
        assert ":replan:" in keys[1]


def test_retry_generation_changes_developer_history_key(tmp_path, monkeypatch):
    """显式恢复已耗尽切片时必须创建新调用历史，不能重放旧响应。"""
    assert slice_workflow._slice_history_key("slice", "topic-crud", 1) == "slice:topic-crud:1"
    assert slice_workflow._slice_history_key("slice", "topic-crud", 1, 1) == "slice:topic-crud:g1:1"


def test_slice_replan_tool_records_reason_and_stops_without_file_change(tmp_path):
    """模型发现跨模块缺口时用结构化工具可靠交给 Planner。"""
    tools = slice_workflow.SliceTools(tmp_path, [], [])
    result = tools.execute(ToolCall("replan-1", "request_slice_replan", {
        "reason": "缺少 task.hasTaskForTopic，需加入 task.js 与 task.test.mjs",
    }))
    assert result.status == "succeeded"
    assert tools.replan_reason == "缺少 task.hasTaskForTopic，需加入 task.js 与 task.test.mjs"


def test_architecture_scaffold_creates_interfaces_and_todo_contract(tmp_path, monkeypatch):
    """架构骨架应创建模块连接与独立 todo 测试，并保存哈希绑定契约。"""
    response = {
        "modules": [{
            "id": "materials",
            "interfaces": ["createMaterial(input)", "listMaterials()"],
            "implementation_files": ["product/index.html", "product/styles.css", "product/js/materials.js",
                                     "product/js/app.js", "product/verify_product.py",
                                     "product/implementation.md"],
            "test_file": "product/materials.test.js",
        }],
        "files": {
            "product/index.html": "<!doctype html><main id=\"materials\"></main><script type=\"module\" src=\"js/app.js\"></script>",
            "product/styles.css": "body { font-family: sans-serif; }\n",
            "product/js/materials.js": "export function createMaterial(){throw new Error('NotImplemented')}\nexport function listMaterials(){throw new Error('NotImplemented')}\n",
            "product/js/app.js": "import { listMaterials } from './materials.js';\nexport function init(){ return listMaterials; }\ninit();\n",
            "product/materials.test.js": "const test=require('node:test');\ntest.todo('新增素材后列表立即展示');\ntest.todo('标题为空后可修正并保存');\n",
            "product/verify_product.py": "raise SystemExit('NotImplemented')\n",
            "product/implementation.md": "# Architecture scaffold\n",
        },
    }

    monkeypatch.setattr(worker, "model_tool_loop", lambda *args, **kwargs: json.dumps(response, ensure_ascii=False))
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.architecture_docs)
        scaffold_workflow.ensure_scaffold(db, task, run, ToolRuntime(tmp_path))
        contract = json.loads((tmp_path / "docs/scaffold-contract.json").read_text())
        assert contract["workflow"] == "architecture-scaffold-v1"
        assert contract["initial_todo_files"] == ["product/materials.test.js"]
        assert scaffold_workflow.remaining_todo_files(tmp_path) == ["product/materials.test.js"]
        assert (tmp_path / "product/js/app.js").is_file()


def test_architecture_scaffold_rejects_missing_styles_before_write():
    """固定入口缺失必须在任何文件落盘前被结构校验拒绝。"""
    value = {
        "modules": [{"id": "materials", "interfaces": ["listMaterials()"],
                     "implementation_files": ["product/materials.js"],
                     "test_file": "product/materials.test.js"}],
        "files": {
            "product/index.html": "<!doctype html><main></main>",
            "product/materials.js": "export const listMaterials = () => [];\n",
            "product/materials.test.js": "const test=require('node:test');test.todo('展示素材');\n",
            "product/verify_product.py": "raise SystemExit('NotImplemented')\n",
            "product/implementation.md": "# scaffold\n",
        },
    }
    try:
        scaffold_workflow._parse_scaffold(json.dumps(value))
        assert False, "missing styles.css must be rejected"
    except ValueError as exc:
        assert str(exc) == "scaffold_product_entries_required"


def test_architecture_scaffold_rejects_unowned_assembly_file():
    """装配文件必须在骨架契约中有唯一模块所有者，避免 Developer 无写权限。"""
    value = {
        "modules": [{"id": "app-ui", "interfaces": ["createApp()"],
                     "implementation_files": ["product/index.html", "product/styles.css",
                                              "product/src/app.js", "product/verify_product.py",
                                              "product/implementation.md"],
                     "test_file": "product/tests/app.test.js"}],
        "files": {
            "product/index.html": "<!doctype html><main></main>",
            "product/styles.css": "body{}\n",
            "product/src/app.js": "export const createApp=()=>({});\n",
            "product/src/main.js": "import {createApp} from './app.js';createApp();\n",
            "product/tests/app.test.js": "const test=require('node:test');test.todo('装配');\n",
            "product/verify_product.py": "raise SystemExit('NotImplemented')\n",
            "product/implementation.md": "# scaffold\n",
        },
    }
    try:
        scaffold_workflow._parse_scaffold(json.dumps(value))
        assert False, "unowned main.js must be rejected"
    except ValueError as exc:
        assert str(exc) == "scaffold_unowned_files:product/src/main.js"


def test_architecture_scaffold_corrects_oversized_manifest_without_user(tmp_path, monkeypatch):
    """骨架结构超限应在同一阶段自动纠正，不能直接终止或询问用户。"""
    oversized = {f"product/js/file-{index}.js": "export const value = 1;\n" for index in range(21)}
    valid = {
        "modules": [{"id": "materials", "interfaces": ["listMaterials()"],
                     "implementation_files": ["product/index.html", "product/styles.css",
                                              "product/js/materials.js", "product/verify_product.py",
                                              "product/implementation.md"],
                     "test_file": "product/materials.test.js"}],
        "files": {
            "product/index.html": "<!doctype html><main></main>",
            "product/styles.css": "body { font-family: sans-serif; }\n",
            "product/js/materials.js": "export function listMaterials(){throw new Error('NotImplemented')}\n",
            "product/materials.test.js": "const test=require('node:test');test.todo('展示素材');\n",
            "product/verify_product.py": "raise SystemExit('NotImplemented')\n",
            "product/implementation.md": "# scaffold\n",
        },
    }
    responses = [json.dumps({"modules": valid["modules"], "files": {**valid["files"], **oversized}}),
                 json.dumps(valid)]
    contexts = []

    def fake_loop(*args, **kwargs):
        contexts.append(args[5])
        return responses.pop(0)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.architecture_docs)
        scaffold_workflow.ensure_scaffold(db, task, run, ToolRuntime(tmp_path))
        assert contexts[0]["validation_feedback"] is None
        assert contexts[1]["validation_feedback"]["error"].startswith("scaffold_file_limit_exceeded:")
        assert task.status == TaskStatus.running


def test_architecture_scaffold_reports_module_file_key_mismatch(tmp_path, monkeypatch):
    """模块路径与 files 键不一致时，反馈应指出模块和具体路径。"""
    valid = {
        "modules": [{"id": "materials", "interfaces": ["listMaterials()"],
                     "implementation_files": ["product/index.html", "product/styles.css",
                                              "product/materials.js", "product/verify_product.py",
                                              "product/implementation.md"],
                     "test_file": "product/materials.test.js"}],
        "files": {
            "product/index.html": "<!doctype html><main></main>",
            "product/styles.css": "body{}\n",
            "product/materials.js": "export const listMaterials = () => [];\n",
            "product/materials.test.js": "const test=require('node:test');test.todo('展示素材');\n",
            "product/verify_product.py": "raise SystemExit('NotImplemented')\n",
            "product/implementation.md": "# scaffold\n",
        },
    }
    broken = json.loads(json.dumps(valid))
    broken["modules"][0]["implementation_files"][2] = "materials.js"
    responses = [json.dumps(broken), json.dumps(valid)]
    contexts = []

    def fake_loop(*args, **kwargs):
        contexts.append(args[5])
        return responses.pop(0)

    monkeypatch.setattr(worker, "model_tool_loop", fake_loop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.architecture_docs)
        scaffold_workflow.ensure_scaffold(db, task, run, ToolRuntime(tmp_path))
        feedback = contexts[1]["validation_feedback"]
        assert feedback["error"] == "scaffold_module_file_missing:materials:materials.js"
        assert "product/materials.js" in feedback["instruction"]
        assert task.status == TaskStatus.running


def test_repair_preflight_failure_uses_remaining_repair_budget(tmp_path, monkeypatch):
    """浏览器复验脚本错误须保留证据并进入下一轮有界返修。"""
    (tmp_path / "product").mkdir()
    (tmp_path / "product/verify_product.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/verification-report.md").write_text("上轮浏览器失败", encoding="utf-8")
    entry = {"card": card(), "card_path": "docs/slices/001-material-create.json", "status": "passed"}
    monkeypatch.setattr(slice_workflow, "load_delivery_plan", lambda root: {})
    monkeypatch.setattr(slice_workflow, "_progress", lambda root, plan: {"slices": [entry]})

    class SubmittedTools:
        def __init__(self, *args, **kwargs):
            self.submitted_hashes = {"product/verify_product.py": "changed"}
            self.readable = set()

        def _safe_path(self, path):
            return tmp_path / path

    monkeypatch.setattr(slice_workflow, "SliceTools", SubmittedTools)
    monkeypatch.setattr(slice_workflow, "_repair_diagnostic", lambda *args: {
        "detail_path": "evidence/diagnostic.json"})
    monkeypatch.setattr(worker, "model_tool_loop", lambda *args, **kwargs: "submitted")
    monkeypatch.setattr(worker, "run_product_browser_validation", lambda *args: (
        ToolResult("preflight", "verify_script_preflight", "failed",
                   {"exit_code": 1, "stdout": "", "stderr": "verification_script_starts_server:7"},
                   "verification_script_starts_server:7"),
        "python verify_product.py http://127.0.0.1:8000"))

    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.develop)
        task.repair_round = 1
        task.result_url = "http://127.0.0.1:8000"
        db.commit()
        slice_workflow.handle_repair(db, task, run, ToolRuntime(tmp_path))
        assert task.status == TaskStatus.running
        assert task.cur_step == Step.develop
        assert task.repair_round == 2
        assert "verification_script_starts_server:7" in (
            tmp_path / "evidence/verification-report.md").read_text(encoding="utf-8")


def test_repair_first_request_has_real_diagnostic_and_preserves_original_failure(tmp_path, monkeypatch):
    """返修首轮提供当前 Node 错误，保留原集成失败，诊断不代替模型自测。"""
    selected = {**card(), "implementation_files": ["product/materials.js"],
                "test_files": ["product/material-create.test.js"]}
    (tmp_path / "product").mkdir()
    (tmp_path / "product/materials.js").write_text("module.exports = 0;\n")
    (tmp_path / "product/material-create.test.js").write_text(
        "const test=require('node:test'); const assert=require('node:assert/strict');\n"
        "test('visible material',()=>assert.equal(require('./materials.js'),1));\n")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/verification-report.md").write_text("原页面缺少编辑入口")
    monkeypatch.setattr(slice_workflow, "load_delivery_plan", lambda root: {})
    monkeypatch.setattr(slice_workflow, "_progress", lambda root, plan: {"slices": [
        {"card": selected, "card_path": "docs/card.json", "status": "passed"}]})

    class RequestObserved(Exception):
        pass

    def first_request(db, task, run, instructions, input_text, context, tools, **kwargs):
        assert "card" not in context and "acceptance_standard_items" not in context
        assert context["repair_task"]["card_id"] == selected["id"]
        reference = context["repair_task"]["original_card_ref"]
        assert json.loads((tmp_path / reference).read_text()) == selected
        assert tools.execute(ToolCall("card", "read", {"path": reference})).status == "succeeded"
        assert tools.execute(ToolCall("alter-card", "write", {
            "path": reference, "content": "{}", "overwrite": True})).status == "failed"
        diagnostic = context["unit_diagnostic"]
        assert diagnostic["passed"] is False and diagnostic["exit_code"] == 1
        assert "visible material" in diagnostic["failure_report"]
        assert "ERR_ASSERTION" in diagnostic["failure_report"]
        assert "material-create.test.js:2" in diagnostic["failure_report"]
        assert context["unit_test_feedback"]["failure_report"] == "原页面缺少编辑入口"
        assert tools.self_test is None and tools.submitted_hashes is None
        assert tools.execute(ToolCall("early", "submit_unit_for_test", {})).error == "unit_self_test_required"
        assert tools.execute(ToolCall("detail", "read", {"path": diagnostic["detail_path"]})).status == "succeeded"
        focused = worker.build_tool_context(task, run, context, [], kwargs["history_key"])
        assert focused["current_task"]["latest_evidence"]["source_ref"] == "unit_diagnostic"
        assert focused["development_state"]["test_state"] == "failed"
        assert focused["development_state"]["next_action"] == "repair_current_unit_from_diagnostic"
        raise RequestObserved

    monkeypatch.setattr(worker, "model_tool_loop", first_request)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.develop)
        with pytest.raises(RequestObserved):
            slice_workflow.handle_repair(db, task, run, ToolRuntime(tmp_path))


@pytest.mark.parametrize("reporter", ["spec", "tap"])
@pytest.mark.parametrize("message_kind", ["steps", "long_line"])
def test_repair_diagnostic_keeps_assertion_after_long_application_logs(tmp_path, monkeypatch, reporter, message_kind):
    """复现真实断言消息很长时，摘要仍须包含末尾失败行号和实际／期望值。"""
    (tmp_path / "product").mkdir()
    message = "Array(80).fill('[step] browser operation succeeded').join('\\n')" if message_kind == "steps" else "'X'.repeat(8000)"
    (tmp_path / "product/long.test.cjs").write_text(
        "const test=require('node:test'); const assert=require('node:assert/strict');\n"
        f"test('long browser evidence',()=>assert.equal(false,true,{message}));\n"
        "test('unrelated successful test',()=>assert.ok(true));\n")
    scope = ["product/long.test.cjs"]
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.develop)
        tools = slice_workflow.SliceTools(tmp_path, scope, [], submission_files=scope,
                                         self_test_files=scope, test_files=scope)
        monkeypatch.setattr(tools, "self_test_command", lambda: f"node --test --test-reporter={reporter} long.test.cjs")
        report = slice_workflow._repair_diagnostic(db, task, run, tools)
        excerpt = report["failure_report"]
        assert report["passed"] is False
        assert "long browser evidence" in excerpt
        assert "long.test.cjs:2" in excerpt
        assert "ERR_ASSERTION" in excerpt
        assert "actual: false" in excerpt and "expected: true" in excerpt
        assert "[step]" not in excerpt and "unrelated successful test" not in excerpt
        full_report = (tmp_path / report["detail_path"]).read_text()
        assert ("[step]" if message_kind == "steps" else "X" * 8000) in full_report
        assert tools.self_test is None and tools.submitted_hashes is None


def test_passing_diagnostic_is_cached_per_version_without_authorizing_submission(tmp_path, monkeypatch):
    """同版本恢复不重复诊断，修改使缓存过期；诊断通过仍需主动自测。"""
    from backend.app.runtime.unit_workflow import file_hashes
    (tmp_path / "product").mkdir()
    implementation = tmp_path / "product/materials.js"
    implementation.write_text("module.exports = 1;\n")
    (tmp_path / "product/material-create.test.js").write_text(
        "const test=require('node:test'); const assert=require('node:assert/strict');\n"
        "test('material',()=>assert.equal(require('./materials.js'),1));\n")
    scope = ["product/materials.js", "product/material-create.test.js"]
    calls = []
    original = worker.execute_tool

    def counted(*args, **kwargs):
        calls.append(args[4])
        return original(*args, **kwargs)

    monkeypatch.setattr(worker, "execute_tool", counted)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.develop)
        tools = slice_workflow.SliceTools(tmp_path, scope, scope, submission_files=scope,
                                         self_test_files=scope, test_files=scope[1:])
        report = slice_workflow._repair_diagnostic(db, task, run, tools)
        assert report["passed"] is True
        assert slice_workflow._repair_diagnostic(db, task, run, tools) == report
        assert len(calls) == 1
        assert tools.self_test is None
        assert tools.execute(ToolCall("early", "submit_unit_for_test", {})).error == "unit_self_test_required"
        context = {"unit_file_scope": scope, "owned_files": scope, "require_unit_submission": True,
                   "unit_diagnostic": report}
        value = worker.build_tool_context(task, run, context, [], "diagnostic")
        assert value["development_state"]["test_state"] == "passed"
        assert value["development_state"]["next_action"] == "run_unit_tests"
        assert value["current_task"]["remaining_work"]["needs_current_self_test"] is True
        implementation.write_text("module.exports = 0;\n")
        stale = worker.build_tool_context(task, run, context, [], "diagnostic")
        assert stale["unit_diagnostic"]["matches_current_files"] is False
        assert stale["development_state"]["test_state"] == "stale"
        updated = slice_workflow._repair_diagnostic(db, task, run, tools)
        assert len(calls) == 2 and updated["passed"] is False
        assert updated["file_hashes_after"] == file_hashes(tmp_path, scope)
        implementation.write_text("module.exports = 1;\n")
        assert slice_workflow._repair_diagnostic(db, task, run, tools) == report
        assert len(calls) == 2


def test_repair_batch_diagnostic_allows_more_edits_and_reuses_explicit_self_test(tmp_path, monkeypatch):
    """一批修改只诊断一次并接力上下文；诊断不能代替自测，仍允许继续改。"""
    from backend.app.runtime.contracts import ModelResult
    from backend.app.runtime.model import build_messages
    (tmp_path / "product").mkdir()
    (tmp_path / "product/a.cjs").write_text("module.exports=0;")
    (tmp_path / "product/b.cjs").write_text("module.exports=0;")
    (tmp_path / "product/a.test.cjs").write_text(
        "require('node:test')('sum',()=>require('node:assert/strict').equal("
        "require('./a.cjs')+require('./b.cjs'),3));")
    selected = {**card(), "implementation_files": ["product/a.cjs", "product/b.cjs"],
                "test_files": ["product/a.test.cjs"]}
    monkeypatch.setattr(slice_workflow, "load_delivery_plan", lambda root: {})
    monkeypatch.setattr(slice_workflow, "_progress", lambda root, plan: {"slices": [
        {"card": selected, "card_path": "docs/card.json", "status": "passed"}]})
    received = []
    diagnostics = []
    original = worker.execute_tool

    def counted(*args, **kwargs):
        if kwargs.get("history_key", "").startswith("slice-repair-diagnostic:"):
            diagnostics.append(args[4].parameters["command"])
        return original(*args, **kwargs)

    def develop(runtime, task_id, request):
        context = request.context
        received.append(context)
        count = len(received)
        messages = build_messages(request, include_reasoning=True)
        if count == 1:
            assert context["unit_diagnostic"]["passed"] is False
            actions = [ToolCall("a", "replace", {"path": "product/a.cjs", "old": "=0", "new": "=1"}),
                       ToolCall("b", "replace", {"path": "product/b.cjs", "old": "=0", "new": "=2"})]
        elif count == 2:
            assert [message["role"] for message in messages] == ["system", "user"]
            assert context["context_session"]["reason"] == "changed_files_and_current_diagnostic"
            assert context["current_requested_data"] == []
            assert context["unit_diagnostic"]["passed"] is True
            assert context["unit_self_test"] is None
            assert context["development_state"]["next_action"] == "run_unit_tests"
            assert len(diagnostics) == 2
            actions = [ToolCall("inspect", "read", {"path": "product/a.cjs"})]
        elif count == 3:
            assert messages[2]["reasoning_content"] == "完整思考-2"
            assert messages[3]["tool_call_id"] == "inspect"
            assert len(diagnostics) == 2
            actions = [ToolCall("early", "submit_unit_for_test", {})]
        elif count == 4:
            assert [message["reasoning_content"] for message in messages if message["role"] == "assistant"] == ["完整思考-2", "完整思考-3"]
            history = context.get("reasoning_tool_history", context["tool_history"])
            assert history[-1]["result"]["error"] == "unit_self_test_required"
            assert len(diagnostics) == 2
            actions = [ToolCall("more", "replace", {"path": "product/a.cjs", "old": "=1", "new": "=2"})]
        elif count == 5:
            assert len(messages) == 2
            assert context["carried_file_context"][0]["content"] == "module.exports=2;"
            assert context["unit_diagnostic"]["passed"] is False
            assert context["unit_diagnostic"]["matches_current_files"] is True
            assert context["development_state"]["next_action"] == "repair_current_unit_from_diagnostic"
            assert len(diagnostics) == 3
            actions = [ToolCall("fix", "replace", {"path": "product/a.cjs", "old": "=2", "new": "=1"}),
                       ToolCall("test", "run_unit_tests", {})]
        else:
            assert len(messages) == 2
            assert context["carried_file_context"][0]["content"] == "module.exports=1;"
            assert context["repair_task"]["card_id"] == selected["id"]
            assert context["owned_files"] == selected["implementation_files"] + selected["test_files"]
            assert count == 6 and len(diagnostics) == 3
            assert context["unit_self_test"]["passed"] is True
            assert context["development_state"]["next_action"] == "submit_unit_for_test"
            actions = [ToolCall("submit", "submit_unit_for_test", {})]
        return ModelResult(request.request_id, 1, "", actions, "tool_calls", {"reasoning_content": f"完整思考-{count}"})

    monkeypatch.setattr(worker, "execute_tool", counted)
    monkeypatch.setattr("backend.app.runtime.model.ChatCompletionsRuntime.call", develop)
    with SessionLocal() as db:
        task, run = make_task(db, tmp_path, Step.develop)
        slice_workflow.handle_repair(db, task, run, ToolRuntime(tmp_path))
        assert len(received) == 6 and len(diagnostics) == 3
        assert task.cur_step == Step.test and run.status == StepStatus.succeeded
        checkpoint = json.loads(Path(run.checkpoint_path).read_text())
        assert len(checkpoint) == 8
        assert checkpoint[0]["reasoning_content"] == "完整思考-1"
        assert run.model_call_count == 6
        state = json.loads(next((tmp_path / "evidence").glob("deepseek-context-session-*.json")).read_text())
        assert len(state["boundaries"]) == 3
        # 恢复使用原循环 ID，不能因为成功动作计数变大而重放或丢历史。
        saved_key = checkpoint[0]["history_key"]
        failure_key = saved_key.split(":")[-2]
        assert slice_workflow._repair_history_key(run, selected["id"], failure_key) == saved_key


@pytest.mark.parametrize("passed", [True, False])
def test_current_diagnostic_takes_precedence_over_stale_self_test(tmp_path, passed):
    """过期的自测不能遮住当前诊断，通过诊断也不能建议直接提交。"""
    from backend.app.runtime.unit_workflow import file_hashes
    tools = ToolRuntime(tmp_path)
    tools._write("product/a.cjs", "current", False)
    scope = ["product/a.cjs"]
    context = {"unit_file_scope": scope, "owned_files": scope, "require_unit_submission": True,
               "repair_task": {"card_id": "repair", "original_card_ref": "evidence/card.json"},
               "unit_self_test": {"passed": True, "file_hashes_after": {scope[0]: "old"}},
               "unit_diagnostic": {"passed": passed, "file_hashes_after": file_hashes(tmp_path, scope)}}
    task = Task(task_name="repair", workspace_path=str(tmp_path), cur_step=Step.develop, status=TaskStatus.running)
    run = StepRun(task_id=1, step=Step.develop, status=StepStatus.running, attempt=1)
    value = worker.build_tool_context(task, run, context, [], "repair")
    assert value["unit_self_test"]["matches_current_files"] is False
    assert value["current_task"]["effective_card"]["source_ref"] == "repair_task"
    assert value["current_task"]["latest_evidence"]["source_ref"] == "unit_diagnostic"
    assert value["development_state"]["test_state"] == ("passed" if passed else "failed")
    assert value["development_state"]["next_action"] == ("run_unit_tests" if passed else "repair_current_unit_from_diagnostic")
    assert value["current_task"]["remaining_work"]["needs_current_self_test"] is True


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
        assert "replace" in {schema["function"]["name"] for schema in kwargs["tool_schemas"]}
        assert input_text != json.dumps(context["card"], ensure_ascii=False)
        contents = {
            "product/index.html": "<!doctype html><main>Materials</main>",
            "product/styles.css": "body { font-family: sans-serif; }\n",
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
        assert tools.execute(ToolCall("patch", "replace", {"path":"product/materials.js", "old":"x => x", "new":"x => ({...x})"})).status == "succeeded"
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
