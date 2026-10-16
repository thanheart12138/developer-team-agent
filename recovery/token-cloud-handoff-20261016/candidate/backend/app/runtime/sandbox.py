"""任务网站 sandbox 统一接口，Docker 细节只由底层 Runner 承载。"""

from datetime import datetime, timezone
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time

import httpx

from . import container_execution as container


def product_version(product: Path) -> str:
    """为完整产品清单生成稳定版本，新增和删除文件也会改变版本。"""
    value = json.dumps(container.product_manifest(product), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def configuration_hash() -> str:
    """绑定统一接口、底层控制和预览实现，旧结果不能跨配置复用。"""
    digest = hashlib.sha256(container.configuration_hash().encode())
    for path in (Path(__file__), Path(__file__).with_name("snapshot_preview.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def image_identity() -> str:
    """解析唯一受控镜像标签到完整镜像 ID，缺镜像时不回退宿主。"""
    result = subprocess.run(["docker", "image", "inspect", container.IMAGE_TAG, "--format", "{{.Id}}"],
                            check=True, capture_output=True, text=True, timeout=15)
    return result.stdout.strip()


def now() -> str:
    """记录宿主 UTC 时间，不使用生成脚本自报时间。"""
    return datetime.now(timezone.utc).isoformat()


def validate_browser_contract(snapshot: Path) -> None:
    """检查首版明确 Chromium 启动契约，拒绝平台路径与关闭沙箱参数。"""
    tree = ast.parse((snapshot / "verify_product.py").read_text())
    launches = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "launch"]
    if not launches:
        raise ValueError("sandbox_browser_contract_invalid")
    for node in launches:
        values = {keyword.arg: keyword.value for keyword in node.keywords}
        flag = values.get("chromium_sandbox")
        if (not isinstance(node.func.value, ast.Attribute) or node.func.value.attr != "chromium"
                or not isinstance(flag, ast.Constant) or flag.value is not True
                or any(key in values for key in (None, "channel", "executable_path"))):
            raise ValueError("sandbox_browser_contract_invalid")
        for value in ast.walk(node):
            if isinstance(value, ast.Constant) and value.value in ("--no-sandbox", "--disable-setuid-sandbox"):
                raise ValueError("sandbox_browser_contract_invalid")


def for_workspace(workspace: Path):
    """只有显式新模式进入 sandbox，旧任务保持原有执行路径。"""
    from .repair_runtime import load
    state = load(workspace)
    return SandboxExecution(workspace, state) if state else None


class SandboxExecution:
    """连接现有工具协议和固定 sandbox 动作，不接受任意 shell。"""

    def __init__(self, workspace: Path, state: dict):
        """从宿主新模式记录绑定任务身份，不接受模型预算或挂载。"""
        self.runtime = SandboxRuntime(workspace)
        self.state = state

    def execute(self, action: str, command: str | None, command_id: str) -> dict:
        """将确定的 Node／浏览器命令映射到固定动作，其他操作拒绝。"""
        parts = shlex.split(command or "")
        if action != "run":
            raise ValueError("sandbox_requires_fixed_service_control")
        if parts[:2] == ["node", "--test"]:
            kind, paths = "run_unit_tests", parts[2:]
        elif (len(parts) == 3 and parts[0] in {"python", "python3", sys.executable}
              and parts[1] == "verify_product.py"):
            kind, paths = "run_browser_validation", []
        else:
            raise ValueError("sandbox_arbitrary_command_rejected")
        value = self.runtime.create(self.state["task_id"], str(self.state["event_id"]),
                                    product_version(self.runtime.workspace / "product"))
        result = self.runtime.execute(value["sandbox_id"], command_id, kind, paths)
        if result["output"].get("truncated"):
            raise RuntimeError("sandbox_output_truncated")
        if kind == "run_browser_validation" and result["exit_code"] != 0:
            error = result["output"].get("stderr", "")
            if "BrowserType.launch:" in error or "Executable doesn't exist" in error:
                raise RuntimeError("sandbox_browser_environment_error")
        before = result["output"].get("resource_events_before", {})
        after = result["output"].get("resource_events_after", {})
        for file, counter in (("memory.events", "oom_kill"), ("pids.events", "max")):
            if int(after.get(file, {}).get(counter, 0)) > int(before.get(file, {}).get(counter, 0)):
                raise RuntimeError("sandbox_resource_exhausted")
        return {**result["output"], "timed_out": result["timed_out"], "process_id": None,
                "running": False, "sandbox": result}

    def start_preview(self, task) -> dict:
        """固定服务核对内部健康后提供同快照预览，宿主只执行可信服务模块。"""
        root = self.runtime.workspace
        value = self.runtime.create(self.state["task_id"], str(self.state["event_id"]), product_version(root / "product"))
        health = self.runtime.execute(value["sandbox_id"], "service-health", "health_check")
        if health["output"].get("status") != 200:
            raise RuntimeError("sandbox_internal_service_unavailable")
        reference = root / "evidence/sandbox-preview-reference.json"
        record = root / "evidence/sandbox-preview.json"
        selected = {"snapshot": value["snapshot"], "submission_id": self.state["submission_id"]}
        previous = json.loads(record.read_text()) if record.exists() else None
        restart_port = None
        history = previous.get("history", []) if previous else []
        if previous and previous["status"] != "running":
            raise RuntimeError("sandbox_preview_outcome_unknown")
        if previous:
            # 只确认本任务可信服务；不终止未知 PID 或静默切换到新 origin。
            try:
                with httpx.Client(trust_env=False, timeout=2) as client:
                    actual = client.get(previous["url"] + "/__repair_health").json()
                if actual != json.loads(reference.read_text())["health"]:
                    raise RuntimeError("sandbox_preview_identity_mismatch")
            except httpx.TransportError:
                # 只有已知服务确实死亡才重启；活进程异常或未知启动结果不重放。
                try:
                    os.waitpid(previous["process_id"], os.WNOHANG)
                except ChildProcessError:
                    pass
                try:
                    os.kill(previous["process_id"], 0)
                except ProcessLookupError:
                    restart_port = previous["port"]
                    history = [*history, {key: value for key, value in previous.items() if key != "history"}]
                    previous = None
                else:
                    raise RuntimeError("sandbox_preview_process_unhealthy")
        if previous:
            self.runtime._save(reference, {**selected, "health": {"submission_id": selected["submission_id"]}})
            service = previous
        else:
            with socket.socket() as listener:
                # 与可信 HTTPServer 的端口复用策略一致，允许已停止连接的 TIME_WAIT。
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    # 已有网站沿用原端口；占用时停止并等待服务交接决定，不杀未知进程。
                    listener.bind(("127.0.0.1", restart_port or task.port or 0))
                except OSError as exc:
                    raise RuntimeError("sandbox_existing_preview_origin_requires_decision") from exc
                port = listener.getsockname()[1]
            command = [sys.executable, "-m", "backend.app.runtime.snapshot_preview", "--reference", str(reference), "--port", str(port)]
            service = {"url": f"http://127.0.0.1:{port}", "port": port, "process_id": None,
                       "command": shlex.join(command), "status": "starting", "history": history}
            self.runtime._save(reference, {**selected, "health": {"submission_id": selected["submission_id"]}})
            self.runtime._save(record, service)
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[3],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            service["process_id"] = process.pid
            self.runtime._save(record, service)
        # 宿主健康返回当前提交，验证和预览的地址分别落证。
        healthy = False
        for _ in range(20):
            try:
                with httpx.Client(trust_env=False, timeout=1) as client:
                    healthy = client.get(service["url"] + "/__repair_health").json() == {"submission_id": selected["submission_id"]}
                if healthy:
                    break
            except (httpx.HTTPError, ValueError):
                time.sleep(0.1)
        if not healthy:
            raise RuntimeError("sandbox_preview_unavailable")
        service.update(status="running", sandbox_id=value["sandbox_id"], internal_url=value["internal_url"])
        self.runtime._save(record, service)
        return service


class SandboxRuntime:
    """程序专用任务 sandbox，固定版本、动作及宿主证据。"""

    def __init__(self, workspace: Path):
        """绑定宿主可信任务根目录，不接收模型挂载或环境设置。"""
        self.workspace = workspace.resolve()

    def _path(self, sandbox_id: str) -> Path:
        """只访问本任务固定格式身份记录，阻止路径注入。"""
        if not re.fullmatch(r"[0-9a-f]{64}", sandbox_id):
            raise ValueError("invalid_sandbox_id")
        return self.workspace / "evidence" / f"sandbox-{sandbox_id}" / "runtime.json"

    def _save(self, path: Path, value: dict) -> None:
        """原子保存宿主控制记录，容器不挂载此目录。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".pending")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temporary.replace(path)

    def _load(self, sandbox_id: str) -> tuple[Path, dict]:
        """加载本任务记录并核对控制版本，拒绝过期配置恢复。"""
        path = self._path(sandbox_id)
        value = json.loads(path.read_text())
        if value["sandbox_id"] != sandbox_id or value["configuration_hash"] != configuration_hash():
            raise ValueError("sandbox_identity_mismatch")
        expected = self.workspace / "isolation" / value["attempt_id"] / "snapshots" / value["version_id"] / "product"
        if value["snapshot"] != str(expected):
            raise ValueError("sandbox_snapshot_changed")
        if value["state"] != "unknown" and product_version(expected) != value["version_id"]:
            raise ValueError("sandbox_snapshot_changed")
        return path, value

    def _runner(self, path: Path, value: dict) -> container.ContainerExecutionRuntime:
        """仅从宿主登记身份构造底层，调用方不能覆盖隔离策略。"""
        return container.ContainerExecutionRuntime(Path(value["snapshot"]), path.parent, value["image_id"],
                                                  {"ai-agent-product.sandbox": value["sandbox_id"],
                                                   "ai-agent-product.task": str(value["task_id"]),
                                                   "ai-agent-product.attempt": value["attempt_id"],
                                                   "ai-agent-product.version": value["version_id"]})

    def create(self, task_id: int, attempt_id: str, source_version: str) -> dict:
        """核对源版本并冻结产品，创建后实际检查容器，失败保留现场。"""
        if type(task_id) is not int or task_id < 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", attempt_id):
            raise ValueError("invalid_sandbox_identity")
        if source_version != product_version(self.workspace / "product"):
            raise ValueError("sandbox_source_changed")
        sandbox_id = hashlib.sha256(f"{task_id}:{attempt_id}:{source_version}".encode()).hexdigest()
        path = self._path(sandbox_id)
        if path.exists():
            _, value = self._load(sandbox_id)
            if value["state"] != "running":
                raise ValueError("sandbox_not_running")
            if self.inspect(sandbox_id)["state"] != "running":
                raise ValueError("sandbox_not_running")
            return value
        snapshot = self.workspace / "isolation" / attempt_id / "snapshots" / source_version / "product"
        value = {"sandbox_id": sandbox_id, "task_id": task_id, "attempt_id": attempt_id,
                 "version_id": source_version, "snapshot": str(snapshot), "image_id": image_identity(),
                 "configuration_hash": configuration_hash(), "state": "preparing", "created_at": now(),
                 "internal_url": "http://127.0.0.1:8080", "evidence_ref": str(path.relative_to(self.workspace))}
        self._save(path, value)
        try:
            # 冻结与创建属于程序副作用，失败不覆盖或删除半完成现场。
            container.freeze_product(self.workspace / "product", snapshot)
            if product_version(snapshot) != source_version or product_version(self.workspace / "product") != source_version:
                raise ValueError("sandbox_source_changed")
            value["container_id"] = self._runner(path, value).create()
            value["state"] = "running"
            self._save(path, value)
            return value
        except Exception as exc:
            value.update(state="unknown", error=type(exc).__name__)
            self._save(path, value)
            raise

    def inspect(self, sandbox_id: str, command_id: str | None = None) -> dict:
        """只查询实际容器及宿主结果，不启动、执行或重放动作。"""
        path, value = self._load(sandbox_id)
        if value["state"] == "unknown":
            return {**value, "command_result": None, "error": "unknown_side_effect"}
        runner = self._runner(path, value)
        saved = json.loads(runner.record.read_text())
        info = container.inspect_container(saved["container_id"])
        container.validate_container(info, runner.snapshot, runner.image_id, runner.labels)
        result = {**value, "state": "running" if info["State"]["Running"] else "stopped"}
        if command_id is not None:
            key = hashlib.sha256(command_id.encode()).hexdigest()
            evidence = path.parent / f"result-{key}.json"
            result["command_result"] = json.loads(evidence.read_text()) if evidence.exists() else None
            intent = path.parent / f"command-{key}.json"
            if intent.exists() and "result" not in json.loads(intent.read_text()):
                result["error"] = "unknown_side_effect"
        return result

    def execute(self, sandbox_id: str, command_id: str, action: str, test_paths: list[str] | None = None) -> dict:
        """执行固定动作，绑定实际结果与版本，不将执行完成视为业务通过。"""
        actions = {"run_unit_tests": "node", "health_check": "health", "run_browser_validation": "browser"}
        if action not in actions or not command_id or (action != "run_unit_tests" and test_paths):
            raise ValueError("invalid_sandbox_action")
        path, value = self._load(sandbox_id)
        if value["state"] != "running":
            raise ValueError("sandbox_not_running")
        runner = self._runner(path, value)
        paths = test_paths or []
        if action == "run_browser_validation":
            # 预检不是恶意代码证明；实际执行仍必须依靠容器边界和独立目标审查。
            validate_browser_contract(runner.snapshot)
        for relative in paths:
            if (Path(relative).is_absolute() or relative.startswith("-") or ".." in Path(relative).parts
                    or relative not in container.product_manifest(runner.snapshot)):
                raise ValueError("invalid_sandbox_test_path")
        key = hashlib.sha256(command_id.encode()).hexdigest()
        started = now()
        # 底层保存意图和结果；完整记录存在时复用，未知结果不重放。
        try:
            output = runner.execute(key, actions[action], paths)
        except Exception:
            intent = path.parent / f"command-{key}.json"
            if intent.exists() and "result" not in json.loads(intent.read_text()):
                value.update(state="unknown", error="unknown_side_effect")
                self._save(path, value)
            raise
        result = {"sandbox_id": sandbox_id, "task_id": value["task_id"], "attempt_id": value["attempt_id"],
                  "version_id": value["version_id"], "command_id": command_id, "action": action,
                  "image_id": value["image_id"], "configuration_hash": value["configuration_hash"],
                  "started_at": output.get("started_at", started), "finished_at": output.get("finished_at", now()), "output": output,
                  "exit_code": output.get("exit_code"), "timed_out": output.get("error") == "container_execution_timeout",
                  "oom_killed": None, "evidence_ref": str((path.parent / f"result-{key}.json").relative_to(self.workspace))}
        before = output.get("resource_events_before", {}).get("memory.events", {})
        after = output.get("resource_events_after", {}).get("memory.events", {})
        if "oom_kill" in before and "oom_kill" in after:
            result["oom_killed"] = int(after["oom_kill"]) > int(before["oom_kill"])
        evidence = self.workspace / result["evidence_ref"]
        if evidence.exists():
            return json.loads(evidence.read_text())
        self._save(evidence, result)
        if result["timed_out"]:
            value.update(state="stopped", stopped_at=now())
            self._save(path, value)
        return result

    def stop(self, sandbox_id: str) -> dict:
        """核对身份并停止整个 sandbox，实际停止确认后更新宿主记录。"""
        path, value = self._load(sandbox_id)
        self._runner(path, value).stop()
        # 底层 stop 已核对实际 Running 为 False；未知命令状态不应遮蔽物理停止结果。
        value.update(state="stopped", stopped_at=now())
        self._save(path, value)
        return value
