"""新任务显式启用的持久预算；输入是估算，未知用量阻断后续实际 HTTP。"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import uuid4


SCHEMA = "task-token-budget-v1"
STATE_PATH = "evidence/task-budget-v1.json"
MARKER_PATH = ".task-budget-v1.enabled.json"
LOCK_PATH = ".task-budget-v1.lock"
REJECTIONS_PATH = "evidence/task-budget-rejections-v1.json"
REJECTIONS_SCHEMA = "task-budget-rejections-v1"
ESTIMATE_KIND = "caller_estimate_not_tokenizer"


class TaskBudgetError(RuntimeError):
    """预算拒绝与模型网络错误分开，调用方不得将其作为 HTTP 重试理由。"""

    def __init__(self, code: str, *, diagnostics: dict | None = None):
        """保存稳定错误码，异常不包含请求正文、凭据或模型输出。"""
        self.code = code
        self.diagnostics = diagnostics
        super().__init__(code)


def _integer(value, minimum: int = 0) -> bool:
    """只接受真正的非负整数，避免布尔值或字符串绕过计数校验。"""
    return type(value) is int and value >= minimum


def _root(root: Path) -> Path:
    """拒绝不存在、非目录或带符号链接的任务位置，不自动重建恢复现场。"""
    root = Path(root).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise TaskBudgetError("task_budget_unsafe_path")
    if not root.is_dir():
        raise TaskBudgetError("task_budget_root_missing")
    for name in (STATE_PATH, MARKER_PATH, LOCK_PATH, REJECTIONS_PATH, "evidence"):
        if (root / name).is_symlink():
            raise TaskBudgetError("task_budget_unsafe_path")
    return root


def _present(root: Path) -> bool:
    """任一预算痕迹均要求完整恢复；完全未启用的旧目录保持只读兼容。"""
    return any((root / name).exists() for name in (STATE_PATH, MARKER_PATH, LOCK_PATH, REJECTIONS_PATH))


def _sync_directory(path: Path) -> None:
    """在支持目录同步的平台持久化重命名，Windows 保留文件 fsync 保证。"""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path: Path, data: dict) -> None:
    """先同步完整临时文件再原子替换，任何失败都不能被当成发送许可。"""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except OSError as error:
        raise TaskBudgetError("task_budget_storage_error") from error
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _lock(root: Path):
    """使用操作系统文件锁串行化读改写；恢复时不创建缺失的锁文件。"""
    path = root / LOCK_PATH
    if not path.is_file():
        raise TaskBudgetError("task_budget_recovery_missing")
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TaskBudgetError("task_budget_unsafe_path")
        if os.fstat(descriptor).st_size != 1 or os.read(descriptor, 1) != b"\0":
            raise TaskBudgetError("task_budget_corrupt")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _unique_keys(pairs: list[tuple]) -> dict:
    """拒绝重复 JSON 字段，防止不同解析器对同一计数取不同值。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _read(path: Path) -> dict:
    """严格读取恢复文件，缺失、非法 JSON 或非对象一律关闭预算入口。"""
    if not path.is_file() or path.is_symlink():
        raise TaskBudgetError("task_budget_recovery_missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (OSError, UnicodeError, ValueError) as error:
        raise TaskBudgetError("task_budget_corrupt") from error
    if not isinstance(data, dict):
        raise TaskBudgetError("task_budget_corrupt")
    return data


def _limits(limits: dict) -> bool:
    """验证不可变限额，输出预留必须能装入总 Token 额度。"""
    return (isinstance(limits, dict)
            and set(limits) == {"total_tokens", "http_limit", "max_output_tokens"}
            and all(_integer(value, 1) for value in limits.values())
            and limits["max_output_tokens"] <= limits["total_tokens"])


def _usage(usage) -> tuple[dict | None, int | None, str | None]:
    """只保存用量数字；思考已在 completion 中，不重复加 reasoning_tokens。"""
    if not isinstance(usage, dict):
        return None, None, None
    names = ("total_tokens", "prompt_tokens", "completion_tokens")
    present = {key: usage[key] for key in names if key in usage}
    if not present or any(not _integer(value) for value in present.values()):
        return None, None, None
    total = present.get("total_tokens")
    prompt, completion = present.get("prompt_tokens"), present.get("completion_tokens")
    if total is not None:
        if (any(value > total for value in (prompt, completion) if value is not None)
                or (prompt is not None and completion is not None and prompt + completion != total)):
            return None, None, None
        source = "provider_total"
    elif prompt is not None and completion is not None:
        total, source = prompt + completion, "prompt_plus_completion"
    else:
        return present, None, None
    # 缓存命中也属于输入用量，不因折价而从实际 Token 总数中扣除。
    return present, total, source


def _validate(state: dict, marker: dict) -> dict:
    """交叉核对版本、固定限额、逐次用量和汇总，损坏不能退回零计数。"""
    shared = ("schema", "budget_id", "limits")
    if (set(state) != {"schema", "budget_id", "limits", "revision", "http_attempts", "known_tokens", "attempts"}
            or set(marker) != set(shared)
            or state.get("schema") != SCHEMA or marker.get("schema") != SCHEMA
            or not isinstance(state.get("budget_id"), str) or len(state["budget_id"]) != 32
            or any(character not in "0123456789abcdef" for character in state["budget_id"])
            or any(state.get(key) != marker.get(key) for key in shared)
            or not _limits(state.get("limits"))
            or not _integer(state.get("revision"))
            or not _integer(state.get("http_attempts"))
            or not _integer(state.get("known_tokens"))
            or not isinstance(state.get("attempts"), list)):
        raise TaskBudgetError("task_budget_corrupt")
    attempts = state["attempts"]
    if (state["http_attempts"] != len(attempts)
            or len(attempts) > state["limits"]["http_limit"]
            or state["revision"] < len(attempts)):
        raise TaskBudgetError("task_budget_corrupt")
    known, unresolved = 0, 0
    for index, item in enumerate(attempts, 1):
        if not isinstance(item, dict):
            raise TaskBudgetError("task_budget_corrupt")
        required = {"attempt", "budget_id", "request_id", "provider", "input_estimate",
                    "input_estimate_kind", "max_output_tokens", "reserved_tokens", "status",
                    "usage", "actual_tokens", "usage_source"}
        if (set(item) != required or type(item["attempt"]) is not int or item["attempt"] != index
                or item["budget_id"] != state["budget_id"]
                or any(not isinstance(item[key], str) or not item[key].strip()
                       for key in ("request_id", "provider", "status"))
                or not _integer(item["input_estimate"])
                or item["input_estimate_kind"] != ESTIMATE_KIND
                or not _integer(item["max_output_tokens"], 1)
                or item["max_output_tokens"] > state["limits"]["max_output_tokens"]
                or not _integer(item["reserved_tokens"])
                or item["reserved_tokens"] != item["input_estimate"] + item["max_output_tokens"]):
            raise TaskBudgetError("task_budget_corrupt")
        usage, actual, source = _usage(item["usage"])
        if (usage != item["usage"] or actual != item["actual_tokens"] or source != item["usage_source"]
                or (actual is not None and not _integer(item["actual_tokens"]))
                or (item["status"] == "send_unknown" and item["usage"] is not None)):
            raise TaskBudgetError("task_budget_corrupt")
        # 未知请求后不应出现任何新请求；这也是恢复时的安全不变量。
        if unresolved or known + item["reserved_tokens"] > state["limits"]["total_tokens"]:
            raise TaskBudgetError("task_budget_corrupt")
        unresolved += int(actual is None)
        known += actual or 0
    if known != state["known_tokens"]:
        raise TaskBudgetError("task_budget_corrupt")
    return state


def _load(root: Path) -> dict:
    """调用方持锁时读取完整现场，标记和账本缺任一项均停止。"""
    return _validate(_read(root / STATE_PATH), _read(root / MARKER_PATH))


def _rejection_reason(state: dict, input_estimate: int, output: int) -> tuple[str, str] | None:
    """保持原准入判定顺序，区分未知用量、次数用尽、实际用尽和本次预约过大。"""
    if any(item["actual_tokens"] is None for item in state["attempts"]):
        return "task_budget_usage_unresolved", "usage_unresolved"
    if state["http_attempts"] >= state["limits"]["http_limit"]:
        return "task_budget_http_exhausted", "http_exhausted"
    if state["known_tokens"] + input_estimate + output > state["limits"]["total_tokens"]:
        reason = ("actual_usage_exhausted" if state["known_tokens"] >= state["limits"]["total_tokens"]
                  else "admission_reservation_exceeded")
        return "task_budget_tokens_exhausted", reason
    return None


def _rejection_snapshot(state: dict, input_estimate: int, output: int, number: int) -> dict:
    """只投影固定字段和数字，不持久化调用方身份、请求正文或异常原文。"""
    code, reason = _rejection_reason(state, input_estimate, output)
    limits = state["limits"]
    unresolved = [item for item in state["attempts"] if item["actual_tokens"] is None]
    return {"rejection": number, "budget_id": state["budget_id"], "ledger_revision": state["revision"],
            "code": code, "reason": reason, "request_sent": False,
            "input_estimate": input_estimate, "input_estimate_kind": ESTIMATE_KIND,
            "max_output_tokens": output, "requested_tokens": input_estimate + output,
            "known_tokens": state["known_tokens"], "total_tokens": limits["total_tokens"],
            "remaining_known_tokens": max(0, limits["total_tokens"] - state["known_tokens"]),
            "input_estimate_limit": limits["total_tokens"] - state["known_tokens"] - output,
            "http_attempts": state["http_attempts"], "http_limit": limits["http_limit"],
            "unresolved_attempts": [item["attempt"] for item in unresolved],
            "reserved_tokens": sum(item["reserved_tokens"] for item in unresolved)}


def _load_rejections(root: Path, state: dict) -> dict:
    """在同一账本锁内校验可选诊断历史；旧 v1 账本无需改写或迁移。"""
    path = root / REJECTIONS_PATH
    empty = {"schema": REJECTIONS_SCHEMA, "budget_id": state["budget_id"], "rejections": []}
    if not path.exists():
        return empty
    data = _read(path)
    if (set(data) != set(empty) or data["schema"] != REJECTIONS_SCHEMA
            or data["budget_id"] != state["budget_id"] or not isinstance(data["rejections"], list)):
        raise TaskBudgetError("task_budget_rejections_corrupt")
    prior_revision = 0
    for number, item in enumerate(data["rejections"], 1):
        if (not isinstance(item, dict) or not _integer(item.get("http_attempts"))
                or item["http_attempts"] > state["http_attempts"]
                or not _integer(item.get("ledger_revision"), max(prior_revision, item["http_attempts"]))
                or item["ledger_revision"] > state["revision"]
                or not _integer(item.get("input_estimate"))
                or not _integer(item.get("max_output_tokens"), 1)
                or item["max_output_tokens"] > state["limits"]["max_output_tokens"]
                or not isinstance(item.get("unresolved_attempts"), list)
                or (item["unresolved_attempts"] != [] and
                    (len(item["unresolved_attempts"]) != 1
                     or not _integer(item["unresolved_attempts"][0], 1)
                     or item["unresolved_attempts"][0] != item["http_attempts"]))):
            raise TaskBudgetError("task_budget_rejections_corrupt")
        # 用不可变的请求前缀复算当时余额；后来补结算的未知项还原为当时未决。
        attempts = [dict(attempt) for attempt in state["attempts"][:item["http_attempts"]]]
        for attempt in attempts:
            if attempt["attempt"] in item["unresolved_attempts"]:
                attempt["actual_tokens"] = None
        snapshot = {**state, "revision": item["ledger_revision"], "http_attempts": item["http_attempts"],
                    "attempts": attempts, "known_tokens": sum(attempt["actual_tokens"] or 0 for attempt in attempts)}
        if (_rejection_reason(snapshot, item["input_estimate"], item["max_output_tokens"]) is None
                or item != _rejection_snapshot(snapshot, item["input_estimate"], item["max_output_tokens"], number)
                or any(type(item[key]) is not int for key in ("rejection", "known_tokens", "total_tokens",
                    "remaining_known_tokens", "input_estimate_limit", "requested_tokens", "http_limit", "reserved_tokens"))
                or item["request_sent"] is not False):
            raise TaskBudgetError("task_budget_rejections_corrupt")
        prior_revision = item["ledger_revision"]
    return data


def initialize(root: Path, *, total_tokens: int = 1_000_000, http_limit: int = 100,
               max_output_tokens: int = 8192) -> dict:
    """仅对显式新建的空任务目录启用一次；旧目录或残缺初始化绝不重置。"""
    limits = {"total_tokens": total_tokens, "http_limit": http_limit, "max_output_tokens": max_output_tokens}
    if not _limits(limits):
        raise TaskBudgetError("task_budget_limits_invalid")
    root = Path(root).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise TaskBudgetError("task_budget_unsafe_path")
    root.mkdir(parents=True, exist_ok=True)
    root = _root(root)
    if any(root.iterdir()):
        raise TaskBudgetError("task_budget_new_empty_task_required")
    # 独占创建永久锁文件，竞争初始化或进程中断均留下拒绝静默重置的证据。
    try:
        descriptor = os.open(root / LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise TaskBudgetError("task_budget_new_empty_task_required") from error
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    _sync_directory(root)
    with _lock(root):
        if set(path.name for path in root.iterdir()) != {LOCK_PATH}:
            raise TaskBudgetError("task_budget_new_empty_task_required")
        state = {"schema": SCHEMA, "budget_id": uuid4().hex, "limits": limits, "revision": 0,
                 "http_attempts": 0, "known_tokens": 0, "attempts": []}
        (root / "evidence").mkdir()
        _write(root / MARKER_PATH, {key: state[key] for key in ("schema", "budget_id", "limits")})
        _write(root / STATE_PATH, state)
        return state


def load(root: Path) -> dict | None:
    """返回已验证账本；未启用旧任务返回 None，且不创建或改写任何文件。"""
    root = _root(root)
    if not _present(root):
        return None
    with _lock(root):
        return _load(root)


def reserve(root: Path, *, request_id: str, provider: str, input_estimate: int,
            max_output_tokens: int | None = None, expected_budget_id: str | None = None) -> dict | None:
    """实际发送前持锁预留一次 HTTP 和估算输入加输出上限；每次重试独立计数。"""
    root = _root(root)
    if not _present(root):
        if expected_budget_id is not None:
            raise TaskBudgetError("experiment_token_budget_binding_mismatch")
        return None
    with _lock(root):
        state = _load(root)
        # 实验身份在同一预约锁内重核，防止检查后换账绕过累计消费。
        if expected_budget_id is not None and state["budget_id"] != expected_budget_id:
            raise TaskBudgetError("experiment_token_budget_binding_mismatch")
        rejections = _load_rejections(root, state)
        limits = state["limits"]
        output = limits["max_output_tokens"] if max_output_tokens is None else max_output_tokens
        if (not _integer(input_estimate) or not _integer(output, 1)
                or output > limits["max_output_tokens"]
                or any(not isinstance(value, str) or not value.strip() for value in (request_id, provider))):
            raise TaskBudgetError("task_budget_reservation_invalid")
        if _rejection_reason(state, input_estimate, output):
            # 未发送的拒绝仅写独立诊断，HTTP、已知成本、预留和账本 revision 均不变。
            details = _rejection_snapshot(state, input_estimate, output, len(rejections["rejections"]) + 1)
            rejections["rejections"].append(details)
            _write(root / REJECTIONS_PATH, rejections)
            raise TaskBudgetError(details["code"], diagnostics=details)
        item = {"attempt": state["http_attempts"] + 1, "budget_id": state["budget_id"],
                "request_id": request_id, "provider": provider, "input_estimate": input_estimate,
                "input_estimate_kind": ESTIMATE_KIND, "max_output_tokens": output,
                "reserved_tokens": input_estimate + output, "status": "send_unknown",
                "usage": None, "actual_tokens": None, "usage_source": None}
        state["attempts"].append(item)
        state["http_attempts"] += 1
        state["revision"] += 1
        # 成功持久化才返回发送许可；发送前崩溃也不返还已登记的 HTTP 次数。
        _write(root / STATE_PATH, state)
        return dict(item)


def finish(root: Path, attempt: dict | None, *, status: str, usage=None) -> dict | None:
    """按每次实际用量结算；未知保留预留和阻断，已结算结果只允许相同重放。"""
    if attempt is None:
        return None
    root = _root(root)
    with _lock(root):
        state = _load(root)
        number = attempt.get("attempt") if isinstance(attempt, dict) else None
        if (not _integer(number, 1) or number > state["http_attempts"]
                or attempt.get("budget_id") != state["budget_id"]):
            raise TaskBudgetError("task_budget_attempt_invalid")
        if not isinstance(status, str) or not status.strip() or status == "send_unknown":
            raise TaskBudgetError("task_budget_status_invalid")
        item = state["attempts"][number - 1]
        identity_fields = ("budget_id", "request_id", "provider", "input_estimate", "input_estimate_kind",
                           "max_output_tokens", "reserved_tokens")
        if any(attempt.get(key) != item[key] for key in identity_fields):
            raise TaskBudgetError("task_budget_attempt_invalid")
        clean_usage, actual, source = _usage(usage)
        updates = {"status": status, "usage": clean_usage, "actual_tokens": actual, "usage_source": source}
        if item["actual_tokens"] is not None:
            if any(item[key] != value for key, value in updates.items()):
                raise TaskBudgetError("task_budget_attempt_already_finalized")
            return state
        if all(item[key] == value for key, value in updates.items()):
            return state
        item.update(updates)
        state["known_tokens"] += actual or 0
        state["revision"] += 1
        _write(root / STATE_PATH, state)
        return state


def report(root: Path) -> dict | None:
    """提供明确停止原因与已知成本；输入估算及未知用量不冒充精确硬上限。"""
    root = _root(root)
    if not _present(root):
        return None
    # 账本和拒绝证据必须属于同一持锁快照，避免并发发送后把旧拒绝当成当前阻塞。
    with _lock(root):
        state = _load(root)
        rejections = _load_rejections(root, state)["rejections"]
    last_rejection = rejections[-1] if rejections else None
    rejection_current = bool(last_rejection and last_rejection["ledger_revision"] == state["revision"])
    limits = state["limits"]
    unresolved = [item for item in state["attempts"] if item["actual_tokens"] is None]
    reason = ("usage_unresolved" if unresolved else
              "http_exhausted" if state["http_attempts"] >= limits["http_limit"] else
              "tokens_exhausted" if state["known_tokens"] >= limits["total_tokens"] else
              last_rejection["reason"] if rejection_current else None)
    return {"schema": SCHEMA, "budget_id": state["budget_id"], "limits": dict(limits),
            "status": "blocked" if reason else "ready", "stop_reason": reason,
            "http_attempts": state["http_attempts"], "known_tokens": state["known_tokens"],
            "remaining_known_tokens": max(0, limits["total_tokens"] - state["known_tokens"]),
            "unresolved_attempts": [item["attempt"] for item in unresolved],
            "reserved_tokens": sum(item["reserved_tokens"] for item in unresolved),
            "input_estimate_kind": ESTIMATE_KIND, "exact_token_cap_guaranteed": False,
            "report_is_send_permission": False,
            "known_tokens_exceeded_limit": state["known_tokens"] > limits["total_tokens"],
            "last_rejection": last_rejection, "last_rejection_current": rejection_current,
            "http_counter_semantics": "persisted_before_send_including_uncertain_attempts"}
