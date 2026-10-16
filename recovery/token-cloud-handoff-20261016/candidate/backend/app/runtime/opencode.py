"""OpenCode 优先渠道、工具协议适配及受预算约束的原渠道回退。"""

import hashlib
import json
import os
import plistlib
import stat
import time
from pathlib import Path

import httpx

from ..config import settings
from ..models import Task
from .model import ChatCompletionsRuntime, ModelProtocolError, build_messages
from .repair_runtime import BudgetExceeded, finish_request, load, reserve_request
from . import token_transport
from .task_budget import TaskBudgetError

BASE_URL = "https://opencode.ai/inference/go/v1"
MODELS = {"deepseek": "deepseek-v4.1-flash", "kimi": "kimi-k2.7-code",
          "openrouter": "gpt-6-luna"}


def get_api_key() -> str:
    """读取受控文本或剪贴文件，失败仅返回固定错误，不暴露凭据内容。"""
    try:
        path = settings.opencode_api_key_file.absolute()
        if not path.exists() and path.suffix != ".textClipping":
            path = path.with_name(path.name + ".textClipping")
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError()
        # 拒绝链接及特殊文件，并将读取量限制为四千字节。
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 4096:
                raise ValueError()
            raw = os.read(fd, 4097)
            if len(raw) != info.st_size:
                raise ValueError()
        finally:
            os.close(fd)
        if path.suffix == ".textClipping":
            raw = plistlib.loads(raw)["UTI-Data"]["public.utf8-plain-text"].encode("ascii")
        raw = raw.strip()
        if not raw or any(value < 33 or value > 126 for value in raw):
            raise ValueError()
        return raw.decode("ascii")
    except Exception:
        raise RuntimeError("opencode_credential_unavailable") from None


def session_id(runtime, task_id: int, request) -> str:
    """任务工作区隔离独立调用；正式会话使用 Worker 提供的稳定身份。"""
    task = runtime.db.get(Task, task_id)
    identity = request.conversation_id or f"task:{task_id}"
    workspace = task.workspace_path if task else ""
    return hashlib.sha256(f"ai-agent-product:{workspace}:{identity}".encode()).hexdigest()


