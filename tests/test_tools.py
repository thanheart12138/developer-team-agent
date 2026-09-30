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


def test_replace_requires_one_exact_match(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    call(runtime, "write", path="product/app.js", content="before\nunique\nafter\n", overwrite=False)

    result = call(runtime, "replace", path="product/app.js", old="unique", new="changed")

    assert result.status == "succeeded"
    assert call(runtime, "read", path="product/app.js").output["content"] == "before\nchanged\nafter\n"
    assert call(runtime, "replace", path="product/app.js", old="missing", new="x").error == "replace_match_count:0"


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


def test_read_supports_inclusive_line_range(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    call(runtime, "write", path="product/app.js", content="one\ntwo\nthree\nfour\n", overwrite=False)

    result = call(runtime, "read", path="product/app.js", start_line=2, end_line=3)

    assert result.status == "succeeded"
    assert result.output["content"] == "two\nthree\n"
    assert result.output["total_lines"] == 4
    assert result.output["start_line"] == 2
    assert result.output["end_line"] == 3


def test_read_rejects_incomplete_or_reversed_line_range(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    call(runtime, "write", path="product/app.js", content="one\ntwo\n", overwrite=False)

    assert call(runtime, "read", path="product/app.js", start_line=1).error == "invalid_line_range"
    assert call(runtime, "read", path="product/app.js", start_line=2, end_line=1).error == "invalid_line_range"


def test_exec_is_fixed_to_product_directory(tmp_path: Path):
    runtime = ToolRuntime(tmp_path)
    result = call(runtime, "exec", action="run", command="python -c \"import os; print(os.path.basename(os.getcwd()))\"")
    assert result.status == "succeeded"
    assert result.output["exit_code"] == 0
    assert result.output["stdout"].strip() == "product"
