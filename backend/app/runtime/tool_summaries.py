"""工具执行摘要账本、上下文投影及当前任务内的只读查询。"""

import hashlib
import json
from pathlib import Path
import uuid

from .tracing import sanitize

PAGE_SIZE = 20
DETAIL_CHARS = 8000


class ToolSummaryStore:
    def __init__(self, workspace: Path):
        # 固定摘要账本归属，查询不接受其他任务或任意证据路径。
        self.workspace = workspace.resolve()
        self.path = self.safe_path("evidence/tool-summaries.jsonl")

    def safe_path(self, value: str) -> Path:
        # 检查相对路径及符号链接，拒绝工作区外的文件。
        if Path(value).is_absolute():
            raise ValueError("absolute_path_rejected")
        path = (self.workspace / value).resolve()
        if self.workspace not in path.parents:
            raise ValueError("path_outside_workspace")
        return path

    def file_state(self, value: str | None) -> dict:
        # 捕获实际文件字节哈希；非法路径不作为可查询文件登记。
        if not isinstance(value, str):
            return {}
        try:
            path = self.safe_path(value)
        except ValueError:
            return {}
        return {"file_path": str(path.relative_to(self.workspace)),
                "hash": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}

    def load(self) -> list[dict]:
        # 读取完整账本，损坏时显式失败，不猜测遗漏的执行结果。
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line] if self.path.is_file() else []

    def record(self, run_id: int, history_key: str, parent_id: str | None, call,
               result, before: dict, evidence_ref: dict, code_hashes: dict,
               blocked: bool = False) -> dict:
        # 按真实执行结果构建短摘要，同一执行重复登记保持幂等。
        records = self.load()
        identity = json.dumps([str(self.workspace), run_id, parent_id, call.call_id], ensure_ascii=False)
        summary_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        existing = next((row for row in records if row["summary_id"] == summary_id), None)
        if existing:
            return existing
        parameters = call.parameters
        output = result.output
        failed = (result.status != "succeeded" or output.get("timed_out")
                  or (call.tool_name == "exec" and parameters.get("action") == "run"
                      and (output.get("exit_code") != 0 or "[SKIP]" in output.get("stdout", "")))
                  or (call.tool_name == "exec" and parameters.get("action") == "start" and not output.get("running")))
        status = "blocked" if blocked else "failed" if failed else "succeeded"
        row = {"summary_id": summary_id, "parent_model_call_id": parent_id,
               "tool_call_id": call.call_id, "step_run_id": run_id, "history_key": history_key,
               "sequence": len(records) + 1, "tool_name": call.tool_name,
               "description": str(parameters.get("description") or call.tool_name)[:200],
               "status": status, "result_summary": f"{call.tool_name}: {status}",
               "evidence_ref": evidence_ref}
        # 操作键不包含描述，避免同一命令仅改描述就误判为不同故障来源。
        operation = [call.tool_name, parameters.get("path"), parameters.get("action"), parameters.get("command"),
                     parameters.get("file_path"), parameters.get("model_call_id"), parameters.get("summary_id"), parameters.get("section")]
        row["operation_key"] = hashlib.sha256(json.dumps(operation, ensure_ascii=False).encode()).hexdigest()
        if call.tool_name in {"write", "read"}:
            after = self.file_state(parameters.get("path"))
            row.update(after)
            row["hash_algorithm"] = "sha256"
            if call.tool_name == "write":
                row.update(operation="overwrite" if parameters.get("overwrite") else "create",
                           before_hash=before.get("hash"), after_hash=after.get("hash") if status == "succeeded" else None,
                           changed=before.get("hash") != after.get("hash") if status == "succeeded" else False,
                           bytes_written=output.get("bytes_written"))
                row.pop("hash", None)
                row["result_summary"] = f"write: {status}; changed={row['changed']}"
            else:
                row["hash"] = output.get("sha256", before.get("hash"))
                row["truncated"] = output.get("truncated")
        elif call.tool_name == "exec":
            row.update(action=parameters.get("action"), command=str(parameters.get("command") or "")[:500],
                       exit_code=output.get("exit_code"), timed_out=output.get("timed_out"),
                       process_id=output.get("process_id") or parameters.get("process_id"), running=output.get("running"))
            if parameters.get("action") == "run":
                row["code_hashes"] = code_hashes
            row["result_summary"] = f"exec {row['action']}: {status}; exit_code={row['exit_code']}"
        if failed:
            row["error_excerpt"] = str(result.error or output.get("stderr") or output.get("stdout") or "tool_execution_failed")[:4000]
        # 原始大文本只保留 Trace，查询摘要不复制查询结果或代码全文。
        row = sanitize(row)
        records.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.safe_path("evidence/tool-summaries.tmp")
        temporary.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
        temporary.replace(self.path)
        return row

    @staticmethod
    def offset(cursor: int | None) -> int:
        # 校验分页位置，拒绝负数、布尔值及任意字符串游标。
        if cursor is None:
            return 0
        if type(cursor) is not int or cursor < 0:
            raise ValueError("invalid_cursor")
        return cursor

    def page(self, records: list[dict], cursor: int | None) -> dict:
        # 对摘要使用固定页长，限制历史查询上下文体积。
        offset = self.offset(cursor)
        end = offset + PAGE_SIZE
        return {"items": records[offset:end], "total": len(records),
                "next_cursor": end if end < len(records) else None}

    def file_history(self, file_path: str, cursor: int | None = None) -> dict:
        # 返回成功 write 的修改记录，并核对当前文件是否仍为最后记录版本。
        state = self.file_state(file_path)
        if not state:
            self.safe_path(file_path)
            raise ValueError("invalid_file_path")
        records = [row for row in self.load() if row.get("file_path") == state["file_path"]
                   and row["tool_name"] == "write" and row["status"] == "succeeded"]
        return {**self.page(list(reversed(records)), cursor), "file_path": state["file_path"],
                "current_hash": state["hash"], "matches_last_record": state["hash"] == records[-1]["after_hash"] if records else None}

    def model_call(self, model_call_id: str, cursor: int | None = None) -> dict:
        # 查询一批模型发起的工具摘要，保留实际执行顺序。
        records = [row for row in self.load() if row["parent_model_call_id"] == model_call_id]
        return {**self.page(records, cursor), "model_call_id": model_call_id}

    def detail(self, summary_id: str, section: str = "result", cursor: int | None = None) -> dict:
        # 从当前任务 Trace 取回历史证据，绝不重新执行工具。
        if section not in {"call", "result", "all"}:
            raise ValueError("invalid_section")
        row = next((item for item in self.load() if item["summary_id"] == summary_id), None)
        if row is None:
            raise ValueError("summary_not_found")
        value = {}
        for part in ("call", "result") if section == "all" else (section,):
            reference = row["evidence_ref"].get(part)
            if not reference:
                raise ValueError("tool_evidence_unavailable")
            path = self.safe_path(reference)
            traces = self.safe_path("traces")
            if traces not in path.parents:
                raise ValueError("evidence_outside_traces")
            value[part] = json.loads(path.read_text(encoding="utf-8"))["payload"]
        content = json.dumps(sanitize(value), ensure_ascii=False)
        offset = self.offset(cursor)
        end = offset + DETAIL_CHARS
        return {"summary_id": summary_id, "section": section, "content": content[offset:end],
                "next_cursor": end if end < len(content) else None, "total_chars": len(content)}

    def project(self, history: list[dict], run_id: int, history_key: str, code_hashes: dict) -> dict:
        # 将当前循环的账本聚合为每文件有效状态，旧检查点缺证据时保持原交互。
        records = [row for row in self.load() if row["step_run_id"] == run_id and row["history_key"] == history_key]
        lookup = {(row["parent_model_call_id"], row["tool_call_id"]): row for row in records}
        recent_id = history[-1].get("model_request_id") if history else None
        recent = []
        requested = []
        for entry in history:
            key = (entry.get("model_request_id"), entry.get("action", {}).get("call_id"))
            row = lookup.get(key)
            if row is None or not all(row["evidence_ref"].get(part) for part in ("call", "result")):
                recent.append(entry)
            elif entry.get("model_request_id") == recent_id and row['tool_name'] in {
                    'read', 'run_unit_tests', 'get_file_change_history', 'get_model_call_summaries', 'get_tool_execution_detail'}:
                requested.append(entry['result'])
        files = {}
        for row in records:
            if row.get('file_path') and row['tool_name'] in {'read', 'write'}:
                state = files.setdefault(row['file_path'], {'file_path':row['file_path']})
                state[row['tool_name']] = row
                state['sequence'] = row['sequence']
        states = []
        for path, entries in sorted(files.items(), key=lambda item:item[1]['sequence']):
            # 使用实际当前文件版本判断读取与写入记录是否仍适用，不把截断读取当完整检查。
            current = self.file_state(path)['hash']
            state = {'file_path':path, 'current_hash':current}
            for kind in ('read', 'write'):
                row = entries.get(kind)
                if row:
                    recorded = row.get('hash' if kind == 'read' else 'after_hash')
                    state['latest_' + kind] = {key:row.get(key) for key in (
                        'summary_id', 'parent_model_call_id', 'tool_call_id', 'status')}
                    state['latest_' + kind].update(recorded_hash=recorded,
                        matches_current_files=current is not None and current == recorded and row['status'] == 'succeeded')
                    if kind == 'read':
                        state['latest_read']['complete'] = row['status'] == 'succeeded' and row.get('truncated') is False
            states.append(state)
        # 仅同操作的后续成功能替换失败，其他命令成功不清除旧故障证据。
        latest = {}
        for row in records:
            latest[row["operation_key"]] = row
        failures = [{"summary_id": row["summary_id"], "parent_model_call_id": row["parent_model_call_id"],
                     "error_excerpt": row.get("error_excerpt"), "evidence_ref": row["evidence_ref"]}
                    for row in latest.values() if row["status"] in {"failed", "blocked"}]
        # 执行成功与验证当前版本分开表达，不把旧版本结果套到新文件。
        executions = [{"summary_id": row["summary_id"], "command": row.get("command"),
                       "status": row["status"], "matches_current_files": row["code_hashes"] == code_hashes}
                      for row in latest.values() if "code_hashes" in row]
        return {"tool_history": recent, "recent_model_call_id": recent_id, "tool_summaries": states[-PAGE_SIZE:],
                "earlier_summary_count": max(0, len(states) - PAGE_SIZE), 'current_requested_data':requested,
                "tool_failures": failures, "latest_execution_versions": executions}

    def recover_result(self, run_id: int, parent_id: str | None, call_id: str) -> dict | None:
        # 恢复摘要已保存但检查点未提交结果的窗口，不重复执行已完成的工具。
        row = next((item for item in self.load() if item["step_run_id"] == run_id
                    and item["parent_model_call_id"] == parent_id and item["tool_call_id"] == call_id), None)
        if row is None:
            return None
        reference = row["evidence_ref"].get("result")
        if not reference:
            raise ValueError("completed_tool_evidence_unavailable")
        path = self.safe_path(reference)
        if self.safe_path("traces") not in path.parents:
            raise ValueError("evidence_outside_traces")
        return json.loads(path.read_text(encoding="utf-8"))["payload"]["result"]