class OpenCodeRuntime(ChatCompletionsRuntime):
    require_stream_done = True

    def __init__(self, original):
        """保留逻辑模型分工和预算身份，传输模型由 OpenCode 映射决定。"""
        super().__init__(original.db)
        self.original = original
        self.provider = original.provider
        self.timeout = original.timeout

    @property
    def model_name(self) -> str:
        """返回 OpenCode 实际模型 ID。"""
        return MODELS[self.provider]

    @property
    def base_url(self) -> str:
        """固定已确认的 Go 端点，不继承其他供应商地址。"""
        return BASE_URL

    def get_api_key(self) -> str:
        """只读取 OpenCode 凭据。"""
        return get_api_key()

    def request_headers(self, task_id: int, request, api_key: str) -> dict:
        """所有请求与重试携带相同会话头，认证不进入审计。"""
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                "User-Agent": "ai-agent-product/1.0",
                "x-opencode-session": session_id(self, task_id, request)}

    def build_payload(self, request) -> dict:
        """构造模型专属字段，并保留已有工具历史与调用 ID。"""
        messages = build_messages(request, include_reasoning=self.provider == "deepseek")
        if self.provider == "openrouter":
            # Responses 的函数调用和工具结果为独立 input 项，不能套用 Chat 消息。
            items = []
            for message in messages:
                if message["role"] == "tool":
                    items.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                                  "output": message["content"]})
                else:
                    if message.get("content"):
                        items.append({"role": message["role"], "content": message["content"]})
                    for call in message.get("tool_calls", []):
                        items.append({"type": "function_call", "call_id": call["id"],
                                      "name": call["function"]["name"],
                                      "arguments": call["function"]["arguments"]})
            payload = {"model": self.model_name, "input": items, "stream": False,
                       "max_output_tokens": 32768, "reasoning": {"effort": "medium"}}
            if request.tools:
                payload["tools"] = [{"type": "function", **tool["function"]} for tool in request.tools]
            return payload
        payload = {"model": self.model_name, "messages": messages, "stream": True,
                   "max_tokens": settings.kimi_max_completion_tokens if self.provider == "kimi" else 32768,
                   "stream_options": {"include_usage": True}}
        if self.provider == "deepseek":
            # 使用项目强度配置，不以渠道切换恢复原硬编码high。
            payload["reasoning_effort"] = settings.deepseek_reasoning_effort
        if request.tools:
            payload["tools"] = request.tools
        return payload

    def _call_direct(self, task_id: int, request):
        """Chat 复用流式传输；Responses 单次调用也受同一实际 HTTP 预算约束。"""
        if request.controlled_transport is not None:
            from .controlled_transport import call_direct
            return call_direct(self, task_id, request)
        if self.provider != "openrouter":
            return super()._call_direct(task_id, request)
        api_key = self.get_api_key()
        task = self.db.get(Task, task_id)
        root = Path(task.workspace_path) if task and task.workspace_path else None
        attempt, raw, usage = None, {}, None
        token_attempt = None
        payload = token_transport.prepare(root, self.build_payload(request))
        try:
            with httpx.Client(trust_env=False, timeout=self.timeout) as client:
                # 每次真实发送先预约，额度不足不会触发原渠道回退。
                if root:
                    attempt = reserve_request(root, self.provider, request.request_id)
                # Responses与Chat使用同一任务Token账，每个实际尝试独立预约。
                token_attempt = token_transport.reserve(root, self.provider, request.request_id, payload,
                                                        expected_budget_id=request.required_token_budget_id)
                response = client.post(f"{BASE_URL}/responses", json=payload,
                                       headers=self.request_headers(task_id, request, api_key))
                response.raise_for_status()
                raw = response.json()
            source = raw.get("usage")
            if isinstance(source, dict):
                counts = [source.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")]
                if any(type(count) is not int or count < 0 for count in counts) or counts[2] != sum(counts[:2]):
                    raise ValueError("invalid_responses_usage")
                usage = {"prompt_tokens": source.get("input_tokens"),
                         "completion_tokens": source.get("output_tokens"),
                         "total_tokens": source.get("total_tokens"),
                         "prompt_tokens_details": source.get("input_tokens_details", {}),
                         "completion_tokens_details": source.get("output_tokens_details", {})}
            if raw.get("object") != "response" or raw.get("status") != "completed" or raw.get("error"):
                raise ValueError("invalid_responses_status")
            if not isinstance(raw.get("output"), list) or not raw["output"]:
                raise ValueError("invalid_responses_output")
            text, calls = [], []
            for item in raw["output"]:
                if item["type"] == "message":
                    for part in item["content"]:
                        if part["type"] == "output_text":
                            text.append(part["text"])
                        elif part["type"] == "refusal":
                            text.append(part["refusal"])
                        else:
                            raise ValueError("invalid_responses_content")
                elif item["type"] == "function_call":
                    calls.append({"id": item["call_id"], "function": {
                        "name": item["name"], "arguments": item["arguments"]}})
                elif item["type"] != "reasoning":
                    raise ValueError("invalid_responses_output")
            merged = {"text": "".join(text), "tool_calls": calls, "usage": usage,
                      "model": raw.get("model", self.model_name), "original_response": raw}
            result = self._finish(task_id, request, merged["text"], calls, merged)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, ModelProtocolError) as exc:
            token_transport.settle(root, token_attempt, "failed", usage)
            if root and attempt is not None:
                finish_request(root, attempt, "failed", usage)
            if isinstance(exc, httpx.HTTPError):
                exc.response_body = raw
                raise
            raise ModelProtocolError("invalid_responses_response", raw) from exc
        token_transport.settle(root, token_attempt, "responded", usage)
        if root:
            finish_request(root, attempt, "responded", usage)
        if request.on_delta and merged["text"]:
            request.on_delta(merged["text"])
        return result


