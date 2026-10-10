import json
import os
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from ..config import get_deepseek_api_key, get_kimi_api_key, get_openrouter_api_key, settings
from ..models import Message, Step, Task
from .repair_runtime import reserve_request, finish_request
from .contracts import ModelRequest, ModelResult, ToolCall


class ModelProtocolError(RuntimeError):
    def __init__(self, code: str, response_body: dict):
        # 保存响应协议错误代码和原始响应。
        super().__init__(code)
        self.code = code
        self.response_body = response_body


def build_messages(request: ModelRequest, include_reasoning: bool = False) -> list[dict]:
    # 把指令、输入和工具历史组装成模型消息。
    context = dict(request.context)
    # 工具历史单独转换为 assistant/tool 消息，保持调用 ID 配对。
    tool_history = context.pop("tool_history", [])
    reasoning_history = context.pop("reasoning_tool_history", None)
    if include_reasoning and reasoning_history is not None:
        tool_history = reasoning_history
    if include_reasoning:
        # 当前会话原样续传完整思考；只去掉已由协议工具消息提供的重复结果正文。
        tool_history = [entry for entry in tool_history if "reasoning_content" in entry]
    if tool_history:
        # 通用工具历史已携带真实结果时只引用，避免其他供应商收到重复正文。
        results = {entry["action"]["call_id"]: entry["result"] for entry in tool_history
                   if entry.get("action") and entry.get("result")}
        context["current_requested_data"] = [
            {"call_id": item["call_id"], "tool_name": item.get("tool_name"), "content_source": "tool_message"}
            if item.get("call_id") in results and item == results[item["call_id"]] else item
            for item in context.get("current_requested_data", [])]
    # 完整自测结果已在实际协议消息中时只引用，仍提供真实状态与版本适用性。
    self_test = context.get("unit_self_test")
    if isinstance(self_test, dict):
        for entry in reversed(tool_history):
            action, result = entry.get("action", {}), entry.get("result", {})
            output = result.get("output", {})
            if (action.get("tool_name") == "run_unit_tests" and result.get("status") == "succeeded"
                    and self_test.get("result") is not None and self_test["result"] == output.get("result")
                    and self_test.get("file_hashes_after") == output.get("file_hashes_after")
                    and self_test.get("passed") == output.get("passed")):
                context["unit_self_test"] = {key: value for key, value in self_test.items() if key != "result"} | {
                    "result_ref": {"call_id": action["call_id"], "content_source": "tool_message"}}
                break
    facts = context.get("current_task_facts")
    if isinstance(facts, dict) and facts.get("contract") == "v2":
        evidence = facts.get("self_test", {}).get("evidence")
        ref = evidence.get("result_ref", {}) if isinstance(evidence, dict) else {}
        for entry in tool_history:
            action, result = entry.get("action", {}), entry.get("result", {})
            output = result.get("output", {})
            if (action.get("tool_name") == "run_unit_tests" and result.get("status") == "succeeded"
                    and ref.get("model_call_id") and ref.get("tool_call_id")
                    and entry.get("model_request_id") == ref["model_call_id"]
                    and action.get("call_id") == ref["tool_call_id"]
                    and all(evidence.get(key) == output.get(key) for key in (
                        "command", "file_hashes_before", "file_hashes_after", "passed", "result", "failure_details"))):
                # 身份和正文均一致才引用实际工具消息；接力没有该消息时保留完整事实。
                result_ref = {**ref, "content_source": "tool_message"}
                compact = {key: value for key, value in evidence.items() if key not in {"result", "failure_details"}}
                compact["result_ref"] = result_ref
                context["current_task_facts"] = {**facts, "self_test": {**facts["self_test"], "evidence": compact}}
                # 只收敛同一次自测的重复失败，不隐藏其他工具故障或未知旧摘要。
                context["tool_failures"] = [
                    {**{key: value for key, value in item.items() if key != "error_excerpt"},
                     "error_ref": result_ref}
                    if item.get("tool_name") == "run_unit_tests"
                    and item.get("parent_model_call_id") == ref["model_call_id"]
                    and item.get("tool_call_id") == ref["tool_call_id"] else item
                    for item in context.get("tool_failures", [])]
                break
    messages = [
        {"role": "system", "content": request.instructions},
        {"role": "user", "content": json.dumps({"input": request.input, "context": context}, ensure_ascii=False)},
    ]
    index = 0
    while index < len(tool_history):
        entry = tool_history[index]
        action = entry.get("action")
        result = entry.get("result")
        if not action and "assistant_content" in entry:
            # 普通助手响应也保留执行意图；思考字段仅按供应商协议追加。
            assistant = {"role": "assistant", "content": entry["assistant_content"]}
            if include_reasoning:
                assistant['reasoning_content'] = entry['reasoning_content']
            messages.append(assistant)
            index += 1
            continue
        if not action or not result:
            index += 1
            continue
        group = [entry]
        if entry.get("model_request_id"):
            # 同一响应的多个工具调用属于一条 assistant 消息，随后逐项追加工具结果。
            while index + len(group) < len(tool_history):
                following = tool_history[index + len(group)]
                if (following.get("model_request_id") != entry["model_request_id"]
                        or not following.get("action") or not following.get("result")):
                    break
                group.append(following)
        assistant = {
            "role": "assistant",
            "content": entry.get("assistant_content"),
            "tool_calls": [{"id": item["action"]["call_id"], "type": "function",
                            "function": {"name": item["action"]["tool_name"],
                                         "arguments": json.dumps(item["action"]["parameters"], ensure_ascii=False)}}
                           for item in group],
        }
        if include_reasoning:
            assistant["reasoning_content"] = entry["reasoning_content"]
        messages.append(assistant)
        for item in group:
            messages.append({"role": "tool", "tool_call_id": item["action"]["call_id"],
                             "content": json.dumps(item["result"], ensure_ascii=False)})
        index += len(group)
    return messages


