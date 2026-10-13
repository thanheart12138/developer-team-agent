"""验证渠道优先级、Responses 工具历史、回退和实际请求预算。"""

import json
import plistlib

import httpx
import pytest

from backend.app.config import settings
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Task
from backend.app.runtime.contracts import ModelRequest
from backend.app.runtime.model import DeepSeekRuntime, KimiRuntime, OpenRouterRuntime
from backend.app.runtime.opencode import OpenCodeRuntime, get_api_key
from backend.app.runtime.repair_runtime import BudgetExceeded, load, save
from tests.test_prompt_management import prompt_store


@pytest.fixture(autouse=True)
def enable_opencode(monkeypatch, tmp_path):
    """使用内存库和临时假凭据，无真实调用。"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    key = tmp_path / 'opencode_api_key'
    key.write_text('fixture-key')
    monkeypatch.setattr(settings, 'opencode_api_key_file', key)
    monkeypatch.setattr(settings, 'opencode_enabled', True)
    monkeypatch.setattr('backend.app.runtime.opencode.time.sleep', lambda duration: None)


def client_factory(monkeypatch, handler):
    """保留真实 HTTPX 协议接口，仅替换网络传输。"""
    client = httpx.Client
    monkeypatch.setattr('backend.app.runtime.model.httpx.Client',
                        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))


def chat_response():
    """返回带用量和完整终止标记的工具响应。"""
    event = {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call-1',
             'function': {'name': 'read', 'arguments': '{"path":"a"}'}}]}, 'finish_reason': 'tool_calls'}],
             'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}}
    return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n')


@pytest.mark.parametrize('runtime_class,model', [(DeepSeekRuntime, 'deepseek-v4.1-flash'),
                                                (KimiRuntime, 'kimi-k2.7-code')])
def test_chat_priority_and_stable_session(monkeypatch, runtime_class, model):
    """不同逻辑请求仍复用同会话头，实际使用 Go 模型和工具定义。"""
    requests = []
    def handler(request):
        """收集实际发送字段。"""
        requests.append(request)
        return chat_response()
    client_factory(monkeypatch, handler)
    with SessionLocal() as db:
        task = Task(task_name='priority')
        db.add(task)
        db.flush()
        runtime = runtime_class(db)
        for request_id in ('first', 'next'):
            result = runtime.call(task.id, ModelRequest('system', 'input', {}, [], request_id,
                                                       conversation_id='same-session'))
            assert result.raw_response['transport_provider'] == 'opencode'
            assert result.actions[0].call_id == 'call-1'
        assert requests[0].headers['x-opencode-session'] == requests[1].headers['x-opencode-session']
        assert requests[0].headers['user-agent'] == 'ai-agent-product/1.0'
        assert requests[0].headers['authorization'] == 'Bearer fixture-key'
        payload = json.loads(requests[0].content)
        assert payload['model'] == model
        assert 'thinking' not in payload
        assert requests[0].url == 'https://opencode.ai/inference/go/v1/chat/completions'


def test_luna_responses_history_and_tool_mapping(monkeypatch):
    """Responses 使用 call_id 配对，不丢失助手意图及工具结果。"""
    captured = []
    def handler(request):
        """返回函数调用与真实 Responses 用量格式。"""
        captured.append(request)
        return httpx.Response(200, json={'object': 'response', 'status': 'completed',
            'output': [{'type': 'reasoning'}, {'type': 'function_call', 'call_id': 'next-call',
                        'name': 'read', 'arguments': '{"path":"b"}'}],
            'usage': {'input_tokens': 20, 'output_tokens': 4, 'total_tokens': 24}})
    client_factory(monkeypatch, handler)
    history = [{'model_request_id': 'old', 'assistant_content': 'check file',
                'action': {'call_id': 'old-call', 'tool_name': 'read', 'parameters': {'path': 'a'}},
                'result': {'status': 'succeeded', 'output': 'contents'}}]
    with SessionLocal() as db:
        task = Task(task_name='luna')
        db.add(task)
        db.flush()
        result = OpenRouterRuntime(db).call(task.id, ModelRequest('system', 'input', {'tool_history': history},
            [{'type': 'function', 'function': {'name': 'read', 'parameters': {'type': 'object'}}}], 'request'))
        payload = json.loads(captured[0].content)
        assert captured[0].url.path.endswith('/responses')
        assert payload['stream'] is False
        assert payload['tools'][0]['name'] == 'read'
        assert payload['input'][-2]['call_id'] == payload['input'][-1]['call_id'] == 'old-call'
        assert payload['input'][-3]['content'] == 'check file'
        assert result.actions[0].call_id == 'next-call'
        assert result.raw_response['usage']['total_tokens'] == 24


@pytest.mark.parametrize('status,expected', [(401, 1), (429, 3), (503, 3)])
def test_technical_fallback(monkeypatch, status, expected):
    """暂态错误最多三次，认证错误立即回退，实际失败证据保持。"""
    requests, events = [], []
    def handler(request):
        """OpenCode 失败而原渠道成功。"""
        requests.append(request)
        return httpx.Response(status) if request.url.host == 'opencode.ai' else chat_response()
    client_factory(monkeypatch, handler)
    monkeypatch.setattr(settings, 'deepseek_api_key', 'original-key')
    with SessionLocal() as db:
        task = Task(task_name='fallback')
        db.add(task)
        db.flush()
        result = DeepSeekRuntime(db).call(task.id, ModelRequest('system', 'input', {}, [], 'request',
                                                               on_transport=events.append))
        assert len(requests) == expected + 1
        assert requests[-1].url.host == 'api.deepseek.com'
        assert result.raw_response['transport_provider'] == 'deepseek'
        assert len(result.raw_response['channel_attempts']) == expected + 1
        assert any(event['status'] == 'fallback' for event in events)


def test_budget_exhaustion_never_falls_back(monkeypatch, tmp_path):
    """OpenCode 重试耗尽任务预算后禁止原渠道发送。"""
    import hashlib
    approval = tmp_path / 'approval.json'
    approval.write_text('{}')
    save(tmp_path, {'workflow': 'repair-v1', 'revision': 0, 'state': 'executing',
        'validation_policy': 'tests_and_browser', 'authorization_ref': 'approval.json',
        'authorization_hash': hashlib.sha256(approval.read_bytes()).hexdigest(),
        'budget': {'provider': 'deepseek', 'total_limit': 1, 'review_reserve': 0,
                   'attempts_used': 0, 'requests': []}})
    requests = []
    def handler(request):
        """首个 HTTP 暂态失败。"""
        requests.append(request)
        return httpx.Response(503)
    client_factory(monkeypatch, handler)
    with SessionLocal() as db:
        task = Task(task_name='budget', workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        with pytest.raises(BudgetExceeded):
            DeepSeekRuntime(db).call(task.id, ModelRequest('system', 'input', {}, [], 'request'))
        assert len(requests) == 1
        assert load(tmp_path)['budget']['attempts_used'] == 1


def test_text_clipping_and_safe_credential_failure(tmp_path, monkeypatch):
    """只解析剪贴文本；非法内容不会出现在异常信息中。"""
    path = tmp_path / 'clip.textClipping'
    path.write_bytes(plistlib.dumps({'UTI-Data': {'public.utf8-plain-text': 'fixture-key'}}))
    monkeypatch.setattr(settings, 'opencode_api_key_file', path)
    assert get_api_key() == 'fixture-key'
    path.write_bytes(b'sensitive-invalid-content')
    with pytest.raises(RuntimeError, match='^opencode_credential_unavailable$'):
        get_api_key()


def test_old_session_and_explicit_original_keep_destination(monkeypatch, tmp_path):
    """旧模型身份与显式固定目的地不自动迁移；新会话走 Go。"""
    from backend.app.runtime.opencode import preferred_runtime
    with SessionLocal() as db:
        task = Task(task_name='old-session', workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        original = DeepSeekRuntime(db)
        request = ModelRequest('system', 'input', {}, [], 'request')
        save(tmp_path, {'workflow': 'repair-v1', 'revision': 0, 'session': {'model': original.model_name}})
        assert preferred_runtime(original, task.id, request) is original
        save(tmp_path, {'workflow': 'repair-v1', 'revision': 0, 'session': {'model': original.model_name, 'channel_policy': 'opencode_first'}})
        assert isinstance(preferred_runtime(original, task.id, request), OpenCodeRuntime)
        request.original_channel_only = True
        assert preferred_runtime(original, task.id, request) is original


def test_truncated_stream_falls_back_without_executing_partial_tool(monkeypatch):
    """缺少 DONE 的工具流被拒绝，只有原渠道完整响应可执行。"""
    requests = []
    def handler(request):
        """返回一个截断工具流。"""
        requests.append(request)
        if request.url.host == 'opencode.ai':
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
        return chat_response()
    client_factory(monkeypatch, handler)
    monkeypatch.setattr(settings, 'deepseek_api_key', 'original-key')
    with SessionLocal() as db:
        task = Task(task_name='truncated')
        db.add(task)
        db.flush()
        result = DeepSeekRuntime(db).call(task.id, ModelRequest('system', 'input', {}, [], 'request'))
        assert len(requests) == 2
        assert result.text == ''
        assert result.raw_response['channel_attempts'][0]['error'] == 'ModelProtocolError'


def test_new_evaluation_requires_fallback_authorization(prompt_store, monkeypatch):
    """新目的地必须精确批准回退，不能借旧批准外发。"""
    from backend.app.runtime.prompt_real_evaluation import RealEvaluation
    from backend.app.runtime.prompt_management import atomic_json
    runtime = RealEvaluation(prompt_store)
    manifest = runtime.prepare('sample', 'v1', 'normal', 2)
    assert manifest['destination'] == 'https://opencode.ai'
    approval = {**{key: manifest[key] for key in ('input_hash', 'http_cap', 'provider', 'destination')},
                'approved': True, 'source': 'fixture'}
    atomic_json(runtime.path(manifest['id']) / 'approval.json', approval)
    with pytest.raises(ValueError, match='real_model_fallback_unconfirmed'):
        runtime.run(manifest['id'])
    approval['fallback_destination'] = manifest['fallback_destination']
    atomic_json(runtime.path(manifest['id']) / 'approval.json', approval)
    monkeypatch.setattr(runtime, 'execute', lambda *args: {'verified': True})
    assert runtime.run(manifest['id']) == {'verified': True}


def test_legacy_evaluation_authorization_survives_new_default(prompt_store, monkeypatch):
    """旧审批按原渠道身份核对，即使默认已启用 OpenCode。"""
    from backend.app.runtime.prompt_real_evaluation import RealEvaluation
    from backend.app.runtime.prompt_management import atomic_json
    runtime = RealEvaluation(prompt_store)
    monkeypatch.setattr(settings, 'opencode_enabled', False)
    manifest = runtime.prepare('sample', 'v1', 'normal', 2)
    atomic_json(runtime.path(manifest['id']) / 'approval.json', {
        **{key: manifest[key] for key in ('input_hash', 'http_cap', 'provider', 'destination')},
        'approved': True, 'source': 'fixture'})
    monkeypatch.setattr(settings, 'opencode_enabled', True)
    monkeypatch.setattr(runtime, 'execute', lambda *args: {'verified': True})
    assert runtime.run(manifest['id']) == {'verified': True}


def test_fallback_charges_same_http_budget(monkeypatch, tmp_path):
    """两个渠道各发送一次，失败和成功都记入原账本。"""
    import hashlib
    approval = tmp_path / 'approval.json'
    approval.write_text('{}')
    save(tmp_path, {'workflow': 'repair-v1', 'revision': 0, 'state': 'executing',
        'validation_policy': 'tests_and_browser', 'authorization_ref': 'approval.json',
        'authorization_hash': hashlib.sha256(approval.read_bytes()).hexdigest(),
        'budget': {'provider': 'deepseek', 'total_limit': 2, 'review_reserve': 0,
                   'attempts_used': 0, 'requests': []}})
    def handler(request):
        """拒绝 Go 认证，原渠道返回完整用量。"""
        return httpx.Response(401) if request.url.host == 'opencode.ai' else chat_response()
    client_factory(monkeypatch, handler)
    monkeypatch.setattr(settings, 'deepseek_api_key', 'original-key')
    with SessionLocal() as db:
        task = Task(task_name='shared-budget', workspace_path=str(tmp_path))
        db.add(task)
        db.flush()
        DeepSeekRuntime(db).call(task.id, ModelRequest('system', 'input', {}, [], 'same-logical-call'))
        budget = load(tmp_path)['budget']
        assert budget['attempts_used'] == 2
        assert [item['status'] for item in budget['requests']] == ['failed', 'responded']
        assert budget['requests'][1]['usage']['total_tokens'] == 12


def test_missing_key_falls_back_without_opencode_http(monkeypatch, tmp_path):
    """凭据不可用不发送 Go 请求，也不展示文件内容。"""
    monkeypatch.setattr(settings, 'opencode_api_key_file', tmp_path / 'missing')
    monkeypatch.setattr(settings, 'deepseek_api_key', 'original-key')
    requests = []
    def handler(request):
        """只允许原渠道发送。"""
        requests.append(request)
        assert request.url.host == 'api.deepseek.com'
        return chat_response()
    client_factory(monkeypatch, handler)
    with SessionLocal() as db:
        task = Task(task_name='missing-key')
        db.add(task)
        db.flush()
        result = DeepSeekRuntime(db).call(task.id, ModelRequest('system', 'input', {}, [], 'request'))
        assert len(requests) == 1
        assert result.raw_response['channel_attempts'][0]['error'] == 'RuntimeError'


def test_worker_retry_does_not_restart_opencode_attempts(monkeypatch):
    """同一逻辑调用外层重试只重试原渠道，下次逻辑调用重新优先 Go。"""
    requests = []
    def handler(request):
        """两渠道均暂态失败，核对实际发送次数。"""
        requests.append(request)
        return httpx.Response(503)
    client_factory(monkeypatch, handler)
    monkeypatch.setattr(settings, 'deepseek_api_key', 'original-key')
    with SessionLocal() as db:
        task = Task(task_name='outer-retry')
        db.add(task)
        db.flush()
        runtime = DeepSeekRuntime(db)
        request = ModelRequest('system', 'input', {}, [], 'same-request')
        for _ in range(2):
            with pytest.raises(httpx.HTTPStatusError):
                runtime.call(task.id, request)
        assert [item.url.host for item in requests] == ['opencode.ai'] * 3 + ['api.deepseek.com'] * 2
        request.request_id = 'next-request'
        with pytest.raises(httpx.HTTPStatusError):
            runtime.call(task.id, request)
        assert len(requests) == 9
