"""用户授权后手动运行单个 materials 局部 DeepSeek 样本，最多十二次 HTTP。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    """复制真实失败夹具并使用正式切换入口，保留请求、版本及独立回归证据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="已有真实任务的 workspace/1")
    parser.add_argument("--output", type=Path, required=True, help="全新的隔离证据目录")
    parser.add_argument("--resume-transport", action="store_true", help="仅恢复无模型响应、无修改的连接失败，保留原总预算")
    args = parser.parse_args()
    source, root = args.source.resolve(), args.output.resolve()
    workspace = root / "workspace/1"
    if args.resume_transport:
        previous = json.loads((root / "summary.json").read_text())
        if (previous.get("error") != "RuntimeError:model_transport_failed:ConnectError"
                or previous.get("usage") or previous.get("changed_files")):
            raise RuntimeError("only_initial_transport_failure_can_resume")
        shutil.copy2(root / "summary.json", root / "summary-transport-failure.json")
    else:
        root.mkdir(parents=True, exist_ok=False)
        for directory in ("docs", "product"):
            shutil.copytree(source / directory, workspace / directory)
        (workspace / "evidence").mkdir()
        shutil.copy2(source / "evidence/slice-progress.json", workspace / "evidence/slice-progress.json")
    # 只复制需求、代码和通过证据，不继承旧模型检查点、数据库或工具摘要。
    os.environ["SIMULATOR_DATABASE_URL"] = f"sqlite+pysqlite:///{root}/test.db"
    os.environ["SIMULATOR_WORKSPACE_ROOT"] = str(root / "workspace")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import httpx
    from sqlalchemy import select
    from backend.app.database import Base, SessionLocal, engine
    from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus, TraceRecord
    from backend.app.runtime import slice_workflow as sw, worker
    from backend.app.runtime.contracts import ToolCall
    from backend.app.runtime.tools import ToolRuntime
    from backend.app.runtime.tracing import sanitize
    from backend.app.runtime.unit_workflow import file_hashes, test_passed

    calls = int((root / "call-count.json").read_text()) if args.resume_transport else 0
    original_stream = httpx.Client.stream

    def bounded_stream(client, method, url, **kwargs):
        """在实际 HTTP 前计数，包含所有传输重试，不输出或保存认证头。"""
        nonlocal calls
        if str(url).endswith("/chat/completions"):
            if calls >= 12:
                raise RuntimeError("materials_local_http_budget_exceeded")
            calls += 1
            (root / "call-count.json").write_text(json.dumps(calls))
            sent = root / "sent-requests"
            sent.mkdir(exist_ok=True)
            (sent / f"{calls:03d}.json").write_text(json.dumps(
                sanitize(kwargs.get("json", {})), ensure_ascii=False, indent=2))
            print("MODEL_HTTP", calls, flush=True)
        return original_stream(client, method, url, **kwargs)

    httpx.Client.stream = bounded_stream
    Base.metadata.create_all(engine)
    progress = json.loads((workspace / "evidence/slice-progress.json").read_text())
    pending = next(entry for entry in progress["slices"] if entry["card"]["id"] == "materials-library")
    card = pending["card"]
    completed = [entry for entry in progress["slices"] if entry.get("status") == "passed"]
    current_tests = list(dict.fromkeys([path for entry in completed for path in entry["card"]["test_files"]]
                                     + card["test_files"]))
    owned = card["implementation_files"] + card["test_files"]
    all_scope = list(dict.fromkeys([str(path.relative_to(workspace)) for path in worker.product_files(workspace)] + owned))
    before = file_hashes(workspace, all_scope)
    (root / "input-manifest.json").write_text(json.dumps({
        "source": str(source), "card": card, "file_hashes": before,
        "http_limit": 12, "restricted_call_limit": sw.MAX_RESTRICTED_IMPLEMENTATION_CALLS,
        "implementation_sha256": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (
            "backend/app/runtime/slice_workflow.py", "backend/app/runtime/worker.py", "prompts/slice-implementer/v1.md")},
    }, ensure_ascii=False, indent=2))
    with SessionLocal() as db:
        if args.resume_transport:
            task = db.scalar(select(Task))
            run = db.scalar(select(StepRun).where(StepRun.task_id == task.id))
            run.status, run.error = StepStatus.running, None
            db.commit()
        else:
            task = Task(task_name="materials control switch local DeepSeek validation", cur_step=Step.develop,
                        status=TaskStatus.running, workspace_path=str(workspace))
            db.add(task); db.flush()
            run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                          checkpoint_path=str(workspace / "evidence/control-switch-checkpoint.json"))
            db.add(run); db.commit()
        scoped = sw.SliceTools(workspace, owned, all_scope + [pending["card_path"], "docs/product.md", "docs/architecture.md"],
                               submission_files=owned, self_test_files=all_scope, test_files=current_tests)
        outcome, error = "", None
        try:
            outcome = sw.run_slice_developer(db, task, run, card, completed, scoped,
                                             "slice:materials-library:control-switch-local")
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
        test_before = file_hashes(workspace, all_scope)
        result = worker.execute_tool(db, task, run, ToolRuntime(workspace), ToolCall(
            "independent-test", "exec", {"action": "run", "command": scoped.self_test_command()}),
            history_key="slice_test:materials-library:control-switch-local")
        after = file_hashes(workspace, all_scope)
        passed = test_passed(result, test_before, after)
        todo = sorted(set(sw.remaining_todo_files(workspace)).intersection(card["test_files"]))
        readonly_changed = [path for path in all_scope if path not in owned and before[path] != after[path]]
        usage = []
        for trace in db.scalars(select(TraceRecord).where(
                TraceRecord.task_id == task.id, TraceRecord.type == "model_response")).all():
            raw = json.loads((workspace / trace.detail_path).read_text()).get("payload", {}).get("raw_response", {})
            if isinstance(raw, dict) and isinstance(raw.get("usage"), dict):
                usage.append(raw["usage"])
        states = [json.loads(path.read_text()) for path in (workspace / "evidence/slices").glob("developer-*.json")]
        summary = {"calls": calls, "logical_calls": run.model_call_count, "outcome": outcome, "error": error,
                   "submitted": scoped.submitted_hashes is not None, "replan_reason": scoped.replan_reason,
                   "independent_test_passed": passed and not todo, "independent_test": result.__dict__,
                   "remaining_current_todo": todo, "readonly_changed": readonly_changed,
                   "switch_states": states, "usage": usage,
                   "total_tokens": sum(item.get("total_tokens", 0) for item in usage),
                   "changed_files": [path for path in all_scope if before[path] != after[path]],
                   "file_hashes_before": before, "file_hashes_after": after,
                   "full_product_ui_verified": False}
        success = summary["submitted"] and summary["independent_test_passed"] and not readonly_changed and error is None
        run.status = StepStatus.succeeded if success else StepStatus.failed
        run.error = error
        db.commit()
        (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps({key: summary[key] for key in (
            "calls", "logical_calls", "outcome", "error", "submitted", "independent_test_passed", "total_tokens",
            "remaining_current_todo", "readonly_changed", "changed_files")}, ensure_ascii=False, indent=2), flush=True)
        return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