def preferred_runtime(original, task_id: int, request):
    """旧固定身份会话沿用原渠道，新请求按已确认优先级选择。"""
    if (not settings.opencode_enabled or request.original_channel_only
            or getattr(original, '_opencode_failed_request_id', None) == request.request_id):
        return original
    task = original.db.get(Task, task_id)
    state = load(Path(task.workspace_path)) if task and task.workspace_path else None
    if state and state.get("session") and state["session"].get("channel_policy") != "opencode_first":
        return original
    return OpenCodeRuntime(original)


def call_preferred(original, task_id: int, request):
    """有界重试 OpenCode 技术失败，再使用原渠道；业务结果不触发回退。"""
    if request.controlled_transport is not None:
        from .controlled_transport import call_selected
        return call_selected(original, task_id, request)
    # 实验请求在选择渠道或读取认证前强制绑定既有预算身份。
    if request.required_token_budget_id is not None:
        task = original.db.get(Task, task_id)
        token_transport.require_bound(Path(task.workspace_path) if task and task.workspace_path else None,
                                      request.required_token_budget_id)
    selected = preferred_runtime(original, task_id, request)
    task = original.db.get(Task, task_id)
    token_root = Path(task.workspace_path) if task and task.workspace_path else None
    attempts = []
    for index in range(1, 4 if selected is not original else 2):
        event = {"provider": "opencode" if selected is not original else original.provider,
                 "model": selected.model_name, "attempt": index, "request_id": request.request_id,
                 "payload": token_transport.prepare(token_root, selected.build_payload(request))}
        # 在 HTTP 前记录实际渠道请求，头部和凭据不进入回调。
        if request.on_transport:
            request.on_transport({**event, "status": "request"})
        try:
            result = selected._call_direct(task_id, request)
            event.pop("payload")
            attempts.append({**event, "status": "responded"})
            result.raw_response.update(transport_provider=event["provider"], transport_model=event["model"],
                                       channel_attempts=attempts)
            return result
        except (BudgetExceeded, TaskBudgetError):
            raise
        except (httpx.HTTPError, ModelProtocolError, RuntimeError) as exc:
            event.pop("payload")
            failure = {**event, "status": "failed", "error": type(exc).__name__,
                       "partial_response": getattr(exc, "response_body", {})}
            attempts.append(failure)
            if request.on_transport:
                request.on_transport(failure)
            if selected is original:
                raise
            # 只有可重试的传输失败退避，协议、配置及非暂态 HTTP 错误立即回退。
            retryable = isinstance(exc, httpx.TransportError) or (
                isinstance(exc, httpx.HTTPStatusError) and
                (exc.response.status_code == 429 or exc.response.status_code >= 500))
            if retryable and index < 3:
                time.sleep(0.5 * 2 ** (index - 1))
                continue
            break
    # Worker 重试同一逻辑请求时继续原渠道，不重新获得三次 Go 尝试额度。
    original._opencode_failed_request_id = request.request_id
    if request.on_transport:
        request.on_transport({"status": "fallback", "provider": original.provider,
                              "model": original.model_name, "request_id": request.request_id})
        request.on_transport({"status": "request", "provider": original.provider,
                              "model": original.model_name, "request_id": request.request_id,
                              "payload": token_transport.prepare(token_root, original.build_payload(request))})
    try:
        result = original._call_direct(task_id, request)
    except (httpx.HTTPError, ModelProtocolError, RuntimeError) as exc:
        # 两渠道都失败时将 OpenCode 原失败证据交给 Worker，不能静默丢失。
        exc.response_body = {"channel_attempts": attempts, "original_channel_response": getattr(exc, "response_body", {})}
        raise
    result.raw_response.update(transport_provider=original.provider, transport_model=original.model_name,
                               channel_attempts=attempts + [{"provider": original.provider,
                                   "model": original.model_name, "status": "responded"}])
    return result
