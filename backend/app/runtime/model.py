import json

import httpx
from sqlalchemy.orm import Session

from ..config import get_deepseek_api_key, get_kimi_api_key, settings
from ..models import Message, Step
from .contracts import ModelRequest, ModelResult, ToolCall


class ModelProtocolError(RuntimeError):
    def __init__(self, code: str, response_body: dict):
        # 保存响应协议错误代码和原始响应。
        super().__init__(code)
        self.code = code
        self.response_body = response_body


def build_messages(request: ModelRequest) -> list[dict]:
    # 把指令、输入和工具历史组装成模型消息。
    context = dict(request.context)
    # 工具历史单独转换为 assistant/tool 消息，保持调用 ID 配对。
    tool_history = context.pop("tool_history", [])
    messages = [
        {"role": "system", "content": request.instructions},
        {"role": "user", "content": json.dumps({"input": request.input, "context": context}, ensure_ascii=False)},
    ]
    for entry in tool_history:
        action = entry.get("action")
        result = entry.get("result")
        if not action or not result:
            continue
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": action["call_id"],
                "type": "function",
                "function": {"name": action["tool_name"],
                             "arguments": json.dumps(action["parameters"], ensure_ascii=False)},
            }],
        })
        messages.append({"role": "tool", "tool_call_id": action["call_id"],
                         "content": json.dumps(result, ensure_ascii=False)})
    return messages


