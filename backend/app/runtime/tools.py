import os
import hashlib
import signal
import subprocess
import tempfile
from pathlib import Path

from .contracts import ToolCall, ToolResult
from .tool_summaries import ToolSummaryStore

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
            # 操作目的仅供摘要登记，不改变底层工具参数与执行语义。
            parameters = {key: value for key, value in call.parameters.items() if key != "description"}
            return ToolResult(call.call_id, call.tool_name, "succeeded", handler(**parameters))
        except Exception as exc:
            return ToolResult(call.call_id, call.tool_name, "failed", error=str(exc))

    def _read(self, path: str, start_line: int | None = None, end_line: int | None = None) -> dict:
        # 读取当前工作区文件；可按行局部读取，并限制返回长度。
        # 所有读写先经过工作区路径校验。
        target = self._safe_path(path)
        encoded = target.read_bytes()
        if start_line is not None or end_line is not None:
            if type(start_line) is not int or type(end_line) is not int or start_line < 1 or end_line < start_line:
                raise ValueError("invalid_line_range")
            lines = encoded.decode("utf-8").splitlines(keepends=True)
            selected = "".join(lines[start_line - 1:end_line]).encode()
            content, truncated = self._limited(selected)
            return {"path": path, "content": content, "truncated": truncated,
                    "start_line": start_line, "end_line": min(end_line, len(lines)),
                    "total_lines": len(lines), "sha256": hashlib.sha256(encoded).hexdigest()}
        content, truncated = self._limited(encoded)
        return {"path": path, "content": content, "truncated": truncated,
                "total_lines": encoded.count(b"\n") + (not encoded.endswith(b"\n")),
                "sha256": hashlib.sha256(encoded).hexdigest()}

    def _get_file_change_history(self, file_path: str, cursor: int | None = None) -> dict:
        # 查询当前任务内的文件写入历史及当前版本一致性。
        return ToolSummaryStore(self.workspace).file_history(file_path, cursor)

    def _get_model_call_summaries(self, model_call_id: str, cursor: int | None = None) -> dict:
        # 查询指定模型调用发起的一批工具执行摘要。
        return ToolSummaryStore(self.workspace).model_call(model_call_id, cursor)

    def _get_tool_execution_detail(self, summary_id: str, section: str = "result", cursor: int | None = None) -> dict:
        # 分页读取原始历史工具证据，不重新执行工具或读取其他任务。
        return ToolSummaryStore(self.workspace).detail(summary_id, section, cursor)

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

    def _replace(self, path: str, old: str, new: str) -> dict:
        # 只允许唯一精确片段替换，避免大文件返修必须整文件重写。
        target = self._safe_path(path)
        content = target.read_text(encoding="utf-8")
        count = content.count(old)
        if count != 1:
            raise ValueError(f"replace_match_count:{count}")
        updated = content.replace(old, new, 1)
        result = self._write(path, updated, overwrite=True)
        return {**result, "replacements": 1}

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
    {"type": "function", "function": {"name": "read", "description": "Read a workspace file, optionally by an inclusive line range",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"},
      "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}},
      "required": ["path"]}}},
    {"type": "function", "function": {"name": "write", "description": "Atomically create or replace a workspace file",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"},
      "content": {"type": "string"}, "overwrite": {"type": "boolean"}},
      "required": ["path", "content", "overwrite"]}}},
    {"type": "function", "function": {"name": "replace",
     "description": "Replace one unique exact text fragment in an existing workspace file; use for small edits to large files",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"},
      "old": {"type": "string"}, "new": {"type": "string"}},
      "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {"name": "exec", "description": "Run or manage a process in product directory",
     "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["run", "start", "stop", "status"]},
      "command": {"type": "string"}, "process_id": {"type": "integer"}}, "required": ["action"]}}},
]

QUERY_TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "get_file_change_history",
     "description": "Get this task's successful writes to a file, newest first, with SHA-256 and model call IDs",
     "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0}},
                    "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "get_model_call_summaries",
     "description": "Get this task's tool execution summaries for one model call ID in execution order",
     "parameters": {"type": "object", "properties": {"model_call_id": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0}},
                    "required": ["model_call_id"]}}},
    {"type": "function", "function": {"name": "get_tool_execution_detail",
     "description": "Read historical evidence by summary ID, never re-execute. Use read for current file content. Continue using next_cursor",
     "parameters": {"type": "object", "properties": {"summary_id": {"type": "string"},
                    "section": {"type": "string", "enum": ["call", "result", "all"]}, "cursor": {"type": "integer", "minimum": 0}},
                    "required": ["summary_id"]}}},
]

# 模型可提供简短目的，旧工具记录与程序发起调用仍允许缺省。
for schema in TOOL_SCHEMAS + QUERY_TOOL_SCHEMAS:
    schema["function"]["parameters"]["properties"]["description"] = {
        "type": "string", "maxLength": 200, "description": "Brief purpose of this operation; not a claim of success"}
