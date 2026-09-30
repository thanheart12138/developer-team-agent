from sqlalchemy import select

from backend.app.config import settings
from backend.app.config import get_deepseek_api_key, get_kimi_api_key, get_openrouter_api_key
from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Message, Step, Task
from backend.app.runtime.contracts import ModelRequest
from backend.app.runtime.model import DeepSeekRuntime, KimiRuntime, OpenRouterRuntime, build_messages, create_model_runtime


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
        assert captured["json"]["thinking"] == {"type": "enabled"}
        assert captured["json"]["stream"] is True
        assert result.finish_reason == "tool_calls"
        assert result.actions[0].tool_name == "write"
        assert result.actions[0].parameters["path"] == "docs/product.md"
        assert "stream_events" not in result.raw_response
        assert result.raw_response["text"] == "writing"
        assert result.raw_response["tool_calls"][0]["function"]["name"] == "write"
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


def test_stream_usage_only_chunk_is_preserved(monkeypatch):
    def lines(self):
        yield 'data: {"choices":[{"delta":{"content":"ok"}}],"usage":null}'
        yield 'data: {"choices":[],"usage":{"prompt_tokens":42,"completion_tokens":2,"total_tokens":44}}'
        yield 'data: {"choices":[],"usage":null}'
        yield 'data: [DONE]'

    monkeypatch.setattr(settings, "deepseek_api_key", "test-only-key")
    monkeypatch.setattr(FakeResponse, "iter_lines", lines)
    captured = {}
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client", lambda **kwargs: FakeClient(captured, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="usage")
        db.add(task)
        db.flush()
        result = DeepSeekRuntime(db).call(task.id, ModelRequest("instructions", "input", {}, [], "usage"))
    assert result.raw_response["usage"] == {"prompt_tokens": 42, "completion_tokens": 2, "total_tokens": 44}
    assert captured["json"]["stream_options"] == {"include_usage": True}


def test_deepseek_thinking_stream_and_multi_tool_history(monkeypatch):
    # 核对官方 thinking 工具协议：完整思考随同一 assistant 的多个工具调用续传。
    def lines(self):
        yield 'data: {"choices":[{"delta":{"reasoning_content":"先检查"}}]}'
        yield 'data: {"choices":[{"delta":{"reasoning_content":"再修改","tool_calls":[{"index":0,"id":"call-a","function":{"name":"read","arguments":"{}"}},{"index":1,"id":"call-b","function":{"name":"write","arguments":"{}"}}]}}]}'
        yield "data: [DONE]"

    captured = {}
    monkeypatch.setattr(settings, "deepseek_api_key", "test-only-key")
    monkeypatch.setattr(FakeResponse, "iter_lines", lines)
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client",
                        lambda **kwargs: FakeClient(captured, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="deepseek-thinking-history")
        db.add(task)
        db.flush()
        runtime = DeepSeekRuntime(db)
        first = runtime.call(task.id, ModelRequest("instructions", "input", {}, [], "first"))
        assert first.raw_response["reasoning_content"] == "先检查再修改"
        assert [action.tool_name for action in first.actions] == ["read", "write"]
        history = [{"model_request_id": "first", "reasoning_content": first.raw_response["reasoning_content"],
                    "action": action.__dict__, "result": {"status": "succeeded", "output": {}}}
                   for action in first.actions]
        history.insert(0, {"model_request_id": "legacy", "action": first.actions[0].__dict__,
                           "result": {"status": "succeeded", "output": {}}})
        runtime.call(task.id, ModelRequest("instructions", "input", {"tool_history": [],
                                                     "reasoning_tool_history": history}, [], "second"))

    messages = captured["json"]["messages"]
    assert len(messages) == 5
    assert messages[2]["reasoning_content"] == "先检查再修改"
    assert [item["id"] for item in messages[2]["tool_calls"]] == ["call-a", "call-b"]
    assert [item["tool_call_id"] for item in messages[3:]] == ["call-a", "call-b"]
    assert "reasoning_tool_history" not in messages[1]["content"]


