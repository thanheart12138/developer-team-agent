import json

import pytest
from sqlalchemy import select

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus, TraceRecord
from backend.app.runtime.tracing import _atomic_create, record_trace


def test_live_snapshot_is_replaced_expired_and_cleared(tmp_path, monkeypatch):
    from backend.app.runtime.tracing import publish_live_response, read_live_response

    monkeypatch.setattr("backend.app.runtime.tracing.tempfile.gettempdir", lambda: str(tmp_path))
    publish_live_response("/task-a", "request-a", "first")
    publish_live_response("/task-a", "request-a", "first second")
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert read_live_response("/task-a")["text"] == "first second"
    assert read_live_response("/task-b") == {}
    timestamp = read_live_response("/task-a")["updated_at"]
    monkeypatch.setattr("backend.app.runtime.tracing.time.time", lambda: timestamp + 16)
    assert read_live_response("/task-a") == {}
    publish_live_response("/task-a", "", "")
    assert read_live_response("/task-a") == {}
    assert "first second" not in next(tmp_path.glob("*.json")).read_text()


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_usage_counts_survive_but_credentials_remain_redacted():
    from backend.app.runtime.tracing import sanitize

    assert sanitize({"usage": {"prompt_tokens": 42, "completion_tokens": 0,
                               "total_tokens": 42, "prompt_cache_hit_tokens": 12},
                     "max_completion_tokens": 8192,
                     "token": "secret", "prompt_tokens": "secret", "api_key": "secret"}) == {
        "usage": {"prompt_tokens": 42, "completion_tokens": 0, "total_tokens": 42,
                  "prompt_cache_hit_tokens": 12},
        "max_completion_tokens": 8192,
        "token": "[REDACTED]", "prompt_tokens": "[REDACTED]", "api_key": "[REDACTED]"}


def test_trace_is_append_only_ordered_and_redacted(tmp_path):
    with SessionLocal() as db:
        task = Task(task_name="trace", cur_step=Step.develop, status=TaskStatus.running,
                    workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=2)
        db.add(run)
        db.flush()

        first = record_trace(db, task, run, "model_request", "running", "请求模型", payload={
            "api_key": "must-not-leak", "nested": {"Authorization": "Bearer secret", "input": "visible"},
        })
        second = record_trace(db, task, run, "model_response", "succeeded", "收到响应", payload={"text": "ok"})
        db.commit()

        assert (first.sequence, second.sequence) == (1, 2)
        detail = json.loads((tmp_path / first.detail_path).read_text(encoding="utf-8"))
        assert detail["payload"]["api_key"] == "[REDACTED]"
        assert detail["payload"]["nested"]["Authorization"] == "[REDACTED]"
        assert detail["payload"]["nested"]["input"] == "visible"
        assert db.scalars(select(TraceRecord).order_by(TraceRecord.sequence)).all() == [first, second]


def test_trace_detail_cannot_be_overwritten(tmp_path):
    with SessionLocal() as db:
        task = Task(task_name="immutable", workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        first = record_trace(db, task, None, "step", "running", "start")
        path = tmp_path / first.detail_path
        original = path.read_bytes()
        with pytest.raises(FileExistsError):
            _atomic_create(path, b"replacement")
        assert path.read_bytes() == original
