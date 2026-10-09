import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Event, Message, Step, StepRun, Task, TaskStatus, TraceRecord
from .runtime.tracing import read_live_response, safe_record_trace
from .schemas import CreateEventRequest, CreateTaskRequest, MessageResponse, TaskResponse, TraceResponse

router = APIRouter(prefix="/api")


def require_task(db: Session, task_id: int) -> Task:
    # 查询任务，不存在时返回 404。
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, detail={"code": "task_not_found"})
    return task


@router.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(payload: CreateTaskRequest, db: Session = Depends(get_db)):
    # 创建任务、初始消息和对应的工作区路径。
    task = Task(task_name=payload.task_name)
    db.add(task)
    # 先取得任务 ID，随后才能建立工作区路径和初始消息。
    db.flush()
    workspace = (settings.workspace_root / str(task.id)).resolve()
    task.workspace_path = str(workspace)
    task.product_path = str(workspace / "product")
    db.add(Message(task_id=task.id, role="user", content=payload.initial_message))
    # 记录用户操作，供任务时间线和详情恢复使用。
    safe_record_trace(db, task, None, "user_event", "info", "创建任务",
                      "用户提交初始软件需求", {"event": "create_task", "initial_message": payload.initial_message})
    db.commit()
    return TaskResponse(task_id=task.id, status=task.status.value, cur_step=task.cur_step.value)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db)):
    # 返回任务状态、可用产物和最新消息位置。
    task = require_task(db, task_id)
    latest = db.scalar(select(func.max(Message.id)).where(Message.task_id == task_id)) or 0
    available = task.status in {TaskStatus.waiting_acceptance, TaskStatus.succeeded, TaskStatus.failed}
    product_document_available = False
    if task.cur_step == Step.product_docs and task.workspace_path:
        # 只检查当前产品阶段最新一次候选，避免展示旧版本。
        latest_product_run = db.scalar(select(StepRun).where(
            StepRun.task_id == task.id, StepRun.step == Step.product_docs
        ).order_by(StepRun.attempt.desc()))
        if latest_product_run:
            root = Path(task.workspace_path) / "docs"
            candidate = root / f"product-v{latest_product_run.attempt}-candidate.md"
            legacy_draft = root / f"product-v{latest_product_run.attempt}-draft.md"
            product_document_available = candidate.is_file() or legacy_draft.is_file()
    from .runtime.repair_runtime import load as load_repair
    repair = load_repair(Path(task.workspace_path)) if task.workspace_path else None
    return TaskResponse(task_id=task.id, status=task.status.value, cur_step=task.cur_step.value,
                        latest_message_id=latest, artifact_available=available,
                        product_document_available=product_document_available,
                        result_url=task.result_url, failure_reason=task.failure_reason,
                        task_version=task.version, execution_mode=repair.get("workflow") if repair else None,
                        repair_state=repair.get("state") if repair else None,
                        stop_reason=repair.get("stop_reason") if repair else None,
                        budget=({key: value for key, value in repair["budget"].items() if key != "requests"}
                                if repair else None), submission_id=repair.get("submission_id") if repair else None,
                        repair_decision=(repair['session']['decisions'][-1]
                                         if repair and repair['state'] == 'waiting_decision' else None))


@router.post("/tasks/{task_id}/events", status_code=202)
def create_event(task_id: int, payload: CreateEventRequest, db: Session = Depends(get_db)):
    # 记录用户事件并提交给 Worker 后续消费。
    require_task(db, task_id)
    if payload.type == "repair_request":
        from .runtime.repair_runtime import isolation_ready
        if not isolation_ready():
            # 入口明确反馈阻塞，不把尚未允许执行的请求显示为已开始。
            raise HTTPException(409, detail={"code": "repair_execution_isolation_pending"})
    event = Event(task_id=task_id, type=payload.type, data=payload.data)
    db.add(event)
    task = require_task(db, task_id)
    # 记录用户操作，供任务时间线和详情恢复使用。
    safe_record_trace(db, task, None, "user_event", "info", "提交用户事件",
                      payload.type, {"event_type": payload.type, "data": payload.data})
    db.commit()
    return {"event_id": event.id, "status": event.status.value}


@router.get("/tasks/{task_id}/messages")
def get_messages(task_id: int, after_id: int = 0, db: Session = Depends(get_db)):
    # 按消息 ID 增量查询任务对话。
    require_task(db, task_id)
    # 按游标读取新增记录，保持前端增量轮询的顺序。
    rows = db.scalars(select(Message).where(Message.task_id == task_id, Message.id > after_id)
                      .order_by(Message.id)).all()
    messages = [MessageResponse(id=row.id, role=row.role, content=row.content,
                                created_at=row.created_at.isoformat() if row.created_at else None) for row in rows]
    return {"messages": messages, "latest_message_id": messages[-1].id if messages else after_id}


