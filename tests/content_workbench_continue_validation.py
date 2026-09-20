"""从真实 materials 局部提交证据续跑剩余切片；需用户授权，最多新增六十次 HTTP。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys


def main():
    """先零模型导入并验证现有提交，再通过正式 Worker 运行剩余阶段。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="materials 局部样本证据根目录")
    parser.add_argument("--output", type=Path, required=True, help="新的续跑证据根目录")
    parser.add_argument("--run", action="store_true", help="运行已准备的续跑任务；默认只复验和准备")
    args = parser.parse_args()
    source, root = args.source.resolve(), args.output.resolve()
    workspace = root / "workspace/1"
    if not args.run:
        root.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source / "workspace/1", workspace)
        # SQLite 官方备份接口只读复制源任务，保留原样本及其完整 Trace。
        with sqlite3.connect(f"file:{source / 'test.db'}?mode=ro", uri=True) as src:
            with sqlite3.connect(root / "test.db") as dst:
                src.backup(dst)
    os.environ["SIMULATOR_DATABASE_URL"] = f"sqlite+pysqlite:///{root}/test.db"
    os.environ["SIMULATOR_WORKSPACE_ROOT"] = str(root / "workspace")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import httpx
    from sqlalchemy import select
    from backend.app.database import SessionLocal
    from backend.app.models import Message, Step, StepRun, StepStatus, Task, TaskStatus, TraceRecord
    from backend.app.runtime import model, slice_workflow as sw, worker
    from backend.app.runtime.contracts import ToolCall
    from backend.app.runtime.tools import ToolRuntime
    from backend.app.runtime.tracing import sanitize
    from backend.app.runtime.unit_workflow import file_hashes, test_passed

    # 延续该基准已确认的全 DeepSeek、原生多模块和 localStorage 范围，不改正式服务配置。
    model.KIMI_STEPS.clear()
    worker.FIXED_PRODUCT_CONSTRAINTS = [
        '原生 HTML、CSS、JavaScript 多模块软件，模块职责和接口由架构及 Dev Design 明确',
        '使用 localStorage 保存单用户业务数据，不引入产品依赖、数据库或构建工具',
        '使用 Node 内置测试框架，测试入口 product.test.js',
        'Python Playwright 验证真实浏览器，本地静态 HTTP 启动与健康检查',
        '本地 HTTP 仅用于预览和验证，来源链接仅保存和打开，不抓取网页',
    ]
    with SessionLocal() as db:
        task = db.scalar(select(Task))
        run = db.scalar(select(StepRun).where(StepRun.task_id == task.id, StepRun.step == Step.develop)
                        .order_by(StepRun.id.desc()))
        if not args.run:
            summary = json.loads((source / "summary.json").read_text())
            if not summary["submitted"] or not summary["independent_test_passed"]:
                raise RuntimeError("source_materials_not_verified")
            old_workspace = Path(task.workspace_path)
            task.workspace_path = str(workspace)
            # 恢复路径指向新隔离目录，保留 Step 的调用计数和工具动作索引。
            for item in db.scalars(select(StepRun).where(StepRun.task_id == task.id)):
                if item.checkpoint_path:
                    item.checkpoint_path = str(workspace / Path(item.checkpoint_path).relative_to(old_workspace))
            progress = sw._progress(workspace, sw.load_delivery_plan(workspace))
            pending = next(e for e in progress["slices"] if e["card"]["id"] == "materials-library")
            completed = [e for e in progress["slices"] if e["status"] == "passed"]
            card = pending["card"]
            owned = card["implementation_files"] + card["test_files"]
            scope = list(dict.fromkeys([str(p.relative_to(workspace)) for p in worker.product_files(workspace)] + owned))
            tests = list(dict.fromkeys([p for e in completed for p in e["card"]["test_files"]] + card["test_files"]))
            scoped = sw.SliceTools(workspace, owned, scope, submission_files=owned,
                                   self_test_files=scope, test_files=tests)
            state = next(s for s in summary["switch_states"] if s["phase"] == "submitted")
            if not scoped.restore_submission(state["submission"]):
                raise RuntimeError("source_materials_submission_stale")
            before = file_hashes(workspace, scope)
            result = worker.execute_tool(db, task, run, scoped, ToolCall(
                "continue-materials-revalidation", "run_unit_tests", {}),
                history_key="continuation:materials:import")
            independent = worker.execute_tool(db, task, run, ToolRuntime(workspace), ToolCall(
                "continue-materials-independent", "exec", {"action": "run", "command": scoped.self_test_command()}),
                history_key="continuation:materials:independent")
            after = file_hashes(workspace, scope)
            if (result.status != "succeeded" or not result.output["passed"]
                    or not test_passed(independent, before, after)
                    or set(sw.remaining_todo_files(workspace)).intersection(card["test_files"])):
                raise RuntimeError("materials_continuation_revalidation_failed")
            # 只有版本一致的原提交和本次独立测试都通过，才登记已交付卡，不编造模型完成。
            report = {"slice_id": card["id"], "attempt": pending["attempt"], "command": scoped.self_test_command(),
                      "expectations": card["acceptance"], "result": independent.__dict__, "passed": True,
                      "file_hashes_before": before, "file_hashes_after": after,
                      "imported_submission_source": str(source / "summary.json")}
            report_path = "evidence/slices/003-materials-continuation-revalidation.json"
            worker.write_json_atomic(workspace / report_path, report)
            pending.update(status="passed", test=report, report=report_path, file_hashes=after)
            sw._save_progress(workspace, progress)
            sw._write_index(workspace, progress)
            task.status, task.cur_step, task.failure_reason = TaskStatus.running, Step.develop, None
            run.status, run.error, run.finished_at = StepStatus.running, None, None
            db.commit()
            manifest = {"source": str(source), "prior_local_http_attempts": summary["calls"],
                        "prior_local_tokens": summary["total_tokens"], "max_new_http": 60,
                        "develop_calls_at_start": run.model_call_count,
                        "first_new_trace_sequence": max(t.sequence for t in db.scalars(select(TraceRecord))),
                        "passed_slices": [e["card"]["id"] for e in progress["slices"] if e["status"] == "passed"],
                        "file_hashes_at_start": after}
            worker.write_json_atomic(root / "continuation-input.json", manifest)
            print(json.dumps({k: v for k, v in manifest.items() if k != "file_hashes_at_start"}, ensure_ascii=False, indent=2))
            return 0

        manifest = json.loads((root / "continuation-input.json").read_text())
        if manifest["source"] != str(source) or task.workspace_path != str(workspace):
            raise RuntimeError("continuation_source_mismatch")
        count_path = root / "new-call-count.json"
        calls = int(count_path.read_text()) if count_path.is_file() else 0
        original_stream = httpx.Client.stream

        def bounded_stream(client, method, url, **kwargs):
            """新增实际请求共用持久化上限；只记录 JSON 载荷，不记录凭据或认证头。"""
            nonlocal calls
            if str(url).endswith('/chat/completions'):
                if calls >= manifest["max_new_http"]:
                    raise RuntimeError("continuation_http_budget_exceeded")
                calls += 1
                worker.write_json_atomic(count_path, calls)
                worker.write_json_atomic(root / f"sent-requests/{calls:03d}.json", sanitize(kwargs.get("json", {})))
                print("NEW_MODEL_HTTP", calls, flush=True)
            return original_stream(client, method, url, **kwargs)

        httpx.Client.stream = bounded_stream
        for index in range(30):
            db.refresh(task)
            print("STATE", index, task.status.value, task.cur_step.value, flush=True)
            if task.status not in {TaskStatus.pending, TaskStatus.running}:
                break
            worker.process_task(db)
        db.refresh(task)
        new_usage = []
        for trace in db.scalars(select(TraceRecord).where(
                TraceRecord.task_id == task.id, TraceRecord.sequence > manifest["first_new_trace_sequence"],
                TraceRecord.type == "model_response").order_by(TraceRecord.sequence)):
            detail = json.loads((workspace / trace.detail_path).read_text())
            usage = detail.get("payload", {}).get("raw_response", {}).get("usage")
            new_usage.append({"step": trace.step, "usage": usage, "trace": trace.detail_path})
        progress = json.loads((workspace / "evidence/slice-progress.json").read_text())
        latest = db.scalar(select(Message).where(Message.task_id == task.id).order_by(Message.id.desc()))
        summary = {"status": task.status.value, "step": task.cur_step.value, "failure_reason": task.failure_reason,
                   "new_http_attempts": calls, "max_new_http": manifest["max_new_http"], "new_usage": new_usage,
                   "new_total_tokens": sum((u["usage"] or {}).get("total_tokens", 0) for u in new_usage),
                   "result_url": task.result_url, "process_id": task.process_id,
                   "latest_message": latest.content if latest else "", "repair_round": task.repair_round,
                   "slices": [{"id": e["card"]["id"], "status": e["status"], "report": e.get("report")}
                              for e in progress["slices"]],
                   "file_hashes_after": file_hashes(workspace, [str(p.relative_to(workspace)) for p in worker.product_files(workspace)])}
        worker.write_json_atomic(root / "summary.json", summary)
        print(json.dumps({k: v for k, v in summary.items() if k not in {"new_usage", "file_hashes_after", "latest_message"}},
                         ensure_ascii=False, indent=2), flush=True)
        return 0 if task.status == TaskStatus.waiting_acceptance else 1


if __name__ == "__main__":
    raise SystemExit(main())
