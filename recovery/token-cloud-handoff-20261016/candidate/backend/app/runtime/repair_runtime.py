"""显式返修尝试的版本提交、固定验证与实际请求预算。"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import httpx

from ..models import Step, StepStatus, TaskStatus
from .contracts import ToolCall, ToolResult


RUNTIME_PATH = "evidence/repair-runtime-v1.json"
STEPS = {"executing": Step.develop, "submitted": Step.test, "testing": Step.test,
         "starting": Step.start_product, "verifying": Step.verify_product,
         "reviewing": Step.verify_product, "awaiting_acceptance": Step.verify_product}


class BudgetExceeded(RuntimeError):
    """区分请求额度耗尽与模型网络故障。"""

    def __init__(self):
        # 固定错误码供 Worker 和前端使用，不暴露凭据。
        super().__init__("budget_exhausted")


def load(root: Path) -> dict | None:
    """读取显式模式状态，旧工作区不创建记录。"""
    path = root / RUNTIME_PATH
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("workflow") != "repair-v1" or not isinstance(state.get("revision"), int):
        raise RuntimeError("repair_runtime_invalid")
    return state


def save(root: Path, state: dict) -> None:
    """先原子保存递增状态，再由调用方更新数据库投影。"""
    from .worker import write_json_atomic
    state["revision"] += 1
    write_json_atomic(root / RUNTIME_PATH, state)


def manifest(root: Path) -> dict:
    """绑定全产品、有效文档和授权文件，新增或删除也改变版本。"""
    paths = list((root / "product").rglob("*"))
    paths += [root / "docs" / name for name in (
        "product.md", "architecture.md", "dev-design.md", "acceptance-standard.json")]
    state = load(root)
    if state:
        paths.append(root / state["authorization_ref"])
    result = {}
    for path in sorted(set(paths)):
        if path.is_symlink() or (path.exists() and root.resolve() not in path.resolve().parents):
            raise RuntimeError("repair_manifest_unsafe_path")
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def isolation_ready() -> bool:
    """只有当前镜像、控制指纹及必需探针证据一致才开放隔离入口。"""
    from .sandbox_gate import ready
    return ready()


def initialize(task, event) -> dict:
    """核对明确入口和程序授权，仅在隔离门禁通过后初始化一次。"""
    from .worker import workspace_for, missing_product_files
    root = workspace_for(task)
    data = event.data or {}
    existing = load(root)
    if existing and existing["event_id"] == event.id:
        return existing
    if data.get("workflow") != "repair-v1":
        raise ValueError("repair_workflow_required")
    if type(data.get("expected_task_version")) is not int or data["expected_task_version"] != task.version:
        raise ValueError("repair_task_version_mismatch")
    if task.status not in {TaskStatus.failed, TaskStatus.succeeded, TaskStatus.waiting_acceptance}:
        raise ValueError("repair_task_not_available")
    if not isinstance(data.get("feedback"), str) or not data["feedback"].strip():
        raise ValueError("repair_feedback_required")
    if missing_product_files(root) or not (root / "docs/product.md").is_file():
        raise ValueError("repair_artifacts_missing")
    # 当前隔离证据不适用时不读取授权、不创建状态、不发送数据。
    if not isolation_ready():
        raise ValueError("repair_execution_isolation_pending")
    ref = data.get("budget_authorization_ref")
    if (not isinstance(ref, str) or not ref.startswith("evidence/repair-authorization-")
            or not ref.endswith(".json") or Path(ref).name != ref.split("/", 1)[1]):
        raise ValueError("repair_authorization_ref_invalid")
    path = root / ref
    if path.is_symlink() or not path.is_file():
        raise ValueError("repair_authorization_missing")
    authorization = json.loads(path.read_text())
    numbers = [authorization.get(key) for key in ("historical_attempts", "total_limit", "review_reserve")]
    if (any(type(value) is not int or value < 0 for value in numbers)
            or numbers[1] <= numbers[0] or numbers[2] > numbers[1] - numbers[0]
            or authorization.get("provider") != "deepseek" or not authorization.get("data_scope")
            or authorization.get("task_id") != task.id):
        raise ValueError("repair_authorization_invalid")
    if existing and numbers[0] != existing["budget"]["attempts_used"]:
        raise ValueError("repair_historical_attempts_mismatch")
    # 每次尝试另存旧状态，防止新尝试覆盖历史预算和失败现场。
    from .worker import write_json_atomic
    if existing:
        old = root / f'evidence/repair-attempt-{existing["event_id"]}-runtime.json'
        if not old.exists():
            write_json_atomic(old, existing)
    state = {"workflow": "repair-v1", "task_id": task.id, "event_id": event.id,
             "validation_policy": "tests_and_browser",
             "revision": 0, "state": "executing", "authorization_ref": ref,
             "authorization_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
             "feedback": data["feedback"], "submission_id": None, "submission_number": 0,
             "intent": None, "stop_reason": None,
             "budget": {"historical_attempts": numbers[0], "attempts_used": numbers[0],
                        "total_limit": numbers[1], "review_reserve": 0,
                        "provider": "deepseek", "requests": []}}
    save(root, state)
    return state


def reserve_request(root: Path, provider: str, request_id: str) -> int | None:
    """在实际 HTTP 发送前保守登记，重试和审查均受同一累计上限约束。"""
    state = load(root)
    if not state:
        return None
    budget = state["budget"]
    authorization = root / state["authorization_ref"]
    if (not authorization.is_file() or authorization.is_symlink()
            or hashlib.sha256(authorization.read_bytes()).hexdigest() != state["authorization_hash"]):
        raise RuntimeError("repair_authorization_changed")
    allowed = {'executing'} if state.get('validation_policy') == 'tests_and_browser' else {'executing', 'reviewing'}
    if state["state"] not in allowed:
        raise RuntimeError("repair_model_call_outside_phase")
    if provider != budget["provider"]:
        raise RuntimeError("repair_provider_mismatch")
    limit = budget["total_limit"] - (0 if state["state"] == "reviewing" else budget["review_reserve"])
    if budget["attempts_used"] >= limit:
        raise BudgetExceeded()
    budget["attempts_used"] += 1
    attempt = budget["attempts_used"]
    budget["requests"].append({"attempt": attempt, "request_id": request_id,
                               "phase": state["state"], "status": "send_unknown", "usage": None})
    save(root, state)
    return attempt


def finish_request(root: Path, attempt: int | None, status: str, usage: dict | None) -> None:
    """追加发送结果与已知真实用量，绝不回减已预约次数。"""
    if attempt is None:
        return
    state = load(root)
    entry = next(item for item in state["budget"]["requests"] if item["attempt"] == attempt)
    entry.update(status=status, usage=usage)
    save(root, state)


def persist_submission(task, scoped) -> None:
    """仅在模型显式提交且自测有效时冻结完整版本，保留每个提交。"""
    from .worker import workspace_for, write_json_atomic, missing_product_files
    root = workspace_for(task)
    state = load(root)
    if not state or state["state"] != "executing":
        raise RuntimeError("repair_submission_outside_phase")
    if scoped.submitted_hashes is None or not scoped.restore_self_test(scoped.self_test):
        raise RuntimeError("repair_submission_self_test_required")
    if scoped.submitted_hashes != scoped.submission_versions() or missing_product_files(root):
        raise RuntimeError("repair_submission_stale")
    versions = manifest(root)
    state["submission_number"] += 1
    submission_id = f'{state["event_id"]}-{state["submission_number"]}'
    submission = {"id": submission_id, "manifest": versions, "self_test": scoped.self_test,
                  "submitted_files": list(scoped.submitted_hashes), "created_at": datetime.utcnow().isoformat()}
    if state.get('session'):
        # 保留相对原批准任务测试的差异，独立审查不能只相信修改后绿灯。
        import difflib
        original = state['session'].get('original_tests', {})
        current = {p: (root / 'product' / p).read_text() for p in original}
        for p in (root / 'product').rglob('*'):
            if p.is_file() and (p.name.endswith(('.test.js', '.test.cjs', '.test.mjs')) or p.name == 'verify_product.py'):
                current[str(p.relative_to(root / 'product'))] = p.read_text()
        submission['test_diff'] = {p: ''.join(difflib.unified_diff(original.get(p, '').splitlines(True),
                    body.splitlines(True), fromfile=p, tofile=p)) for p, body in current.items()
                    if original.get(p, '') != body}
    ref = f"evidence/repair-attempt-{submission_id}-submission.json"
    if (root / ref).exists():
        existing = json.loads((root / ref).read_text())
        if any(existing.get(key) != submission[key] for key in ("id", "manifest", "self_test", "submitted_files")):
            raise RuntimeError("repair_submission_conflict")
    else:
        write_json_atomic(root / ref, submission)
    state.update(state="submitted", submission_id=submission_id, submission_ref=ref,
                 validation_ref=f"evidence/repair-attempt-{submission_id}-validation.json", intent=None)
    if not (root / state["validation_ref"]).exists():
        write_json_atomic(root / state["validation_ref"], {"submission_id": submission_id, "stages": {}})
    save(root, state)


def current_submission(root: Path, state: dict) -> dict:
    """恢复冻结提交并核对需求、授权及全产品文件版本。"""
    ref = state.get("submission_ref")
    if not ref or not (root / ref).is_file():
        raise RuntimeError("repair_submission_missing")
    submission = json.loads((root / ref).read_text())
    if submission["id"] != state["submission_id"] or submission["manifest"] != manifest(root):
        raise RuntimeError("repair_submission_version_changed")
    return submission


def stop(db, task, run, reason: str) -> None:
    """明确持久停止原因并保存成果，不自动续跑或核销目标。"""
    from .worker import workspace_for, safe_record_trace
    root = workspace_for(task)
    state = load(root)
    state.update(state="stopped", stop_reason=reason)
    save(root, state)
    task.status = TaskStatus.failed
    task.failure_reason = reason
    task.version += 1
    run.status = StepStatus.failed
    run.error = reason
    run.finished_at = datetime.utcnow()
    safe_record_trace(db, task, run, "state_transition", "failed", "返修停止", reason,
                      {"submission_id": state["submission_id"], "budget": state["budget"]})
    db.commit()


def pipeline(db, task, run, tools) -> None:
    """按冻结版本执行一个固定阶段，完成证据先于数据库状态投影。"""
    from . import worker as w
    from .repair_objectives import pending, verify
    from .unit_workflow import test_passed
    root = w.workspace_for(task)
    state = load(root)
    try:
        # 阶段契约绑定尝试；旧断点不自动跳过此前约定的审查。
        reviewed = state.get('validation_policy') != 'tests_and_browser'
        current_submission(root, state)
        if not (root / state["validation_ref"]).is_file():
            raise RuntimeError("repair_validation_missing")
        validation = json.loads((root / state["validation_ref"]).read_text())
        if validation["submission_id"] != state["submission_id"]:
            raise RuntimeError("repair_validation_submission_mismatch")
        phase = "testing" if state["state"] == "submitted" else state["state"]
        if phase not in {"testing", "starting", "verifying", "reviewing", "awaiting_acceptance"}:
            raise RuntimeError("repair_pipeline_phase_invalid")
        if phase == 'reviewing' and not reviewed:
            raise RuntimeError('repair_pipeline_phase_invalid')
        # 已保存阶段结果可恢复投影；未完成 intent 不能默认为可安全重放。
        stages = validation["stages"]
        if state["intent"] and phase not in stages:
            raise RuntimeError("unknown_side_effect")
        if phase not in stages and phase != "awaiting_acceptance":
            state.update(state=phase, intent=phase)
            save(root, state)
            if phase == "testing":
                result = w.execute_tool(db, task, run, tools, ToolCall(
                    "repair-test", "exec", {"action": "run", "command": "node --test"}))
                if (result.status != "succeeded" or result.output.get("timed_out")
                        or result.output.get("exit_code") in {126, 127, 9009}):
                    raise RuntimeError("repair_test_environment_error")
                passed = test_passed(result, {}, {})
                output = {"result": result.__dict__, "passed": passed}
            elif phase == "starting":
                # 服务事实先保存到版本化阶段结果，不提前提交 Task 下一步。
                try:
                    service = w.start_product_service(db, task, run, tools)
                except Exception as exc:
                    raise RuntimeError("repair_service_environment_error:" + str(exc)) from exc
                passed = True
                output = {"passed": True, **service}
            elif phase == "verifying":
                if not stages.get("testing", {}).get("passed") or not stages.get("starting", {}).get("passed"):
                    raise RuntimeError("repair_previous_stage_missing")
                task.result_url = stages["starting"]["url"]
                browser, _ = w.run_product_browser_validation(db, task, run, tools)
                if browser.status != "succeeded" and browser.tool_name != "verify_script_preflight":
                    raise RuntimeError("repair_browser_environment_error")
                passed = w.browser_validation_passed(browser)
                output = {"result": browser.__dict__, "passed": passed}
            else:
                browser = ToolResult(**stages["verifying"]["result"])
                from .acceptance_standard import load_standard, review_coverage
                standard = load_standard(root)
                coverage = {"complete": True}
                if standard:
                    from .slice_workflow import _progress, load_delivery_plan
                    progress = _progress(root, load_delivery_plan(root))
                    completed = [item for item in progress["slices"] if item.get("status") == "passed"]
                    coverage = review_coverage(db, task, run, tools, standard, completed)
                # 独立只读目标复核保留原始目标，审查预留仅在该阶段使用。
                passed = coverage["complete"] and verify(db, task, run, tools, browser) and not pending(task)
                output = {"passed": passed, "coverage": coverage,
                          "objectives_unresolved": [item["id"] for item in pending(task)]}
            current_submission(root, state)
            stages[phase] = output
            w.write_json_atomic(root / state["validation_ref"], validation)
        elif phase != "awaiting_acceptance":
            passed = stages[phase]["passed"]
        else:
            passed = True
        # Provider 守卫可能更新预算，刷新状态后再保存，避免覆盖新增计数。
        state = load(root)
        state["intent"] = None
        w.safe_record_trace(db, task, run, "repair_validation", "succeeded" if passed else "failed",
                            "固定返修验证", phase,
                            {"phase": phase, "submission_id": state["submission_id"],
                             "evidence": state["validation_ref"]})
        if phase == "starting":
            service = stages[phase]
            task.result_url = service["url"]
            task.port = service["port"]
            task.process_id = service["process_id"]
            task.process_command = service["command"]
        if not passed:
            if state.get('session'):
                # 独立验证失败后的恢复不能复用该次提交，但保留完整协议历史。
                checkpoint = root / f'evidence/repair-session-{state["session"]["id"]}-checkpoint.json'
                state['session']['validation_boundary'] = len(json.loads(checkpoint.read_text())) if checkpoint.is_file() else 0
            state.update(state="executing", last_failure={"phase": phase, "evidence": state["validation_ref"]})
            save(root, state)
            w.fail_or_repair(db, task, run, "repair_" + phase + "_failed")
            if task.status == TaskStatus.failed:
                stop(db, task, run, "repair_rounds_exhausted")
            return
        next_phase = {"testing": "starting", "starting": "verifying", "verifying": "reviewing" if reviewed else "awaiting_acceptance",
                      "reviewing": "awaiting_acceptance", "awaiting_acceptance": "awaiting_acceptance"}[phase]
        state.update(state=next_phase)
        save(root, state)
        if next_phase == "awaiting_acceptance":
            current_submission(root, state)
            required = ('testing', 'starting', 'verifying', 'reviewing') if reviewed else ('testing', 'starting', 'verifying')
            if any(not stages.get(name, {}).get("passed") for name in required):
                raise RuntimeError("repair_validation_incomplete")
            task.result_url = stages["starting"]["url"]
            with httpx.Client(trust_env=False, timeout=2) as client:
                if client.get(task.result_url).status_code != 200:
                    raise RuntimeError("repair_product_unavailable")
            task.status = TaskStatus.waiting_acceptance
            task.cur_step = Step.verify_product
            task.version += 1
            run.status = StepStatus.succeeded
            run.finished_at = datetime.utcnow()
            w.safe_record_trace(db, task, run, "state_transition", "waiting", "等待人工验收",
                                "固定验证完成", {"submission_id": state["submission_id"], "url": task.result_url})
            w.add_message(db, task, "assistant", f"提交 {state['submission_id']} 验证通过，请访问 {task.result_url} 验收。")
            db.commit()
        else:
            w.finish_step(db, task, run, STEPS[next_phase])
    except BudgetExceeded:
        stop(db, task, run, "budget_exhausted")
    except Exception as exc:
        stop(db, task, run, str(exc))
