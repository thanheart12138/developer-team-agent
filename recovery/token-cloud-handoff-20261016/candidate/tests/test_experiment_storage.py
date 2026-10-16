import ast
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

import experiment_storage as storage


@pytest.fixture
def persistent_root(tmp_path, monkeypatch):
    """用独立夹具模拟持久父目录，不创建付费实验或访问正式任务。"""
    base = tmp_path / "persistent"
    monkeypatch.setattr(storage, "EXPERIMENTS_ROOT", base)
    return base


def seed_checkpoint(path):
    """建立恢复所需的本地夹具，计数和业务内容均为合成数据。"""
    root = storage.prepare_experiment_root("fixture-", path)
    (root / "workspace").mkdir()
    seed_database(root)
    storage.save_call_count(root, 7)
    return root


def seed_database(root):
    """建立真实的合成 SQLite 文件，只用于测试原库的只读校验。"""
    with closing(sqlite3.connect(root / "test.db")) as db:
        db.execute("CREATE TABLE fixture (state TEXT, version INTEGER)")
        db.execute("INSERT INTO fixture VALUES ('failed/start_product', 67)")
        db.commit()


def bootstrap(script, arguments, monkeypatch):
    """只执行手动入口的标准库初始化，截断在 SDK／Runtime 导入之前。"""
    path = Path(__file__).parent / script
    statements = []
    for node in ast.parse(path.read_text()).body:
        imported = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        if any(name.split(".")[0] in {"backend", "httpx", "sqlalchemy"} for name in imported):
            break
        statements.append(node)
    with monkeypatch.context() as context:
        context.setattr(sys, "argv", [str(path), *map(str, arguments)])
        context.setattr(os, "environ", dict(os.environ))
        namespace = {}
        exec(compile(ast.Module(body=statements, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def test_new_roots_use_persistent_parent_and_do_not_collide(persistent_root):
    first = storage.prepare_experiment_root("example-")
    second = storage.prepare_experiment_root("example-")
    assert first.parent == second.parent == persistent_root
    assert first != second
    assert (persistent_root / "README.md").is_file()
    assert (first / "README.md").is_file()
    assert storage.read_call_count(first) == 0


def test_outside_path_and_symlink_are_rejected_before_creation(persistent_root, tmp_path):
    outside = tmp_path / "temporary" / "experiment"
    with pytest.raises(ValueError, match="outside_persistent"):
        storage.prepare_experiment_root("example-", outside)
    assert not outside.exists()
    persistent_root.mkdir()
    (persistent_root / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="outside_persistent"):
        storage.prepare_experiment_root("example-", persistent_root / "escape" / "experiment")


def test_nonempty_root_cannot_reset_existing_experiment(persistent_root):
    root = seed_checkpoint(persistent_root / "original")
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError, match="use_resume"):
        storage.prepare_experiment_root("example-", root)
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_storage_parent_cannot_redirect_to_temporary_directory(persistent_root, tmp_path):
    outside = tmp_path / "temporary"
    outside.mkdir()
    persistent_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="must_not_be_symlink"):
        storage.prepare_experiment_root("example-")
    assert not list(outside.iterdir())


def test_resume_copy_cannot_nest_destination_inside_source(persistent_root, monkeypatch):
    source = seed_checkpoint(persistent_root / "original")
    with pytest.raises(ValueError, match="copy_destination_inside_source"):
        bootstrap("tool_summary_deepseek_resume.py", [source, source / "copy"], monkeypatch)
    assert not (source / "copy").exists()
    assert storage.read_call_count(source) == 7


@pytest.mark.parametrize("missing", ["root", "database", "workspace", "counter"])
def test_resume_refuses_incomplete_checkpoint_without_creating_database(persistent_root, missing):
    root = persistent_root / "original"
    if missing != "root":
        root = storage.prepare_experiment_root("fixture-", root)
        if missing != "database":
            seed_database(root)
        if missing != "workspace":
            (root / "workspace").mkdir()
        if missing == "counter":
            (root / "call-count.json").rename(root / "call-count.saved.json")
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(FileNotFoundError):
        storage.prepare_experiment_root("fixture-", root, resume=True)
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("value", [-1, True, "7", 1.5, None])
def test_resume_rejects_invalid_saved_count(persistent_root, value):
    root = seed_checkpoint(persistent_root / "original")
    (root / "call-count.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="call_count_invalid"):
        storage.prepare_experiment_root("fixture-", root, resume=True)


def test_partial_counter_write_preserves_previous_count(persistent_root, monkeypatch):
    root = seed_checkpoint(persistent_root / "original")

    def interrupted_replace(path, target):
        """模拟原子替换前中断，调用尚未发送。"""
        raise OSError("fixture_interrupted_before_replace")

    monkeypatch.setattr(Path, "replace", interrupted_replace)
    with pytest.raises(OSError, match="fixture_interrupted"):
        storage.save_call_count(root, 8)
    assert storage.read_call_count(root) == 7


def test_resume_refuses_corrupted_database_without_modifying_it(persistent_root):
    root = seed_checkpoint(persistent_root / "original")
    path = root / "test.db"
    path.write_bytes(b"corrupted fixture database")
    with pytest.raises(ValueError, match="database_invalid"):
        storage.prepare_experiment_root("fixture-", root, resume=True)
    assert path.read_bytes() == b"corrupted fixture database"
    assert storage.read_call_count(root) == 7


def test_content_resume_loads_saved_count_and_refuses_lower_prior(persistent_root, monkeypatch):
    root = seed_checkpoint(persistent_root / "original")
    result = bootstrap("content_workbench_baseline.py", ["--root", root, "--resume"], monkeypatch)
    assert result["calls"] == 7
    with pytest.raises(ValueError, match="cannot_decrease"):
        bootstrap("content_workbench_baseline.py", ["--root", root, "--resume", "--prior-calls", "0"], monkeypatch)
    assert storage.read_call_count(root) == 7


@pytest.mark.parametrize("script, arguments", [
    ("context_calculator_baseline.py", ["--resume", "missing"]),
    ("content_workbench_baseline.py", ["--root", "missing", "--resume"]),
    ("unit_workflow_deepseek_validation.py", ["missing", "0", "--resume"]),
    ("tool_summary_deepseek_probe.py", ["new", "missing"]),
    ("tool_summary_deepseek_resume.py", ["missing", "new"]),
    ("content_workbench_baseline.py", ["--root", "new", "--verify-existing", "missing"]),
    ("unit_workflow_deepseek_validation.py", ["new", "0", "--verified-repair-probe", "--verified-source", "missing"]),
])
def test_all_paid_entries_refuse_missing_checkpoint_before_runtime(persistent_root, monkeypatch, script, arguments):
    paths = [persistent_root / value if value in {"missing", "new"} else value for value in arguments]
    with pytest.raises(FileNotFoundError, match="experiment_database_missing"):
        bootstrap(script, paths, monkeypatch)
    assert not persistent_root.exists()


def test_verified_repair_requires_explicit_persistent_source(persistent_root, monkeypatch):
    with pytest.raises(ValueError, match="verified_source_required"):
        bootstrap("unit_workflow_deepseek_validation.py",
                  [persistent_root / "new", "0", "--verified-repair-probe"], monkeypatch)
    assert not persistent_root.exists()


def test_checkpoint_survives_process_exit_and_preserves_history(persistent_root):
    root = storage.prepare_experiment_root("process-")
    workspace = root / "workspace" / "1"
    workspace.mkdir(parents=True)
    seed_database(root)
    history = workspace / "checkpoint.json"
    history.write_text(json.dumps([{"reasoning_content": "fixture thinking", "action": "read"}]))
    product = workspace / "main.js"
    product.write_text("export const fixture = 1;\n")
    storage.save_call_count(root, 7)
    original = {p: p.read_bytes() for p in (history, product)}
    code = """
import json, sqlite3, sys
from pathlib import Path
import experiment_storage as storage
storage.EXPERIMENTS_ROOT = Path(sys.argv[1])
root = storage.prepare_experiment_root('process-', sys.argv[2], resume=True)
with sqlite3.connect(root / 'test.db') as db:
    state = db.execute('SELECT state, version FROM fixture').fetchone()
print(json.dumps({'calls': storage.read_call_count(root), 'state': state}))
storage.save_call_count(root, 8)
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
    result = subprocess.run([sys.executable, "-c", code, str(persistent_root), str(root)],
                            capture_output=True, text=True, env=env, check=True)
    assert json.loads(result.stdout) == {"calls": 7, "state": ["failed/start_product", 67]}
    assert storage.read_call_count(root) == 8
    assert all(p.read_bytes() == body for p, body in original.items())