class ChatCompletionsRuntime:
    provider: str
    timeout: float = 60
    trust_env: bool = False

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

    @property
    def proxy_url(self) -> str | None:
        # 默认 Provider 不使用进程环境中的代理。
        return None

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
        reasoning_parts = []
        tools_by_index: dict[int, dict] = {}
        metadata = {}
        task = self.db.get(Task, task_id)
        budget_root = Path(task.workspace_path) if task and task.workspace_path else None
        attempt = None

        def merged_response() -> dict:
            # 汇总文本、完整工具参数和响应元信息，不保留原始分片。
            return {**metadata, "text": "".join(text_parts), "reasoning_content": "".join(reasoning_parts),
                    "tool_calls": [tools_by_index[index] for index in sorted(tools_by_index)]}

        try:
            proxy_url = self.proxy_url
            client_options = {"trust_env": self.trust_env if proxy_url else False, "timeout": self.timeout}
            # 仅给声明了 HTTPS 代理的 Provider 传入显式代理地址。
            if proxy_url:
                client_options["proxy"] = proxy_url
            with httpx.Client(**client_options) as client:
                # 每次实际发送（含重试）先登记任务预算，旧任务没有新状态时保持原行为。
                if budget_root:
                    attempt = reserve_request(budget_root, self.provider, request.request_id)
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
                        # 思考内容只供 DeepSeek 工具轮次续传，不作为面向用户的实时文本发布。
                        reasoning = delta.get("reasoning_content") or ""
                        if reasoning:
                            reasoning_parts.append(reasoning)
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
            if budget_root:
                finish_request(budget_root, attempt, "failed", metadata.get("usage"))
            exc.response_body = merged_response()
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            # 无法解析的流归入协议错误，保存已合并内容而不保存原始事件。
            if budget_root:
                finish_request(budget_root, attempt, "failed", metadata.get("usage"))
            raise ModelProtocolError("invalid_stream_response", merged_response()) from exc
        merged = merged_response()
        if budget_root:
            finish_request(budget_root, attempt, "responded", metadata.get("usage"))
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
            "messages": build_messages(request, include_reasoning=True),
            "tools": request.tools or None,
            "stream": True,
            "stream_options": {"include_usage": True},
            "thinking": {"type": "enabled"},
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


class OpenRouterRuntime(ChatCompletionsRuntime):
    provider = "openrouter"
    # 仅 OpenRouter 从当前进程环境读取代理配置。
    trust_env = True

    @property
    def proxy_url(self) -> str | None:
        # 优先使用进程已配置的 HTTPS 代理，避免无关 SOCKS 环境变量影响客户端初始化。
        return os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")

    @property
    def model_name(self) -> str:
        # 返回配置的 OpenRouter 模型 ID。
        return settings.openrouter_model

    @property
    def base_url(self) -> str:
        # 返回 OpenRouter 的 API 地址。
        return settings.openrouter_base_url

    def get_api_key(self) -> str:
        # 从受控配置读取 OpenRouter 密钥。
        return get_openrouter_api_key()

    def build_payload(self, request: ModelRequest) -> dict:
        # 构造 Luna medium 的流式请求，并请求返回真实用量。
        payload = {
            "model": self.model_name,
            "messages": build_messages(request),
            "stream": True,
            "stream_options": {"include_usage": True},
            "reasoning": {"effort": "medium"},
        }
        # 只有提供工具定义时才发送 tools，避免把空值当成工具列表。
        if request.tools:
            payload["tools"] = request.tools
        return payload


KIMI_STEPS = {Step.product_docs, Step.architecture_docs, Step.dev_design}


def create_model_runtime(db: Session, step: Step | None = None) -> ChatCompletionsRuntime:
    # 根据阶段或配置选择对应的模型运行时。
    runtimes = {"deepseek": DeepSeekRuntime, "kimi": KimiRuntime, "openrouter": OpenRouterRuntime}
    # 按固定阶段路由模型，未指定阶段时使用全局配置。
    provider = "kimi" if step in KIMI_STEPS else "deepseek" if step is not None else settings.model_provider.lower()
    runtime_class = runtimes.get(provider)
    if runtime_class is None:
        supported = ", ".join(runtimes)
        raise RuntimeError(f"Unsupported model provider: {settings.model_provider}; expected one of {supported}")
    return runtime_class(db)
