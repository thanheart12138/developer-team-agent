from pathlib import Path

from backend.app.runtime.contracts import ToolCall
from backend.app.runtime.tools import MAX_BYTES, ToolRuntime


def call(runtime, name, **parameters):
    return runtime.execute(ToolCall("call-1", name, parameters))


def test_write_read_and_overwrite_contract(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    created = call(runtime, "write", path="docs/a.md", content="first", overwrite=False)
    assert created.status == "succeeded"
    assert call(runtime, "write", path="docs/a.md", content="second", overwrite=False).status == "failed"
    assert call(runtime, "write", path="docs/a.md", content="second", overwrite=True).status == "succeeded"
    assert call(runtime, "read", path="docs/a.md").output["content"] == "second"


def test_paths_cannot_escape_workspace(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    assert call(runtime, "read", path="/etc/passwd").error == "absolute_path_rejected"
    assert call(runtime, "write", path="../escape", content="x", overwrite=False).error == "path_outside_workspace"


def test_read_is_truncated_at_100_kb(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    content = "x" * (MAX_BYTES + 1)
    assert call(runtime, "write", path="evidence/large.txt", content=content, overwrite=False).status == "succeeded"
    result = call(runtime, "read", path="evidence/large.txt")
    assert len(result.output["content"].encode()) == MAX_BYTES
    assert result.output["truncated"] is True


def test_exec_is_fixed_to_product_directory(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    result = call(runtime, "exec", action="run", command="python -c \"import os; print(os.path.basename(os.getcwd()))\"")
    assert result.status == "succeeded"
    assert result.output["exit_code"] == 0
    assert result.output["stdout"].strip() == "product"

