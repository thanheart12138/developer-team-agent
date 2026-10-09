"""返修容器的只读快照与固定 Docker 配置，未验证时不开放入口。"""

import hashlib
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import uuid


IMAGE_TAG = "ai-agent-product/website-repair:pw-1.55.0-v1"
IMAGE_CONFIG = Path(__file__).resolve().parents[3] / "runtime-images/website-repair"


def _read_regular(root: Path, relative: Path) -> bytes:
    """逐层打开目录描述符，拒绝读取期间被替换的父目录链接。"""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsupported_snapshot_file")
            return stream.read()
    finally:
        os.close(directory)


def configuration_hash() -> str:
    """绑定控制实现和镜像配置，使旧探针不能证明新实现已隔离。"""
    digest = hashlib.sha256()
    for path in [Path(__file__), *[IMAGE_CONFIG / name for name in ("Dockerfile", "controller.py", "seccomp.json", ".dockerignore")]]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def product_manifest(product: Path) -> dict[str, str]:
    """只接受普通产品文件，拒绝链接、特殊文件和凭据路径。"""
    if product.is_symlink() or not product.is_dir():
        raise ValueError("invalid_product_root")
    result = {}
    for directory, directories, files in os.walk(product, followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            info = path.lstat()
            if name.startswith(".env") or name in {".git", "secrets", ".aws", ".codex", ".agents"}:
                raise ValueError("forbidden_snapshot_path")
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError("unsupported_snapshot_file")
            if stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise ValueError("snapshot_hardlink_forbidden")
                # 禁止在检查后通过符号链接替换，将读取限定到普通文件。
                relative = path.relative_to(product)
                result[relative.as_posix()] = hashlib.sha256(_read_regular(product, relative)).hexdigest()
    return result


def freeze_product(product: Path, destination: Path) -> dict[str, str]:
    """复制并核对产品版本，失败保留现场，成功快照仅允许读取。"""
    expected = product_manifest(product)
    destination.mkdir(parents=True, exist_ok=False)
    for relative in expected:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_read_regular(product, Path(relative)))
        target.chmod(0o444)
    if product_manifest(destination) != expected or product_manifest(product) != expected:
        raise ValueError("snapshot_source_changed")
    for directory, _, _ in os.walk(destination, topdown=False):
        Path(directory).chmod(0o555)
    return expected


def create_arguments(name: str, snapshot: Path, image_id: str, labels: dict[str, str]) -> list[str]:
    """构造固定限制的容器参数，不接受模型 shell 或宿主环境转发。"""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("immutable_image_required")
    command = ["docker", "create", "--name", name, "--network", "none", "--read-only",
               "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
               "--security-opt", f"seccomp={IMAGE_CONFIG / 'seccomp.json'}", "--pids-limit", "256",
               "--cpus", "2", "--memory", "2g", "--memory-swap", "2g", "--ipc", "private",
               "--shm-size", "512m", "--tmpfs", "/tmp:rw,nosuid,nodev,size=268435456,mode=1777",
               "--init", "--restart", "no", "--log-driver", "local", "--log-opt", "max-size=1m",
               "--log-opt", "max-file=2", "--mount", f"type=bind,source={snapshot.resolve()},target=/product,readonly"]
    for key, value in sorted(labels.items()):
        command.extend(["--label", f"{key}={value}"])
    return [*command, image_id]


def inspect_container(container_id: str) -> dict:
    """读取专用容器配置，调用者核对身份后才可启动或停止。"""
    completed = subprocess.run(["docker", "inspect", container_id], check=True,
                               capture_output=True, text=True, timeout=15)
    return json.loads(completed.stdout)[0]


def validate_container(info: dict, snapshot: Path, image_id: str, labels: dict[str, str]) -> None:
    """启动前逐字段核对身份和隔离边界，不以创建参数代替实际配置。"""
    config, host = info["Config"], info["HostConfig"]
    expected = {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                "PidMode": "", "IpcMode": "private", "PidsLimit": 256,
                "Memory": 2147483648, "MemorySwap": 2147483648,
                "NanoCpus": 2000000000, "ShmSize": 536870912}
    if info["Image"] != image_id or config["User"] != "1000:1000":
        raise ValueError("container_identity_mismatch")
    if any(config.get("Labels", {}).get(key) != value for key, value in labels.items()):
        raise ValueError("container_identity_mismatch")
    if any(host.get(key) != value for key, value in expected.items()):
        raise ValueError("container_isolation_mismatch")
    if host.get("CapDrop") != ["ALL"] or host.get("CapAdd") or host.get("Devices") or host.get("PortBindings"):
        raise ValueError("container_isolation_mismatch")
    security = host.get("SecurityOpt", [])
    if "no-new-privileges=true" not in security or not any(item.startswith("seccomp=") for item in security):
        raise ValueError("container_security_mismatch")
    # Docker CLI 将 profile 内容提交给 daemon；禁止把 unconfined 视为有效 profile。
    seccomp = next(item.split("=", 1)[1] for item in security if item.startswith("seccomp="))
    try:
        if json.loads(seccomp) != json.loads((IMAGE_CONFIG / "seccomp.json").read_text()):
            raise ValueError("container_security_mismatch")
    except json.JSONDecodeError as exc:
        raise ValueError("container_security_mismatch") from exc
    if host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev,size=268435456,mode=1777"} or host.get("Init") is not True:
        raise ValueError("container_temporary_storage_mismatch")
    mounts = info.get("Mounts", [])
    if len(mounts) != 1 or mounts[0].get("Type") != "bind" or mounts[0].get("RW") is not False:
        raise ValueError("container_mount_mismatch")
    if mounts[0]["Source"] != str(snapshot.resolve()) or mounts[0]["Destination"] != "/product":
        raise ValueError("container_mount_mismatch")
    environment = dict(item.split("=", 1) for item in config.get("Env", []))
    allowed = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PYTHONDONTWRITEBYTECODE",
               "PYTHONUNBUFFERED", "PLAYWRIGHT_BROWSERS_PATH"}
    if set(environment) - allowed or environment.get("HOME") != "/tmp":
        raise ValueError("container_environment_mismatch")


