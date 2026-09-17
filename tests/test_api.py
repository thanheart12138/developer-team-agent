from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.database import Base, engine
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime.tracing import record_trace


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_create_and_query_task_with_initial_message():
    client = TestClient(app)
    created = client.post("/api/tasks", json={"task_name": "calculator", "initial_message": "build it"})
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "pending"
    assert body["cur_step"] == "product_docs"

    task = client.get(f"/api/tasks/{body['task_id']}").json()
    assert task["latest_message_id"] > 0
    messages = client.get(f"/api/tasks/{body['task_id']}/messages?after_id=0").json()
    assert messages["messages"][0] | {"created_at": None} == {
        "id": task["latest_message_id"], "role": "user", "content": "build it", "created_at": None,
    }
    assert messages["messages"][0]["created_at"]


def test_missing_task_has_explicit_error():
    response = TestClient(app).get("/api/tasks/999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"


def test_live_response_is_task_scoped_uncached_and_temporary(tmp_path):
    from backend.app.runtime.tracing import publish_live_response

    with SessionLocal() as db:
        task = Task(task_name="live", workspace_path=str(tmp_path))
        other = Task(task_name="other", workspace_path=str(tmp_path / "other"))
        db.add_all([task, other])
        db.commit()
        task_id, other_id = task.id, other.id
    client = TestClient(app)
    publish_live_response(str(tmp_path), "request-1", "实时文本")
    response = client.get(f"/api/tasks/{task_id}/live-response")
    assert response.json()["text"] == "实时文本"
    assert response.headers["cache-control"] == "no-store"
    assert client.get(f"/api/tasks/{other_id}/live-response").json() == {}
    assert client.get("/api/tasks/999/live-response").status_code == 404
    publish_live_response(str(tmp_path), "", "")
    assert client.get(f"/api/tasks/{task_id}/live-response").json() == {}


def test_event_is_created_pending():
    client = TestClient(app)
    task_id = client.post("/api/tasks", json={"task_name": "calculator", "initial_message": "build it"}).json()["task_id"]
    response = client.post(f"/api/tasks/{task_id}/events", json={
        "type": "document_approval",
        "data": {"document_type": "product", "document_version": 1, "approved": True, "feedback": ""},
    })
    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_product_draft_can_be_previewed_while_waiting(tmp_path):
    client = TestClient(app)
    task_id = client.post("/api/tasks", json={"task_name": "calculator", "initial_message": "build it"}).json()["task_id"]
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.status = TaskStatus.waiting_user
        db.add(StepRun(task_id=task.id, step=Step.product_docs,
                       status=StepStatus.waiting_user, attempt=1))
        path = Path(task.workspace_path) / "docs" / "product-v1-draft.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Calculator", encoding="utf-8")
        db.commit()
    response = client.get(f"/api/tasks/{task_id}/documents/product")
    assert response.status_code == 200
    assert response.json()["content"] == "# Calculator"
    assert client.get(f"/api/tasks/{task_id}").json()["product_document_available"] is True


def test_trace_index_is_incremental_and_detail_is_read_on_demand(tmp_path):
    client = TestClient(app)
    task_id = client.post("/api/tasks", json={"task_name": "trace", "initial_message": "build"}).json()["task_id"]
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.workspace_path = str(tmp_path)
        first = record_trace(db, task, None, "step", "running", "阶段开始", payload={"value": 1})
        second = record_trace(db, task, None, "validation", "succeeded", "验证通过", payload={"value": 2})
        db.commit()

    response = client.get(f"/api/tasks/{task_id}/traces?after_sequence={first.sequence}")
    assert response.status_code == 200
    assert [item["sequence"] for item in response.json()["traces"]] == [second.sequence]
    assert "payload" not in response.json()["traces"][0]

    detail = client.get(f"/api/tasks/{task_id}/traces/{second.sequence}")
    assert detail.status_code == 200
    assert detail.json()["payload"] == {"value": 2}


def test_missing_trace_detail_has_explicit_error(tmp_path):
    client = TestClient(app)
    task_id = client.post("/api/tasks", json={"task_name": "trace", "initial_message": "build"}).json()["task_id"]
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.workspace_path = str(tmp_path)
        trace = record_trace(db, task, None, "step", "running", "阶段开始")
        db.commit()
    (tmp_path / trace.detail_path).unlink()
    response = client.get(f"/api/tasks/{task_id}/traces/{trace.sequence}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "trace_detail_unavailable"


def test_workspace_file_can_be_read_but_traversal_is_rejected(tmp_path):
    client = TestClient(app)
    task_id = client.post("/api/tasks", json={"task_name": "file", "initial_message": "build"}).json()["task_id"]
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task.workspace_path = str(tmp_path)
        target = tmp_path / "product" / "app.js"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("const answer = 42;", encoding="utf-8")
        db.commit()

    response = client.get(f"/api/tasks/{task_id}/files", params={"path": "product/app.js"})
    assert response.status_code == 200
    assert response.json()["name"] == "app.js"
    assert response.json()["content"] == "const answer = 42;"
    assert len(response.json()["sha256"]) == 64

    rejected = client.get(f"/api/tasks/{task_id}/files", params={"path": "../outside.txt"})
    assert rejected.status_code == 404
    assert rejected.json()["detail"]["code"] == "workspace_file_not_found"
