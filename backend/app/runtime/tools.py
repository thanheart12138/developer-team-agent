import os
import signal
import subprocess
import tempfile
from pathlib import Path

from .contracts import ToolCall, ToolResult

MAX_BYTES = 100 * 1024
COMMAND_TIMEOUT = 60


class ToolRuntime:
    def __init__(self, workspace: Path):
        # 初始化任务工作区目录和进程记录。
        # 固定任务工作区根路径，后续文件与命令只在该范围执行。
        self.workspace = workspace.resolve()
        self.product = self.workspace / "product"
        for name in ("messages", "docs", "evidence", "product"):
            (self.workspace / name).mkdir(parents=True, exist_ok=True)
        self._processes: dict[int, subprocess.Popen] = {}

    def _safe_path(self, value: str) -> Path:
        # 拒绝绝对路径和工作区外路径。
        raw = Path(value)
        if raw.is_absolute():
            raise ValueError("absolute_path_rejected")
        # 解析符号链接后再次检查，防止路径逃逸。
        target = (self.workspace / raw).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ValueError("path_outside_workspace")
        return target

    @staticmethod
    def _limited(value: bytes) -> tuple[str, bool]:
        # 限制工具输出大小并标记截断。
        return value[:MAX_BYTES].decode("utf-8", errors="replace"), len(value) > MAX_BYTES

    def execute(self, call: ToolCall) -> ToolResult:
        # 分派工具调用并统一包装成功或失败结果。
        try:
            # 按工具名选择受控处理器，不执行未注册的操作。
            handler = getattr(self, f"_{call.tool_name}")
        except AttributeError:
            return ToolResult(call.call_id, call.tool_name, "failed", error="unknown_tool")
        try:
            return ToolResult(call.call_id, call.tool_name, "succeeded", handler(**call.parameters))
        except Exception as exc:
            return ToolResult(call.call_id, call.tool_name, "failed", error=str(exc))

    def _read(self, path: str) -> dict:
        # 读取当前工作区文件并限制返回长度。
        # 所有读写先经过工作区路径校验。
        target = self._safe_path(path)
        content, truncated = self._limited(target.read_bytes())
        return {"path": path, "content": content, "truncated": truncated}

    def _write(self, path: str, content: str, overwrite: bool) -> dict:
        # 按覆盖标记原子写入文件并校验写入结果。
        # 所有读写先经过工作区路径校验。
        target = self._safe_path(path)
        # 创建与覆盖意图必须和磁盘现状一致。
        if target.exists() != overwrite:
            raise ValueError("overwrite_flag_mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode()
        # 先写临时文件并刷盘，再原子替换目标。
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        # 重读目标文件，确认写入的实际字节与请求一致。
        if target.read_bytes() != encoded:
            raise OSError("write_verification_failed")
        return {"path": path, "bytes_written": len(encoded)}

    def _exec(self, action: str, command: str | None = None, process_id: int | None = None) -> dict:
        # 运行命令或管理生成软件的后台进程。
        if action == "run":
            if not command:
                raise ValueError("command_required")
            try:
                # 同步命令受时间和输出长度限制。
                result = subprocess.run(command, cwd=self.product, shell=True, capture_output=True,
                                        timeout=COMMAND_TIMEOUT)
                stdout, stdout_cut = self._limited(result.stdout)
                stderr, stderr_cut = self._limited(result.stderr)
                return {"exit_code": result.returncode, "stdout": stdout, "stderr": stderr,
                        "timed_out": False, "truncated": stdout_cut or stderr_cut,
                        "process_id": None, "running": False}
            except subprocess.TimeoutExpired as exc:
                stdout, stdout_cut = self._limited(exc.stdout or b"")
                stderr, stderr_cut = self._limited(exc.stderr or b"")
                return {"exit_code": None, "stdout": stdout, "stderr": stderr,
                        "timed_out": True, "truncated": stdout_cut or stderr_cut,
                        "process_id": None, "running": False}
        if action == "start":
            if not command:
                raise ValueError("command_required")
            process_options = {"start_new_session": True} if os.name != "nt" else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            # 后台启动生成软件并登记进程，以便状态查询和停止。
            process = subprocess.Popen(command, cwd=self.product, shell=True, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, **process_options)
            self._processes[process.pid] = process
            return {"exit_code": None, "stdout": "", "stderr": "", "timed_out": False,
                    "truncated": False, "process_id": process.pid, "running": process.poll() is None}
        if not process_id:
            raise ValueError("process_id_required")
        process = self._processes.get(process_id)
        if process is None:
            raise ValueError("unknown_process")
        if action == "status":
            return {"exit_code": process.poll(), "stdout": "", "stderr": "", "timed_out": False,
                    "truncated": False, "process_id": process_id, "running": process.poll() is None}
        # 先请求进程组退出，超时后再强制终止。
        if action == "stop":
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process_id), "/T", "/F"],
                                   capture_output=True, timeout=5)
                else:
                    os.killpg(os.getpgid(process_id), signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(os.getpgid(process_id), signal.SIGKILL)
                    process.wait(timeout=5)
            return {"exit_code": process.returncode, "stdout": "", "stderr": "", "timed_out": False,
                    "truncated": False, "process_id": process_id, "running": False}
        raise ValueError("invalid_exec_action")


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "read", "description": "Read a workspace file",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write", "description": "Atomically create or replace a workspace file",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"},
      "content": {"type": "string"}, "overwrite": {"type": "boolean"}},
      "required": ["path", "content", "overwrite"]}}},
    {"type": "function", "function": {"name": "exec", "description": "Run or manage a process in product directory",
     "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["run", "start", "stop", "status"]},
      "command": {"type": "string"}, "process_id": {"type": "integer"}}, "required": ["action"]}}},
]
