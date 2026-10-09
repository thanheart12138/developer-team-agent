"""隔离快照和固定容器参数的本地机制验证，不代表真实 Docker 探针。"""

import json
import os

import pytest

from backend.app.runtime.container_execution import ContainerExecutionRuntime, IMAGE_CONFIG, configuration_hash, create_arguments, freeze_product, product_manifest, validate_container


def test_snapshot_matches_and_is_read_only(tmp_path):
    """冻结文件字节和权限，后续源文件修改不会改变快照。"""
    product = tmp_path / "product"
    product.mkdir()
    (product / "index.html").write_text("original")
    snapshot = tmp_path / "snapshot"
    manifest = freeze_product(product, snapshot)
    (product / "index.html").write_text("changed")
    assert product_manifest(snapshot) == manifest
    assert (snapshot / "index.html").read_text() == "original"
    assert snapshot.stat().st_mode & 0o222 == 0
    assert (snapshot / "index.html").stat().st_mode & 0o222 == 0


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "credential", "directory_link"])
def test_snapshot_rejects_unsafe_sources(tmp_path, kind):
    """凭据及外部链接不能进入模型执行快照。"""
    product = tmp_path / "product"
    product.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("dummy sentinel")
    target = product / "entry"
    if kind == "symlink":
        target.symlink_to(outside)
    elif kind == "directory_link":
        target.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "hardlink":
        os.link(outside, target)
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        (product / ".env.local").write_text("dummy")
    with pytest.raises(ValueError):
        freeze_product(product, tmp_path / "snapshot")
    assert outside.read_text() == "dummy sentinel"


def test_container_has_no_host_network_or_writable_bind(tmp_path):
    """参数生成保持断网、只读和资源限制，不接受可漂移镜像标签。"""
    arguments = create_arguments("repair-probe", tmp_path, "sha256:" + "a" * 64, {"task": "fixture"})
    assert arguments[arguments.index("--network") + 1] == "none"
    assert "--read-only" in arguments
    assert arguments[arguments.index("--mount") + 1].endswith("target=/product,readonly")
    assert "--privileged" not in arguments
    assert "--rm" not in arguments
    with pytest.raises(ValueError, match="immutable_image_required"):
        create_arguments("repair-probe", tmp_path, "latest", {})


def test_unknown_command_is_not_replayed(tmp_path, monkeypatch):
    """已记录意图却无宿主结果时停止，不能重跑未知副作用。"""
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    runtime = ContainerExecutionRuntime(snapshot, tmp_path / "evidence", "sha256:" + "a" * 64, {})
    calls = []
    monkeypatch.setattr(runtime, "create", lambda: calls.append("created"))
    intent = {"command_id": "probe1", "kind": "node", "arguments": [],
              "image_id": runtime.image_id, "manifest": {}, "labels": {}, "configuration_hash": configuration_hash()}
    path = runtime.evidence / "command-probe1.json"
    path.write_text(json.dumps({"intent": intent}))
    with pytest.raises(ValueError, match="outcome_unknown"):
        runtime.execute("probe1", "node")
    assert calls == []
    path.write_text(json.dumps({"intent": intent, "result": {"exit_code": 0}}))
    assert runtime.execute("probe1", "node") == {"exit_code": 0}
    assert calls == []


@pytest.mark.parametrize("arguments", [["--eval=bad"], ["../outside.js"], ["/host.js"]])
def test_node_arguments_cannot_escape_fixed_entry(tmp_path, arguments):
    """拒绝 Node 开关和快照外路径，在 Docker 副作用前停止。"""
    runtime = ContainerExecutionRuntime(tmp_path, tmp_path / "evidence", "sha256:" + "a" * 64, {})
    with pytest.raises(ValueError, match="invalid_container_arguments"):
        runtime.execute("probe", "node", arguments)


def test_inspection_rejects_unexpected_mounts_and_environment(tmp_path):
    """实际配置偏离断网、只读或凭据边界时拒绝启动。"""
    info = {"Image": "sha256:" + "a" * 64,
            "Config": {"User": "1000:1000", "Labels": {"probe": "1"}, "Env": ["HOME=/tmp"]},
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                           "PidMode": "", "IpcMode": "private", "PidsLimit": 256,
                           "Memory": 2147483648, "MemorySwap": 2147483648,
                           "NanoCpus": 2000000000, "ShmSize": 536870912,
                           "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges=true", "seccomp=" + (IMAGE_CONFIG / "seccomp.json").read_text()],
                           "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=268435456,mode=1777"}, "Init": True},
            "Mounts": [{"Type": "bind", "RW": False, "Source": str(tmp_path.resolve()), "Destination": "/product"}]}
    validate_container(info, tmp_path, info["Image"], {"probe": "1"})
    info["Config"]["Env"].append("DEEPSEEK_API_KEY=dummy")
    with pytest.raises(ValueError, match="environment_mismatch"):
        validate_container(info, tmp_path, info["Image"], {"probe": "1"})
    info["Config"]["Env"].pop()
    info["Mounts"][0]["RW"] = True
    with pytest.raises(ValueError, match="mount_mismatch"):
        validate_container(info, tmp_path, info["Image"], {"probe": "1"})
