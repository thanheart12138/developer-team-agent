import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import StepRun, Task, TraceRecord

SENSITIVE_PARTS = ("authorization", "api_key", "apikey", "token", "password", "secret")
logger = logging.getLogger(__name__)


def sanitize(value: Any) -> Any:
    # 递归脱敏 Trace 数据中的敏感字段。
    if isinstance(value, dict):
        return {
            # 递归检查字段名，避免已知敏感键进入持久化详情。
            str(key): "[REDACTED]" if any(part in str(key).lower() for part in SENSITIVE_PARTS)
            else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def _atomic_create(path: Path, content: bytes) -> None:
    # 原子创建不可覆盖的 Trace 详情文件。
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("trace_detail_already_exists")
    # 使用临时文件和硬链接创建不可覆盖的详情。
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_trace(db: Session, task: Task, run: StepRun | None, trace_type: str, status: str,
                 title: str, summary: str = "", payload: Any = None,
                 metadata: dict | None = None, started_at: datetime | None = None,
                 finished_at: datetime | None = None) -> TraceRecord:
    # 写入 Trace 详情文件与数据库索引记录。
    # 锁定任务行，确保同一任务的 Trace 序号连续且唯一。
    db.execute(select(Task.id).where(Task.id == task.id).with_for_update())
    sequence = (db.scalar(select(func.max(TraceRecord.sequence)).where(
        TraceRecord.task_id == task.id)) or 0) + 1
    step = run.step.value if run else task.cur_step.value
    attempt = run.attempt if run else 0
    relative = Path("traces") / step / str(attempt) / f"{sequence:06d}-{trace_type}.json"
    root = Path(task.workspace_path or "").resolve()
    detail = (root / relative).resolve()
    # 拒绝写入当前任务工作区之外的详情路径。
    if root not in detail.parents:
        raise ValueError("trace_path_outside_workspace")
    created_at = datetime.utcnow()
    # 在序列化前脱敏完整 payload 和元数据。
    document = sanitize({
        "sequence": sequence, "type": trace_type, "status": status,
        "title": title, "summary": summary, "payload": payload,
        "metadata": metadata or {}, "started_at": started_at,
        "finished_at": finished_at, "created_at": created_at,
    })
    encoded = json.dumps(document, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    # 先保存完整详情，再建立轻量数据库索引。
    _atomic_create(detail, encoded)
    record = TraceRecord(
        task_id=task.id, step_run_id=run.id if run else None, sequence=sequence,
        step=step, attempt=attempt, type=trace_type, status=status,
        title=title, summary=summary, detail_path=str(relative),
        metadata_json=sanitize(metadata or {}), started_at=started_at,
        finished_at=finished_at, created_at=created_at,
    )
    db.add(record)
    db.flush()
    return record


def safe_record_trace(db: Session, *args, **kwargs) -> TraceRecord | None:
    # 在嵌套事务中尝试记录 Trace，失败时不中断主流程。
    try:
        # 隔离 Trace 写入错误，主业务事务可继续执行。
        with db.begin_nested():
            return record_trace(db, *args, **kwargs)
    except Exception as exc:
        logger.warning("Trace recording failed: %s", type(exc).__name__)
        return None
