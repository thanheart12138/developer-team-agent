"""数据库任务、阶段、事件、消息与 Trace 模型。"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    waiting_user = "waiting_user"
    waiting_acceptance = "waiting_acceptance"
    succeeded = "succeeded"
    failed = "failed"


class StepStatus(str, enum.Enum):
    running = "running"
    waiting_user = "waiting_user"
    succeeded = "succeeded"
    failed = "failed"


class EventStatus(str, enum.Enum):
    pending = "pending"
    consumed = "consumed"
    rejected = "rejected"


class Step(str, enum.Enum):
    product_docs = "product_docs"
    architecture_docs = "architecture_docs"
    dev_design = "dev_design"
    develop = "develop"
    test = "test"
    start_product = "start_product"
    verify_product = "verify_product"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(200))
    cur_step: Mapped[Step] = mapped_column(Enum(Step), default=Step.product_docs)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending)
    workspace_path: Mapped[str | None] = mapped_column(String(1000))
    result_url: Mapped[str | None] = mapped_column(String(500))
    port: Mapped[int | None] = mapped_column(Integer)
    process_id: Mapped[int | None] = mapped_column(Integer)
    process_command: Mapped[str | None] = mapped_column(Text)
    product_path: Mapped[str | None] = mapped_column(String(1000))
    repair_round: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    step_runs: Mapped[list["StepRun"]] = relationship(back_populates="task")
    trace_records: Mapped[list["TraceRecord"]] = relationship(back_populates="task")


class StepRun(TimestampMixin, Base):
    __tablename__ = "step_runs"
    __table_args__ = (UniqueConstraint("task_id", "step", "attempt", name="uq_step_attempt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    step: Mapped[Step] = mapped_column(Enum(Step))
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.running)
    attempt: Mapped[int] = mapped_column(Integer)
    model_call_count: Mapped[int] = mapped_column(Integer, default=0)
    input_path: Mapped[str | None] = mapped_column(String(1000))
    output_path: Mapped[str | None] = mapped_column(String(1000))
    message_path: Mapped[str | None] = mapped_column(String(1000))
    checkpoint_path: Mapped[str | None] = mapped_column(String(1000))
    last_completed_action_index: Mapped[int] = mapped_column(Integer, default=-1)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    task: Mapped[Task] = relationship(back_populates="step_runs")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.pending)
    data: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TraceRecord(Base):
    __tablename__ = "trace_records"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_trace_task_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_run_id: Mapped[int | None] = mapped_column(ForeignKey("step_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(String(50))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    detail_path: Mapped[str] = mapped_column(String(1000))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    task: Mapped[Task] = relationship(back_populates="trace_records")
