"""按真实请求和版本证据统计执行阶段，成本分析不改实验状态。"""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path

from .prompt_registry import sha256_text

PHASES = ("before_modify", "before_self_test", "after_green", "other")


def effective_write(entry: dict) -> bool:
    """只有成功改变产品哈希才算内容修改，计划与相同正文不算。"""
    action, result = entry.get("action", {}), entry.get("result", {})
    path = action.get("parameters", {}).get("path", "")
    before = entry.get("repair_versions_before", entry.get("unit_versions_before", {}))
    after = entry.get("repair_versions_after", entry.get("unit_versions_after", {}))
    return (action.get("tool_name") in {"write", "replace"} and result.get("status") == "succeeded"
            and path.startswith("product/") and path in after and after.get(path) != before.get(path))


def valid_test(entry: dict) -> dict | None:
    """核对真实通过和当前版本，外层工具成功不能代替测试绿灯。"""
    result = entry.get("result", {})
    output = result.get("output", {})
    tool = entry.get("action", {}).get("tool_name")
    if tool == "verify_and_submit":
        output = output.get("self_test", {})
    if (tool not in {"run_unit_tests", "verify_and_submit"} or result.get("status") != "succeeded"
            or output.get("passed") is not True):
        return None
    before, after = output.get("file_hashes_before"), output.get("file_hashes_after")
    current = entry.get("repair_versions_after", entry.get("unit_versions_after", after))
    if (not isinstance(after, dict) or not after or before != after or not isinstance(current, dict)
            or not current or any(after.get(path) != digest for path, digest in current.items())):
        return None
    return after


def valid_submission(entry: dict, green: dict | None) -> bool:
    """提交必须成功且绑定最近有效自测版本，缺依据不猜造提交边界。"""
    output = entry.get("result", {}).get("output", {})
    submitted = output.get("file_hashes")
    if entry.get('action', {}).get('tool_name') == 'verify_and_submit' and output.get('submitted') is not True:
        return False
    return (entry.get("action", {}).get("tool_name") in {"submit_unit_for_test", "verify_and_submit"}
            and entry.get("result", {}).get("status") == "succeeded" and green is not None
            and isinstance(submitted, dict) and bool(submitted)
            and all(green.get(path) == digest for path, digest in submitted.items()))


def classify(requests: list[dict], events: list[dict]) -> dict:
    """对每次HTTP逐项归属，重试保留，多个边界同请求归最早阶段。"""
    by_request = defaultdict(list)
    for event in events:
        by_request[event.get("model_request_id")].append(event)
    states, rows = {}, []
    last_response = {request['request_id']: index for index, request in enumerate(requests)
                     if request.get('status') == 'responded'}
    totals = {phase: {"http": 0, "known_tokens": 0, "unknown_usage": 0} for phase in PHASES}
    for index, request in enumerate(requests):
        request_id = request["request_id"]
        # 重试共用逻辑ID时，工具只属于最终完整响应，不能重复核销边界。
        actions = by_request.get(request_id, []) if last_response.get(request_id) == index else []
        scope = request.get("scope", "")
        execution = scope.startswith(("repair-session:", "slice:", "slice-repair:", "unit:"))
        state = states.setdefault(scope, {"modified": False, "green": None, "cycle": 1,
                                          "first_modify": None, "first_green": None, "submitted": False})
        if execution:
            if state["submitted"]:
                state.update(modified=False, green=None, cycle=state["cycle"]+1, first_modify=None,
                             first_green=None, submitted=False)
            phase = "after_green" if state["green"] is not None else (
                "before_self_test" if state["modified"] else "before_modify")
        else:
            phase = "other"
        boundaries, invalidated = [], False
        for entry in actions if execution else []:
            if effective_write(entry):
                if not state["modified"]:
                    state["first_modify"] = request["attempt"]
                    boundaries.append("first_effective_modify")
                if state["green"] is not None:
                    invalidated = True
                    boundaries.append("green_invalidated_by_write")
                state.update(modified=True, green=None)
            tested = valid_test(entry)
            if tested:
                if state["first_green"] is None:
                    state["first_green"] = request["attempt"]
                    boundaries.append("first_current_self_test_passed")
                else:
                    boundaries.append("current_self_test_passed")
                state["green"] = tested
            if valid_submission(entry, state["green"]):
                state["submitted"] = True
                boundaries.append("valid_explicit_submission")
        usage = request.get("usage")
        known = isinstance(usage, dict) and type(usage.get("total_tokens")) is int and usage["total_tokens"] >= 0
        total = usage["total_tokens"] if known else None
        bucket = totals[phase]
        bucket["http"] += 1
        bucket["known_tokens"] += total or 0
        bucket["unknown_usage"] += int(not known)
        rows.append({"attempt": request["attempt"], "request_id": request_id, "scope": scope,
                     "cycle": state["cycle"] if execution else None, "phase": phase,
                     "status": request.get("status"), "tokens": total,
                     "prompt_tokens": usage.get("prompt_tokens") if isinstance(usage, dict) else None,
                     "completion_tokens": usage.get("completion_tokens") if isinstance(usage, dict) else None,
                     "cache_hit_tokens": usage.get("prompt_cache_hit_tokens") if isinstance(usage, dict) else None,
                     "duration_seconds": request.get("duration_seconds"), "boundaries": boundaries,
                     "post_green_rework": invalidated,
                     "test_commands": [entry.get("result", {}).get("output", {}).get("command") for entry in actions
                                       if entry.get("action", {}).get("tool_name") == "run_unit_tests"],
                     "tools": [entry.get("action", {}).get("tool_name") for entry in actions],
                     "evidence": request.get("evidence")})
    known_total = sum(row["tokens"] or 0 for row in rows)
    assert known_total == sum(bucket["known_tokens"] for bucket in totals.values())
    assert len(rows) == sum(bucket["http"] for bucket in totals.values())
    return {"requests": rows, "phases": totals, "http": len(rows), "known_tokens": known_total,
            "unknown_usage": sum(bucket["unknown_usage"] for bucket in totals.values()),
            "final_scopes": states, "reconciled": True,
            "notes": ["Token不拆分；同轮多个边界归最早阶段。", "首次有效修改只证明哈希变化，不证明业务修改正确。",
                      "旧切片自测按单元范围统计，不冒充整平台全量通过。", "通过后重改标记重测，不默认视为浪费。"]}


