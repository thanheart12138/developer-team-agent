"""在完整修改批次及新诊断后接力 DeepSeek 上下文，原始执行历史不删改。"""

import hashlib
import json

from .tools import ToolRuntime


def covered_end_line(output: dict) -> int:
    # 只把实际返回的完整行算作可用范围，字节截断的半行不证明完整读取。
    lines = output.get("content", "").splitlines(keepends=True)
    count = len(lines)
    if output.get("truncated") and lines and not lines[-1].endswith(("\n", "\r")):
        count -= 1
    return output.get("start_line", 1) + count - 1


class DeepSeekContextRelay:
    def __init__(self, tools: ToolRuntime, run_id: int, history_key: str):
        # 每个执行循环独立保存边界；恢复不改变检查点、调用计数或工具执行。
        self.tools = tools
        self.run_id = run_id
        self.history_key = history_key
        key = hashlib.sha256(history_key.encode()).hexdigest()[:12]
        self.path = tools.workspace / f"evidence/deepseek-context-session-{run_id}-{key}.json"
        self.boundaries = []
        if self.path.is_file():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if (isinstance(saved, dict) and saved.get("run_id") == run_id
                        and saved.get("history_key") == history_key and isinstance(saved.get("boundaries"), list)
                        and all(isinstance(boundary, dict) for boundary in saved["boundaries"])):
                    self.boundaries = saved["boundaries"]
            except (OSError, ValueError, KeyError):
                # 边界证据不可用时沿用完整协议历史，不猜测截断位置。
                self.boundaries = []

    @staticmethod
    def _boundary_end(history: list[dict], boundary: dict) -> int | None:
        # 核对整批调用 ID 和所有结果，只允许在完整 assistant/tool 批次之后切开。
        indices = [i for i, entry in enumerate(history)
                   if entry.get("model_request_id") == boundary.get("model_request_id")]
        if not indices or indices != list(range(indices[0], indices[-1] + 1)):
            return None
        entries = [history[i] for i in indices]
        if ([entry.get("action", {}).get("call_id") for entry in entries] != boundary.get("call_ids")
                or not all(entry.get("result") for entry in entries)):
            return None
        return indices[-1] + 1

    def complete_batch(self, history: list[dict], request_id: str, call_ids: list[str], diagnostic: dict) -> None:
        # 调用方取得当前版本诊断后登记整批边界，保留每次接力的可追溯依据。
        batch = [entry for entry in history if entry.get("model_request_id") == request_id]
        boundary = {"model_request_id": request_id, "call_ids": call_ids,
                    "reason": "changed_files_and_current_diagnostic",
                    "diagnostic_ref": diagnostic.get("detail_path"),
                    "file_versions": diagnostic.get("file_hashes_after"),
                    "recent_changes": [
                        {"tool_name": entry["action"]["tool_name"],
                         "path": entry["action"]["parameters"].get("path"),
                         "description": entry["action"]["parameters"].get("description", "")[:200]}
                        for entry in batch if entry.get("action", {}).get("tool_name") in {"write", "replace"}
                        and entry.get("result", {}).get("status") == "succeeded"]}
        if self._boundary_end(history, boundary) is None:
            return
        self.boundaries.append(boundary)
        # 原子写入独立证据，避免边界标记参与原有无进展计算或动作恢复。
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"run_id": self.run_id, "history_key": self.history_key,
                                         "boundaries": self.boundaries}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def _known_files(self, history: list[dict], focus_paths: set[str] | None = None) -> tuple[list[dict], list[str], list[dict]]:
        # 合并真正读过或完整写过的范围，不因重建把未读文件全文加入模型上下文。
        ranges = {}
        report_refs = set()
        for entry in history:
            action, result = entry.get("action", {}), entry.get("result", {})
            if result.get("status") != "succeeded" or action.get("tool_name") not in {"read", "write"}:
                continue
            parameters = action["parameters"]
            try:
                path = str(self.tools._safe_path(parameters["path"]).relative_to(self.tools.workspace))
            except (KeyError, ValueError, TypeError):
                continue
            # 诊断报告绑定当时的产品版本，不能当作当前代码正文接力；保留按需引用。
            if path.startswith("evidence/slice-repair-diagnostic-") and path.endswith(".json"):
                report_refs.add(path)
                continue
            output = result.get("output", {})
            if action["tool_name"] == "write":
                if not isinstance(parameters.get("content"), str):
                    continue
                first, last = 1, None
            else:
                if not isinstance(output.get("content"), str):
                    continue
                first, last = output.get("start_line", 1), covered_end_line(output)
                if not output.get("truncated") and first == 1 and last == output.get("total_lines"):
                    last = None
                elif last < first:
                    continue
            ranges.setdefault(path, []).append((first, last))
        files = []
        file_refs = []
        for path, spans in sorted(ranges.items()):
            merged = []
            for first, last in sorted(spans, key=lambda span: span[0]):
                if merged and (merged[-1][1] is None or first <= merged[-1][1] + 1):
                    previous = merged[-1][1]
                    merged[-1][1] = None if previous is None or last is None else max(previous, last)
                else:
                    merged.append([first, last])
            for first, last in merged:
                # 省略的已知源码可按原权限补读，引用不证明本次请求已有正文。
                if focus_paths is not None and path.startswith("product/") and path not in focus_paths:
                    file_refs.append({"path": path, "start_line": first, "end_line": last,
                                      "content_source": "read_on_demand"})
                    continue
                try:
                    # 使用现有受控读取及字节上限刷新正文，权限变化和路径逃逸仍会拒绝。
                    target = self.tools._safe_path(path)
                    if hasattr(self.tools, "readable") and target not in self.tools.readable:
                        raise ValueError("unit_read_outside_scope")
                    total = len(target.read_text(encoding="utf-8").splitlines())
                    if total < first and total != 0:
                        raise ValueError("known_range_no_longer_available")
                    output = self.tools._read(path, first, min(last or total, total)) if total else self.tools._read(path)
                    files.append({**output, "covered_end_line": covered_end_line(output),
                                  "complete": not output.get("truncated") and output.get("start_line", 1) == 1
                                  and covered_end_line(output) == output.get("total_lines")})
                except (OSError, ValueError):
                    # 缺失及已撤销权限的内容不作为正文，也不能授权重复读取保护。
                    files.append({"path": path, "status": "unavailable", "complete": False})
        return files, sorted(report_refs), file_refs

    @staticmethod
    def focus_paths(context: dict, boundary: dict) -> set[str] | None:
        # 仅依据当前有效诊断与最近修改选择源码，无法定位时保留全部已知范围。
        source = context.get("current_task", {}).get("latest_evidence", {}).get("source_ref")
        report = context.get(source) if source else context.get("unit_diagnostic")
        if not isinstance(report, dict) or report.get("matches_current_files") is not True:
            return None
        changed = {item["path"] for item in boundary.get("recent_changes", []) if item.get("path")}
        if report.get("passed") is True:
            return changed
        output = report.get("result", {}).get("output", {})
        failure = "\n".join(str(value or "") for value in (
            report.get("failure_report"), output.get("stdout"), output.get("stderr")))
        failure = failure.replace("\\", "/")
        matches = {item["path"] for item in context.get("product_file_manifest", [])
                   if item["path"] in failure or item["path"].removeprefix("product/") in failure}
        if not matches:
            return None
        return matches | changed

    def project(self, history: list[dict], context: dict | None = None) -> tuple[list[dict], dict]:
        # 新会话只续传边界之后的完整协议轮次，旧文件知识从当前版本接力。
        if not self.boundaries:
            return history, {}
        boundary = self.boundaries[-1]
        if not all(key in boundary for key in ("model_request_id", "call_ids", "reason", "diagnostic_ref", "recent_changes")):
            return history, {}
        end = self._boundary_end(history, boundary)
        if end is None:
            return history, {}
        focus = self.focus_paths(context, boundary) if context is not None else None
        files, report_refs, file_refs = self._known_files(history[:end], focus)
        return history[end:], {"context_session": {"boundary_request_id": boundary["model_request_id"],
            "reason": boundary["reason"], "diagnostic_ref": boundary["diagnostic_ref"],
            "recent_changes": boundary["recent_changes"],
            "history_access": "get_model_call_summaries / get_tool_execution_detail"},
            "carried_file_context": files,
            "carried_file_refs": file_refs,
            "diagnostic_report_refs": [{"path": path, "content_source": "read_on_demand",
                "relation_to_boundary": "boundary_diagnostic" if path == boundary["diagnostic_ref"] else "historical_report"}
                for path in report_refs]}
