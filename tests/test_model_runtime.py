from sqlalchemy import select

from backend.app.config import settings
from backend.app.config import get_deepseek_api_key, get_kimi_api_key
from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Message, Step, Task
from backend.app.runtime.contracts import ModelRequest
from backend.app.runtime.model import DeepSeekRuntime, KimiRuntime, create_model_runtime


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"writing"}}]}'
        yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"write","arguments":"{\\"path\\":\\"docs/product.md\\",\\"content\\":\\"ok\\",\\"overwrite\\":false}"}}]}}]}'
        yield "data: [DONE]"


class FakeClient:
    def __init__(self, captured, **kwargs):
        self.captured = captured
        self.captured["client_options"] = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def stream(self, method, url, **kwargs):
        self.captured["method"] = method
        self.captured.update({"url": url, **kwargs})
        return FakeResponse()


def test_deepseek_request_and_tool_call_mapping(monkeypatch):
    captured = {}

    monkeypatch.setattr(settings, "deepseek_api_key", "test-only-key")
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client",
                        lambda **kwargs: FakeClient(captured, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="model-contract")
        db.add(task)
        db.flush()
        request = ModelRequest("instructions", "input", {"state": "test"}, [], "request-1")
        result = DeepSeekRuntime(db).call(task.id, request)
        db.commit()

        assert captured["url"] == "https://api.deepseek.com/chat/completions"
        assert captured["client_options"] == {"trust_env": False, "timeout": 60}
        assert captured["headers"] == {"Authorization": "Bearer test-only-key"}
        assert captured["json"]["model"] == "deepseek-flash"
        assert captured["json"]["stream"] is True
        assert result.finish_reason == "tool_calls"
        assert result.actions[0].tool_name == "write"
        assert result.actions[0].parameters["path"] == "docs/product.md"
        assert db.scalar(select(Message).where(Message.id == result.message_id)).content == "writing"


def test_streaming_text_is_forwarded_incrementally(monkeypatch):
    captured = {}
    deltas = []
    monkeypatch.setattr(settings, "deepseek_api_key", "test-only-key")
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client",
                        lambda **kwargs: FakeClient(captured, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="stream-contract")
        db.add(task)
        db.flush()
        DeepSeekRuntime(db).call(task.id, ModelRequest(
            "instructions", "input", {}, [], "request-stream", on_delta=deltas.append,
        ))
    assert deltas == ["writing"]


def test_key_can_be_loaded_from_ignored_file(tmp_path, monkeypatch):
    key_file = tmp_path / "deepseek_api_key"
    key_file.write_text("test-file-key\n", encoding="utf-8")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "deepseek_api_key_file", key_file)
    assert get_deepseek_api_key() == "test-file-key"


def test_kimi_request_and_tool_call_mapping(monkeypatch):
    captured = {}
    monkeypatch.setattr(settings, "kimi_api_key", "test-only-kimi-key")
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client",
                        lambda **kwargs: FakeClient(captured, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="kimi-model-contract")
        db.add(task)
        db.flush()
        request = ModelRequest("instructions", "input", {"state": "test"}, [], "request-kimi")
        result = KimiRuntime(db).call(task.id, request)

        assert captured["url"] == "https://api.kimi.com/coding/v1/chat/completions"
        assert captured["client_options"] == {"trust_env": False, "timeout": 180}
        assert captured["headers"] == {"Authorization": "Bearer test-only-kimi-key"}
        assert captured["json"]["model"] == "kimi-for-coding"
        assert captured["json"]["thinking"] == {"type": "disabled"}
        assert captured["json"]["max_completion_tokens"] == 8192
        assert result.actions[0].tool_name == "write"


def test_kimi_key_can_be_loaded_from_ignored_file(tmp_path, monkeypatch):
    key_file = tmp_path / "kimi_api_key"
    key_file.write_text("test-kimi-file-key\n", encoding="utf-8")
    monkeypatch.setattr(settings, "kimi_api_key", "")
    monkeypatch.setattr(settings, "kimi_api_key_file", key_file)
    assert get_kimi_api_key() == "test-kimi-file-key"


def test_model_provider_can_select_kimi(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "kimi")
    with SessionLocal() as db:
        runtime = create_model_runtime(db)
        assert isinstance(runtime, KimiRuntime)
        assert runtime.provider == "kimi"


def test_document_steps_use_kimi_and_execution_steps_use_deepseek(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "unknown")
    with SessionLocal() as db:
        for step in (Step.product_docs, Step.architecture_docs, Step.dev_design):
            assert isinstance(create_model_runtime(db, step), KimiRuntime)
        for step in (Step.develop, Step.test, Step.start_product, Step.verify_product):
            assert isinstance(create_model_runtime(db, step), DeepSeekRuntime)


def test_unknown_model_provider_fails_explicitly(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "unknown")
    with SessionLocal() as db:
        try:
            create_model_runtime(db)
        except RuntimeError as exc:
            assert "Unsupported model provider" in str(exc)
        else:
            raise AssertionError("unknown provider should fail")


def test_tool_history_uses_native_assistant_and_tool_messages(monkeypatch):
    captured = {}
    monkeypatch.setattr(settings, "deepseek_api_key", "test-only-key")
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client",
                        lambda **kwargs: FakeClient(captured, **kwargs))
    history = [{
        "action": {"call_id": "call-old", "tool_name": "write",
                   "parameters": {"path": "product/a.js", "content": "x", "overwrite": False}},
        "result": {"call_id": "call-old", "tool_name": "write", "status": "succeeded",
                   "output": {"bytes_written": 1}, "error": None},
    }]
    with SessionLocal() as db:
        task = Task(task_name="native-tool-history")
        db.add(task)
        db.flush()
        DeepSeekRuntime(db).call(task.id, ModelRequest("instructions", "input",
                                                      {"tool_history": history}, [], "request-2"))
    messages = captured["json"]["messages"]
    assert messages[2]["role"] == "assistant"
    assert messages[2]["tool_calls"][0]["id"] == "call-old"
    assert messages[3]["role"] == "tool"
    assert messages[3]["tool_call_id"] == "call-old"
