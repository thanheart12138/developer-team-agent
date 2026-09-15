"""API 请求与响应的数据结构及字段约束。"""

from typing import Literal

from pydantic import BaseModel, Field


class CreateTaskRequest(BaseModel):
    task_name: str = Field(min_length=1, max_length=200)
    initial_message: str = Field(min_length=1)


class TaskResponse(BaseModel):
    task_id: int
    status: str
    cur_step: str
    latest_message_id: int = 0
    artifact_available: bool = False
    product_document_available: bool = False
    result_url: str | None = None
    failure_reason: str | None = None


class CreateEventRequest(BaseModel):
    type: Literal["user_message", "document_approval", "acceptance_result"]
    data: dict


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: str | None = None


class TraceResponse(BaseModel):
    sequence: int
    step: str
    attempt: int
    type: str
    status: str
    title: str
    summary: str
    metadata: dict
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str