class ChatCompletionsRuntime:
    provider: str
    timeout: float = 60

    def __init__(self, db: Session):
        # 保存供模型消息写入使用的数据库会话。
        self.db = db

    @property
    def model_name(self) -> str:
        # 声明子类需要提供模型 ID。
        raise NotImplementedError

    @property
    def base_url(self) -> str:
        # 声明子类需要提供 API 地址。
        raise NotImplementedError

    def get_api_key(self) -> str:
        # 声明子类需要提供受控 API 密钥。
        raise NotImplementedError

    def build_payload(self, request: ModelRequest) -> dict:
        # 声明子类需要构造 Provider 请求体。
        raise NotImplementedError

    def _finish(self, task_id: int, request: ModelRequest, text: str,
                raw_tool_calls: list[dict], raw_response: dict) -> ModelResult:
        # 保存模型消息并解析工具调用结果。
        message = Message(task_id=task_id, role="assistant", content=text)
        self.db.add(message)
        # 先持久化模型消息，再以其 ID 关联本次模型结果。
        self.db.flush()
        try:
            # 严格解析模型提供的工具参数；非法 JSON 作为协议错误处理。
            actions = [ToolCall(call_id=item["id"], tool_name=item["function"]["name"],
                                parameters=json.loads(item["function"]["arguments"]))
                       for item in raw_tool_calls]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ModelProtocolError("invalid_tool_call", raw_response) from exc
        return ModelResult(request.request_id, message.id, text, actions,
                           "tool_calls" if actions else "completed", raw_response)

    def call(self, task_id: int, request: ModelRequest) -> ModelResult:
        # 流式调用 Chat Completions 并合并文本和工具参数。
        api_key = self.get_api_key()
        if not api_key:
            raise RuntimeError(
                f"{self.provider} API key is not configured; "
                f"set SIMULATOR_{self.provider.upper()}_API_KEY_FILE"
            )
        payload = self.build_payload(request)
        # 流式传输仅用于实时展示，审计保存合并响应。
        payload["stream"] = True
        text_parts = []
        tools_by_index: dict[int, dict] = {}
        metadata = {}

        def merged_response() -> dict:
            # 汇总文本、完整工具参数和响应元信息，不保留原始分片。
            return {**metadata, "text": "".join(text_parts),
                    "tool_calls": [tools_by_index[index] for index in sorted(tools_by_index)]}

        try:
            with httpx.Client(trust_env=False, timeout=self.timeout) as client:
                # 认证头只用于传输，不进入审计响应。
                with client.stream("POST", f"{self.base_url.rstrip('/')}/chat/completions",
                                   headers={"Authorization": f"Bearer {api_key}"}, json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        event = json.loads(data)
                        for key in ("id", "model", "created", "usage", "system_fingerprint"):
                            if key in event and event[key] is not None:
                                metadata[key] = event[key]
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        if isinstance(choice.get("usage"), dict):
                            metadata["usage"] = choice["usage"]
                        if choice.get("finish_reason"):
                            metadata["finish_reason"] = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        content = delta.get("content") or ""
                        if content:
                            text_parts.append(content)
                            if request.on_delta:
                                request.on_delta(content)
                        # 工具参数按调用索引拼接，保留最终原始参数字符串供协议排查。
                        for item in delta.get("tool_calls") or []:
                            index = item.get("index", 0)
                            target = tools_by_index.setdefault(index, {"id": "", "function": {"name": "", "arguments": ""}})
                            target["id"] += item.get("id") or ""
                            function = item.get("function") or {}
                            target["function"]["name"] += function.get("name") or ""
                            target["function"]["arguments"] += function.get("arguments") or ""
        except httpx.HTTPError as exc:
            # 传输中断仍携带部分文本和工具参数，由 Worker 归档一次。
            exc.response_body = merged_response()
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            # 无法解析的流归入协议错误，保存已合并内容而不保存原始事件。
            raise ModelProtocolError("invalid_stream_response", merged_response()) from exc
        merged = merged_response()
        return self._finish(task_id, request, merged["text"], merged["tool_calls"], merged)


class DeepSeekRuntime(ChatCompletionsRuntime):
    provider = "deepseek"

    @property
    def model_name(self) -> str:
        # 返回配置的 DeepSeek 模型 ID。
        return settings.deepseek_model

    @property
    def base_url(self) -> str:
        # 返回配置的 DeepSeek API 地址。
        return settings.deepseek_base_url

    def get_api_key(self) -> str:
        # 读取 DeepSeek 受控密钥。
        return get_deepseek_api_key()

    def build_payload(self, request: ModelRequest) -> dict:
        # 构造 DeepSeek Chat Completions 请求体。
        return {
            "model": self.model_name,
            "messages": build_messages(request),
            "tools": request.tools or None,
            "stream": True,
            "stream_options": {"include_usage": True},
            "thinking": {"type": "disabled"},
        }


class KimiRuntime(ChatCompletionsRuntime):
    provider = "kimi"
    timeout = 180

    @property
    def model_name(self) -> str:
        # 返回配置的 Kimi 模型 ID。
        return settings.kimi_model

    @property
    def base_url(self) -> str:
        # 返回配置的 Kimi API 地址。
        return settings.kimi_base_url

    def get_api_key(self) -> str:
        # 读取 Kimi 受控密钥。
        return get_kimi_api_key()

    def build_payload(self, request: ModelRequest) -> dict:
        # 构造带输出上限的 Kimi 请求体。
        return {
            "model": self.model_name,
            "messages": build_messages(request),
            "tools": request.tools or None,
            "stream": True,
            "thinking": {"type": "disabled"},
            "max_completion_tokens": settings.kimi_max_completion_tokens,
        }


KIMI_STEPS = {Step.product_docs, Step.architecture_docs, Step.dev_design}


def create_model_runtime(db: Session, step: Step | None = None) -> ChatCompletionsRuntime:
    # 根据阶段或配置选择对应的模型运行时。
    runtimes = {"deepseek": DeepSeekRuntime, "kimi": KimiRuntime}
    # 按固定阶段路由模型，未指定阶段时使用全局配置。
    provider = "kimi" if step in KIMI_STEPS else "deepseek" if step is not None else settings.model_provider.lower()
    runtime_class = runtimes.get(provider)
    if runtime_class is None:
        supported = ", ".join(runtimes)
        raise RuntimeError(f"Unsupported model provider: {settings.model_provider}; expected one of {supported}")
    return runtime_class(db)
