"""统一 sandbox 契约回归，替身只证明程序机制，不证明 Docker 隔离。"""

import json

import pytest

from backend.app.runtime import sandbox
from backend.app.runtime.tools import ToolRuntime
from backend.app.runtime.contracts import ToolCall


def test_source_change_rejected_before_docker_lookup(tmp_path, monkeypatch):
    """产品版本失效时不能冻结或启动旧版本 sandbox。"""
    product = tmp_path / "product"
    product.mkdir()
    (product / "index.html").write_text("first")
    version = sandbox.product_version(product)
    (product / "index.html").write_text("second")
    monkeypatch.setattr(sandbox, "image_identity", lambda: pytest.fail("must not query Docker"))
    with pytest.raises(ValueError, match="sandbox_source_changed"):
        sandbox.SandboxRuntime(tmp_path).create(1, "attempt1", version)


def test_creation_failure_keeps_unknown_and_never_recreates(tmp_path, monkeypatch):
    """创建副作用失败后保留未知状态，恢复查询不再次创建容器。"""
    product = tmp_path / "product"
    product.mkdir()
    (product / "index.html").write_text("fixture")
    monkeypatch.setattr(sandbox, "image_identity", lambda: "sha256:" + "a" * 64)
    calls = []

    def fail_create(self):
        """模拟结果未知的底层创建。"""
        calls.append("create")
        raise RuntimeError("unknown fixture")

    monkeypatch.setattr(sandbox.container.ContainerExecutionRuntime, "create", fail_create)
    runtime = sandbox.SandboxRuntime(tmp_path)
    version = sandbox.product_version(product)
    with pytest.raises(RuntimeError):
        runtime.create(1, "attempt1", version)
    record = next((tmp_path / "evidence").glob("sandbox-*/runtime.json"))
    value = json.loads(record.read_text())
    assert value["state"] == "unknown"
    assert runtime.inspect(value["sandbox_id"])["error"] == "unknown_side_effect"
    with pytest.raises(ValueError, match="sandbox_not_running"):
        runtime.create(1, "attempt1", version)
    with pytest.raises(ValueError, match="sandbox_not_running"):
        runtime.execute(value["sandbox_id"], "cmd", "run_unit_tests")
    assert calls == ["create"]


@pytest.mark.parametrize("action", ["shell", "install", "docker", "run"])
def test_no_arbitrary_execution_action(tmp_path, action):
    """未批准动作在任何容器副作用或记录读取前被拒绝。"""
    with pytest.raises(ValueError, match="invalid_sandbox_action"):
        sandbox.SandboxRuntime(tmp_path).execute("a" * 64, "cmd", action)


def test_new_mode_does_not_fall_back_to_host(tmp_path, monkeypatch):
    """sandbox 环境失败时不得启动宿主生成脚本。"""
    tools = ToolRuntime(tmp_path)

    class Unavailable:
        """模拟不可用的隔离环境。"""

        def execute(self, action, command, command_id):
            """拒绝执行并返回可辨识环境错误。"""
            raise RuntimeError("sandbox_unavailable")

    monkeypatch.setattr(sandbox, "for_workspace", lambda workspace: Unavailable())
    result = tools.execute(ToolCall("fixture", "exec", {"action": "run", "command": "touch host-marker"}))
    assert result.status == "failed"
    assert result.error == "sandbox_unavailable"
    assert not (tmp_path / "product/host-marker").exists()


def test_unknown_command_does_not_mask_confirmed_stop(tmp_path, monkeypatch):
    """未知命令不能掩盖底层已确认的物理停止，仍保留未知错误证据。"""
    runtime = sandbox.SandboxRuntime(tmp_path)
    path = tmp_path / "runtime.json"
    value = {"state": "unknown", "error": "unknown_side_effect"}
    monkeypatch.setattr(runtime, "_load", lambda sid: (path, value))
    calls = []

    class Runner:
        """模拟底层核对完成的停止。"""

        def stop(self):
            """返回前底层已经确认容器停止。"""
            calls.append("confirmed")

    monkeypatch.setattr(runtime, "_runner", lambda *args: Runner())
    result = runtime.stop("fixture")
    assert calls == ["confirmed"]
    assert result["state"] == "stopped" and result["error"] == "unknown_side_effect"


@pytest.mark.parametrize("launch", ["p.chromium.launch()", "p.chromium.launch(chromium_sandbox=False)",
                                   "p.chromium.launch(channel='chrome',chromium_sandbox=True)",
                                   "p.chromium.launch(chromium_sandbox=True,args=['--no-sandbox'])"])
def test_browser_contract_rejects_disabled_or_platform_browser(tmp_path, launch):
    """首版浏览器必须显式打开 sandbox 并使用配套 bundled Chromium。"""
    (tmp_path / "verify_product.py").write_text(launch)
    with pytest.raises(ValueError, match="sandbox_browser_contract_invalid"):
        sandbox.validate_browser_contract(tmp_path)


def test_browser_contract_accepts_explicit_sandbox(tmp_path):
    """明确的配套 Chromium 启动入口通过预检。"""
    (tmp_path / "verify_product.py").write_text("p.chromium.launch(headless=True,chromium_sandbox=True)")
    sandbox.validate_browser_contract(tmp_path)