def load_evidence(task_root: Path, summary: Path | None = None) -> tuple[list, list, dict]:
    """读取原预算或完整响应Trace及检查点，保留来源指纹和缺失边界。"""
    if not task_root.is_dir():
        raise ValueError("task_root_missing")
    fingerprints, traces, events, seen = {}, [], [], {}
    for path in sorted((task_root / "traces").rglob("*.json")):
        if path.is_symlink():
            raise ValueError("trace_symlink_rejected")
        body = path.read_bytes()
        fingerprints[str(path.relative_to(task_root))] = hashlib.sha256(body).hexdigest()
        trace = json.loads(body)
        trace["evidence"] = str(path.relative_to(task_root))
        traces.append(trace)
    traces.sort(key=lambda trace: trace["sequence"])
    for path in sorted((task_root / "evidence").glob("*checkpoint.json")):
        body = path.read_bytes()
        fingerprints[str(path.relative_to(task_root))] = hashlib.sha256(body).hexdigest()
        checkpoint = json.loads(body)
        if not isinstance(checkpoint, list):
            raise ValueError("checkpoint_invalid")
        for entry in checkpoint:
            if not entry.get("action"):
                continue
            identity = (entry.get("model_request_id"), entry["action"].get("call_id"))
            signature = sha256_text(json.dumps({key:entry.get(key) for key in ("action","result")}, sort_keys=True,ensure_ascii=False))
            if identity in seen:
                if seen[identity] != signature:
                    raise ValueError("checkpoint_action_conflict")
                continue
            seen[identity] = signature
            events.append(entry)
    responses = [trace for trace in traces if trace["type"] == "model_response"]
    requests_by_id = {trace["payload"]["request_id"]: trace for trace in traces if trace["type"] == "model_request"}
    runtime_path = task_root / "evidence/repair-runtime-v1.json"
    if runtime_path.is_file():
        runtime_body = runtime_path.read_bytes()
        fingerprints[str(runtime_path.relative_to(task_root))] = hashlib.sha256(runtime_body).hexdigest()
        requests = json.loads(runtime_body)["budget"]["requests"]
        requests = [dict(request) for request in requests]
        count_evidence = "persistent_http_budget"
    else:
        if summary is None or not summary.is_file():
            raise ValueError("legacy_http_counter_required")
        source = json.loads(summary.read_text())
        if type(source.get("calls")) is not int or source["calls"] != len(responses):
            raise ValueError("legacy_http_response_count_mismatch")
        requests = [{"attempt":index+1,"request_id":trace["payload"]["request_id"],
                     "status":"responded" if trace['status'] == 'succeeded' else 'protocol_failed',
                     "usage":trace["payload"].get("raw_response",{}).get("usage"),
                     "evidence":trace["evidence"]} for index,trace in enumerate(responses)]
        count_evidence = "legacy_counter_and_complete_responses"
        fingerprints["external_summary"] = hashlib.sha256(summary.read_bytes()).hexdigest()
    for request in requests:
        trace = requests_by_id.get(request["request_id"], {})
        request["scope"] = trace.get("metadata", {}).get("history_key", "unknown")
        request.setdefault("evidence", trace.get("evidence"))
        end = next((row for row in responses if row["payload"]["request_id"] == request["request_id"]), {})
        start_at, finish_at = trace.get("started_at"), end.get("finished_at")
        if start_at and finish_at:
            request["duration_seconds"] = max(0,(datetime.fromisoformat(finish_at)-datetime.fromisoformat(start_at)).total_seconds())
    return requests, events, {"count_evidence": count_evidence, "fingerprints": fingerprints}


def main() -> None:
    """只读分析已有任务现场，结果打印到stdout，缺失证据明确失败。"""
    parser = argparse.ArgumentParser(description="执行阶段Token分析")
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--attempt-limit", type=int)
    args = parser.parse_args()
    requests, events, source = load_evidence(args.task_root, args.summary)
    if args.attempt_limit is not None:
        if args.attempt_limit <= 0 or args.attempt_limit > len(requests):
            raise ValueError("attempt_limit_invalid")
        requests = requests[:args.attempt_limit]
    result = classify(requests, events)
    print(json.dumps({"source": source, **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