class ContainerExecutionRuntime:
    """专用容器固定命令执行器，宿主证据是恢复结果的唯一来源。"""

    def __init__(self, snapshot: Path, evidence: Path, image_id: str, labels: dict[str, str]):
        """绑定不可变产品版本与宿主证据目录，不自动创建或执行容器。"""
        self.snapshot, self.evidence, self.image_id, self.labels = snapshot, evidence, image_id, labels
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.record = self.evidence / "container.json"

    def _save(self, path: Path, value: dict) -> None:
        """在宿主原子保存控制证据，容器无法写入该目录。"""
        temporary = path.with_suffix(".pending")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temporary.replace(path)

    def create(self) -> str:
        """先记录创建意图，实际配置核对通过后才启动专用容器。"""
        if self.record.exists():
            saved = json.loads(self.record.read_text())
            if saved.get("configuration_hash") != configuration_hash():
                raise ValueError("container_configuration_changed")
            if "container_id" not in saved:
                raise ValueError("container_creation_outcome_unknown")
            validate_container(inspect_container(saved["container_id"]), self.snapshot, self.image_id, self.labels)
            return saved["container_id"]
        name = "repair-v1-" + uuid.uuid4().hex
        value = {"name": name, "image_id": self.image_id, "labels": self.labels,
                 "snapshot": str(self.snapshot), "configuration_hash": configuration_hash(), "status": "creating"}
        self._save(self.record, value)
        result = subprocess.run(create_arguments(name, self.snapshot, self.image_id, self.labels),
                                check=True, capture_output=True, text=True, timeout=30)
        container_id = result.stdout.strip()
        validate_container(inspect_container(container_id), self.snapshot, self.image_id, self.labels)
        value.update(container_id=container_id, status="created")
        self._save(self.record, value)
        # 只有已核对配置的容器可启动；失败保留现场，不删除或降级。
        subprocess.run(["docker", "start", container_id], check=True, capture_output=True, timeout=15)
        value["status"] = "running"
        self._save(self.record, value)
        return container_id

    def stop(self) -> None:
        """核对身份后停止整个容器及后代，保留容器和快照。"""
        saved = json.loads(self.record.read_text())
        container_id = saved["container_id"]
        validate_container(inspect_container(container_id), self.snapshot, self.image_id, self.labels)
        subprocess.run(["docker", "stop", "--time", "2", container_id],
                       check=True, capture_output=True, timeout=15)
        if inspect_container(container_id)["State"]["Running"]:
            raise RuntimeError("container_stop_not_confirmed")

    def execute(self, command_id: str, kind: str, arguments: list[str] | None = None) -> dict:
        """记录固定命令意图并收集结果，未知副作用不重放，超时停止整个容器。"""
        if not command_id.isalnum() or kind not in {"node", "browser", "health"}:
            raise ValueError("invalid_container_command")
        arguments = arguments or []
        if kind != "node" and arguments:
            raise ValueError("invalid_container_arguments")
        if any(path.startswith("-") or Path(path).is_absolute() or ".." in Path(path).parts for path in arguments):
            raise ValueError("invalid_container_arguments")
        path = self.evidence / f"command-{command_id}.json"
        intent = {"command_id": command_id, "kind": kind, "arguments": arguments,
                  "image_id": self.image_id, "manifest": product_manifest(self.snapshot),
                  "labels": self.labels, "configuration_hash": configuration_hash()}
        if path.exists():
            saved = json.loads(path.read_text())
            if saved.get("intent") != intent:
                raise ValueError("container_command_identity_mismatch")
            if "result" not in saved:
                raise ValueError("container_command_outcome_unknown")
            return saved["result"]
        container_id = self.create()
        validate_container(inspect_container(container_id), self.snapshot, self.image_id, self.labels)
        started_at = datetime.now(timezone.utc).isoformat()
        self._save(path, {"intent": intent, "container_id": container_id, "started_at": started_at})
        action = ["health"] if kind == "health" else ["run", command_id, kind, *arguments]
        try:
            result = subprocess.run(["docker", "exec", container_id, "python", "/opt/repair/controller.py", *action],
                                    check=True, capture_output=True, text=True,
                                    timeout={"node": 120, "browser": 300, "health": 10}[kind])
            value = json.loads(result.stdout)
            if kind != "health" and value.get("command_id") != command_id:
                raise ValueError("container_command_result_mismatch")
        except subprocess.TimeoutExpired:
            self.stop()
            value = {"exit_code": None, "error": "container_execution_timeout"}
        value.update(started_at=started_at, finished_at=datetime.now(timezone.utc).isoformat())
        self._save(path, {"intent": intent, "container_id": container_id, "result": value})
        return value