def test_deepseek_thinking_history_keeps_assistant_turn_without_tool():
    # 无工具响应被要求继续时，下一次带工具请求仍需保留该轮思考。
    history = [{"reasoning_content": "还需要提交", "assistant_content": "先自测",
                "result": {"status": "succeeded"}}]
    request = ModelRequest("instructions", "input", {"reasoning_tool_history": history}, [], "retry")
    messages = build_messages(request, include_reasoning=True)
    assert messages[2] == {"role": "assistant", "content": "先自测", "reasoning_content": "还需要提交"}


def test_interrupted_stream_keeps_partial_response_without_events(monkeypatch):
    import httpx
    import pytest

    def interrupted_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
        yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"write","arguments":"{"}}]}}]}'
        raise httpx.ReadError("interrupted")

    monkeypatch.setattr(settings, "deepseek_api_key", "test-only-key")
    monkeypatch.setattr(FakeResponse, "iter_lines", interrupted_lines)
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client", lambda **kwargs: FakeClient({}, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="interrupted")
        db.add(task)
        db.flush()
        with pytest.raises(httpx.ReadError) as failure:
            DeepSeekRuntime(db).call(task.id, ModelRequest("instructions", "input", {}, [], "partial"))
        assert failure.value.response_body["text"] == "partial"
        assert failure.value.response_body["tool_calls"][0]["function"]["arguments"] == "{"
        assert "stream_events" not in failure.value.response_body


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


def test_openrouter_request_and_tool_call_mapping(monkeypatch):
    captured = {}
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7890")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-only-openrouter-key")
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client",
                        lambda **kwargs: FakeClient(captured, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="openrouter-model-contract")
        db.add(task)
        db.flush()
        tools = [{"type": "function", "function": {"name": "write", "parameters": {"type": "object"}}}]
        request = ModelRequest("instructions", "input", {"state": "test"}, tools, "request-openrouter")
        result = OpenRouterRuntime(db).call(task.id, request)

        assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert captured["client_options"] == {"trust_env": True, "timeout": 60,
                                              "proxy": "http://127.0.0.1:7890"}
        assert captured["headers"] == {"Authorization": "Bearer test-only-openrouter-key"}
        assert captured["json"]["model"] == "openai/gpt-6-luna"
        assert captured["json"]["reasoning"] == {"effort": "medium"}
        assert captured["json"]["stream_options"] == {"include_usage": True}
        assert "thinking" not in captured["json"]
        assert captured["json"]["tools"] == tools
        assert result.actions[0].tool_name == "write"


def test_openrouter_without_https_proxy_ignores_unrelated_socks_proxy(monkeypatch):
    captured = {}
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7890")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-only-openrouter-key")
    monkeypatch.setattr("backend.app.runtime.model.httpx.Client",
                        lambda **kwargs: FakeClient(captured, **kwargs))
    with SessionLocal() as db:
        task = Task(task_name="openrouter-no-https-proxy")
        db.add(task)
        db.flush()
        OpenRouterRuntime(db).call(task.id, ModelRequest("instructions", "input", {}, [], "request-no-proxy"))
    assert captured["client_options"] == {"trust_env": False, "timeout": 60}


def test_openrouter_key_can_be_loaded_from_ignored_file(tmp_path, monkeypatch):
    key_file = tmp_path / "openrouter_api_key"
    key_file.write_text("test-openrouter-file-key\n", encoding="utf-8")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key_file", key_file)
    assert get_openrouter_api_key() == "test-openrouter-file-key"


def test_openrouter_missing_key_fails_before_http(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key_file", tmp_path / "missing-key")
    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="SIMULATOR_OPENROUTER_API_KEY_FILE"):
            OpenRouterRuntime(db).call(1, ModelRequest("instructions", "input", {}, [], "request-no-key"))


def test_model_provider_can_select_kimi(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "kimi")
    with SessionLocal() as db:
        runtime = create_model_runtime(db)
        assert isinstance(runtime, KimiRuntime)
        assert runtime.provider == "kimi"


def test_model_provider_can_select_openrouter(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "openrouter")
    with SessionLocal() as db:
        runtime = create_model_runtime(db)
        assert isinstance(runtime, OpenRouterRuntime)
        assert runtime.provider == "openrouter"


def test_document_steps_use_kimi_and_execution_steps_use_deepseek(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "openrouter")
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
        "reasoning_content": "先读取历史文件，再根据结果继续。",
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
