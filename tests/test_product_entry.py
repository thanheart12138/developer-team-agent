"""验证产品入口契约及真实子目录模块返修，不调用付费模型。"""

import json

import pytest

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime.tools import ToolRuntime
from backend.app.runtime import worker


def setup_function():
    # 为每个用例建立独立的内存业务库。
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed_product(root):
    # 构造无根目录 app.js 的真实子目录入口与 Node 测试。
    product = root / "product"
    (product / "js").mkdir(parents=True)
    (product / "test-cases").mkdir()
    (root / "docs").mkdir()
    (root / "evidence").mkdir()
    (root / "docs/product.md").write_text("显示 42", encoding="utf-8")
    (root / "docs/dev-design.md").write_text("入口 js/main.cjs，业务 js/value.cjs", encoding="utf-8")
    (product / "index.html").write_text('<script src="js/main.cjs?version=1#entry"></script>', encoding="utf-8")
    (product / "js/main.cjs").write_text("require('./value.cjs')", encoding="utf-8")
    (product / "js/value.cjs").write_text("module.exports = 42", encoding="utf-8")
    (product / "test-cases/domain.test.cjs").write_text(
        "const test = require('node:test'); const assert = require('node:assert/strict');"
        "test('module contract', () => assert.equal(require('../js/value.cjs'), 42));", encoding="utf-8")
    (product / "verify_product.py").write_text("", encoding="utf-8")
    (product / "implementation.md").write_text("nested entry", encoding="utf-8")
    return product


@pytest.mark.parametrize("reference,expected", [
    ('<script src="js/main.cjs?v=1#x"></script>', []),
    ('<script src="/js/main.cjs"></script>', []),
    ('<script src="js/missing.js"></script>', ['js/missing.js']),
    ('<link rel="stylesheet" href="css/missing.css?version=2">', ['css/missing.css']),
    ('<a href="nonexistent.html">普通链接</a><script>inline()</script>', []),
])
def test_entry_references_use_actual_local_paths(tmp_path, reference, expected):
    # 按浏览器加载引用检查实际文件，不要求默认 JS/CSS 文件名。
    product = seed_product(tmp_path)
    (product / "index.html").write_text(reference, encoding="utf-8")
    assert worker.missing_product_files(tmp_path) == expected
    assert not (product / "app.js").exists()


def test_entry_cannot_reference_outside_product(tmp_path):
    # 入口引用不得把工作区内治理文档作为产品脚本。
    product = seed_product(tmp_path)
    (product / "index.html").write_text('<script src="../docs/product.md"></script>', encoding="utf-8")
    with pytest.raises(RuntimeError, match="product_entry_outside_directory"):
        worker.missing_product_files(tmp_path)


@pytest.mark.parametrize("step", [Step.test, Step.verify_product])
def test_missing_test_cannot_pass_with_zero_discovery(tmp_path, monkeypatch, step):
    # 没有合约测试时必须返修，不能依赖 Node 的零测试成功退出。
    product = tmp_path / "product"
    product.mkdir()
    for name in ("index.html", "verify_product.py", "implementation.md"):
        (product / name).write_text("", encoding="utf-8")
    called = []
    monkeypatch.setattr(worker, "execute_tool", lambda *args: called.append(args))
    with SessionLocal() as db:
        task = Task(task_name="no test", status=TaskStatus.running, cur_step=step, workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=step, status=StepStatus.running, attempt=1)
        db.add(run)
        db.commit()
        handler = worker.handle_test if step == Step.test else worker.handle_verify
        handler(db, task, run, ToolRuntime(tmp_path))
        assert task.cur_step == Step.develop
        assert run.status == StepStatus.failed
        assert "*.test.js" in run.error
        assert not called
        assert "入口校验失败" in (tmp_path / run.output_path).read_text()


def test_nested_module_repair_refreshes_all_files_and_runs_discovered_test(tmp_path, monkeypatch):
    # 复现只改子目录业务模块的返修，实际运行 Node 验证修复结果。
    product = seed_product(tmp_path)
    (product / "js/value.cjs").write_text("module.exports = -1", encoding="utf-8")
    tools = ToolRuntime(tmp_path)
    assert tools._exec("run", "node --test")["exit_code"] != 0
    contexts = []

    def repair(db, task, run, instructions, input_text, context, tools, **kwargs):
        # 模拟模型仅修改真实故障模块，其他文件保持原样。
        contexts.append(context)
        assert kwargs['stop_when'] is None
        (product / "js/value.cjs").write_text("module.exports = 42", encoding="utf-8")
        return "done"

    monkeypatch.setattr(worker, "model_tool_loop", repair)
    with SessionLocal() as db:
        task = Task(task_name="nested repair", status=TaskStatus.running, cur_step=Step.develop,
                    workspace_path=str(tmp_path), repair_round=1)
        db.add(task)
        db.flush()
        db.add(StepRun(task_id=task.id, step=Step.test, status=StepStatus.failed, attempt=1))
        db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=2)
        db.add(run)
        db.commit()
        worker.handle_develop(db, task, run, tools)
        assert task.cur_step == Step.test
        assert contexts[0]['current_product_files']['product/js/value.cjs'] == 'module.exports = -1'
        assert 'product/test-cases/domain.test.cjs' in contexts[0]['snapshot']['file_sha256']
        assert tools._exec("run", "node --test")["exit_code"] == 0
        test_run = worker.create_step_run(db, task)
        worker.handle_test(db, task, test_run, tools)
        assert task.cur_step == Step.start_product


def test_develop_accepts_existing_nested_entry_with_matching_lineage(tmp_path, monkeypatch):
    # 复现基准中 js/app.js 类入口被误判缺失，恢复时无需创建空壳根入口。
    seed_product(tmp_path)
    (tmp_path / 'evidence/implementation-lineage.json').write_text(json.dumps({
        'dev_design_hash': worker.content_hash((tmp_path / 'docs/dev-design.md').read_text()),
    }))
    monkeypatch.setattr(worker, 'model_tool_loop', lambda *args, **kwargs: pytest.fail('matching lineage should resume'))
    with SessionLocal() as db:
        task = Task(task_name="nested resume", status=TaskStatus.running, cur_step=Step.develop,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1)
        db.add(run)
        db.commit()
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert task.cur_step == Step.test


def test_new_module_is_available_to_next_repair_attempt(tmp_path, monkeypatch):
    # 新增模块导致首轮验证失败时，下一轮应能看到并覆盖实际新文件。
    product = seed_product(tmp_path)
    contexts = []

    def repair(db, task, run, instructions, input_text, context, tools, **kwargs):
        # 首轮新增依赖并引入失败；第二轮依据刷新后的快照修复依赖。
        contexts.append(context)
        if len(contexts) == 1:
            (product / 'js/new.cjs').write_text('module.exports = -1')
            (product / 'js/value.cjs').write_text("module.exports = require('./new.cjs')")
        else:
            assert 'product/js/new.cjs' in context['existing_product_files']
            assert context['current_product_files']['product/js/new.cjs'] == 'module.exports = -1'
            (product / 'js/new.cjs').write_text('module.exports = 42')
        return 'done'

    monkeypatch.setattr(worker, 'model_tool_loop', repair)
    with SessionLocal() as db:
        task = Task(task_name='new nested module', status=TaskStatus.running, cur_step=Step.develop,
                    workspace_path=str(tmp_path), repair_round=1)
        db.add(task)
        db.flush()
        db.add(StepRun(task_id=task.id, step=Step.test, status=StepStatus.failed, attempt=1))
        db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=2)
        db.add(run)
        db.commit()
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert len(contexts) == 2
        assert task.cur_step == Step.test