@router.get("/tasks/{task_id}/traces")
def get_traces(task_id: int, after_sequence: int = 0, db: Session = Depends(get_db)):
    # 按序号增量查询任务 Trace 摘要。
    require_task(db, task_id)
    # 按游标读取新增记录，保持前端增量轮询的顺序。
    rows = db.scalars(select(TraceRecord).where(
        TraceRecord.task_id == task_id, TraceRecord.sequence > after_sequence
    ).order_by(TraceRecord.sequence)).all()
    traces = [TraceResponse(
        sequence=row.sequence, step=row.step, attempt=row.attempt, type=row.type,
        status=row.status, title=row.title, summary=row.summary,
        metadata=row.metadata_json or {},
        started_at=row.started_at.isoformat() if row.started_at else None,
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        created_at=row.created_at.isoformat(),
    ).model_dump() for row in rows]
    return {"traces": traces, "latest_sequence": traces[-1]["sequence"] if traces else after_sequence}


@router.get("/tasks/{task_id}/live-response")
def get_live_response(task_id: int, response: Response, db: Session = Depends(get_db)):
    # 仅展示当前临时回答，不允许客户端缓存模型增量内容。
    task = require_task(db, task_id)
    response.headers["Cache-Control"] = "no-store"
    return read_live_response(task.workspace_path) if task.workspace_path else {}


@router.get("/tasks/{task_id}/traces/{sequence}")
def get_trace_detail(task_id: int, sequence: int, db: Session = Depends(get_db)):
    # 在当前任务 Trace 目录内读取完整详情。
    task = require_task(db, task_id)
    record = db.scalar(select(TraceRecord).where(
        TraceRecord.task_id == task_id, TraceRecord.sequence == sequence))
    if not record:
        raise HTTPException(404, detail={"code": "trace_not_found"})
    root = Path(task.workspace_path or "").resolve()
    # 将详情访问限定在当前任务的 traces 目录。
    trace_root = (root / "traces").resolve()
    path = (root / record.detail_path).resolve()
    if trace_root != path and trace_root not in path.parents:
        raise HTTPException(409, detail={"code": "trace_detail_unavailable"})
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(409, detail={"code": "trace_detail_unavailable"})


@router.get("/tasks/{task_id}/artifacts")
def get_artifacts(task_id: int, db: Session = Depends(get_db)):
    # 返回当前任务已存在的产物和验证报告路径。
    task = require_task(db, task_id)
    # 任务尚未进入可查看产物的状态时拒绝读取。
    if task.status not in {TaskStatus.waiting_acceptance, TaskStatus.succeeded, TaskStatus.failed}:
        raise HTTPException(409, detail={"code": "artifacts_not_available"})
    root = Path(task.workspace_path or "")
    candidates = {
        "readme": root / "product" / "README.md",
        "test_report": root / "evidence" / "test-report.md",
        "verification_report": root / "evidence" / "verification-report.md",
        "failure_report": root / "evidence" / "failure-report.md",
    }
    return {"result_url": task.result_url,
            "artifacts": {name: str(path) for name, path in candidates.items() if path.is_file()}}


@router.get("/tasks/{task_id}/documents/product")
def get_product_document(task_id: int, db: Session = Depends(get_db)):
    # 按任务状态返回候选或正式产品文档。
    task = require_task(db, task_id)
    root = Path(task.workspace_path or "") / "docs"
    # 等待审批时优先返回最新候选，否则返回正式文档。
    if task.status == TaskStatus.waiting_user:
        candidates = sorted(root.glob("product-v*-candidate.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            candidates = sorted(root.glob("product-v*-draft.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        path = candidates[0] if candidates else None
    else:
        path = root / "product.md"
    if not path or not path.is_file():
        raise HTTPException(404, detail={"code": "product_document_not_found"})
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


@router.get("/tasks/{task_id}/files")
def get_workspace_file(task_id: int, path: str = Query(min_length=1), db: Session = Depends(get_db)):
    # 校验工作区路径和大小后读取文件内容。
    task = require_task(db, task_id)
    root = Path(task.workspace_path or "").resolve()
    requested = Path(path)
    if requested.is_absolute():
        raise HTTPException(400, detail={"code": "absolute_path_rejected"})
    # 解析相对路径后再次验证目标仍位于任务工作区。
    target = (root / requested).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, detail={"code": "workspace_file_not_found"})
    # 限制读取大小并返回内容哈希，供前端核对文件。
    data = target.read_bytes()
    if len(data) > 1024 * 1024:
        raise HTTPException(413, detail={"code": "workspace_file_too_large"})
    return {"name": target.name, "path": str(requested), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content": data.decode("utf-8", errors="replace")}
