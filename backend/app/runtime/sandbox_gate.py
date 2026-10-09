"""以镜像、控制指纹与合成探针证据验证 sandbox 启用条件。"""

import hashlib
import json
from pathlib import Path
import subprocess

from . import sandbox


PROJECT = Path(__file__).resolve().parents[3]
PROFILE = PROJECT / "workspace/experiments/docker-isolation-20261005/profile.json"
REQUIRED = {"normal_node_browser", "readonly_files_env_network", "pid_limit", "memory_limit", "timeout",
            "output_bounded", "known_and_unknown_recovery", "completion_gates", "snapshot_inputs",
            "preview_restart", "integration"}


def gate_hash() -> str:
    """绑定启用检查本身，避免旧 profile 跨门禁实现复用。"""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def ready() -> bool:
    """缺失、损坏、证据变化或运行环境变化均保持关闭，不启动任何容器。"""
    try:
        if not PROFILE.is_file() or PROFILE.is_symlink():
            return False
        value = json.loads(PROFILE.read_text())
        if value.get("configuration_hash") != sandbox.configuration_hash() or value.get("gate_hash") != gate_hash():
            return False
        if any(value.get("checks", {}).get(key) is not True for key in REQUIRED):
            return False
        evidence = value.get("evidence_hashes", {})
        if not evidence:
            return False
        for relative, expected in evidence.items():
            path = (PROFILE.parent / relative).resolve()
            if not path.is_relative_to(PROFILE.parent) or not path.is_file():
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
        if sandbox.image_identity() != value["image_id"]:
            return False
        actual = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}} {{.Architecture}}"],
                                check=True, capture_output=True, text=True, timeout=5).stdout.strip()
        return actual == value["docker_identity"]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False
