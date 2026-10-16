"""真实入口授权与恢复门禁，使用协议夹具，不发送HTTP。"""
from types import SimpleNamespace

import pytest

from tests.test_prompt_management import prompt_store
from backend.app.runtime import repair_runtime as repair
from backend.app.runtime.prompt_management import PromptStore, atomic_json
from backend.app.runtime.prompt_real_evaluation import RealEvaluation


def authorize(runtime, manifest):
    """在隔离夹具写入精确批准字段，不代表真实外发授权。"""
    atomic_json(runtime.path(manifest['id']) / 'approval.json', {
        **{key: manifest[key] for key in ('input_hash', 'http_cap', 'provider', 'destination')},
        'approved': True, 'source': 'test_fixture'})


def test_unapproved_and_changed_input_never_call(prompt_store, monkeypatch):
    """没有批准或案例变化时必须在Provider调用前拒绝。"""
    runtime = RealEvaluation(prompt_store)
    manifest = runtime.prepare('sample', 'v1', 'normal', 2)
    calls = []
    monkeypatch.setattr(runtime, 'execute', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='authorization_pending'):
        runtime.run(manifest['id'])
    authorize(runtime, manifest)
    document, digest = prompt_store.cases('sample')
    document['cases'][1]['input']['task'] = '不同输入'
    prompt_store.save_cases('sample', document, digest)
    with pytest.raises(ValueError, match='input_changed'):
        runtime.run(manifest['id'])
    assert calls == []


@pytest.mark.parametrize('failed', [False, True])
def test_receipt_is_idempotent_and_failure_counts(prompt_store, monkeypatch, failed):
    """真实运行机制使用持久守卫，成功和失败都计数，重复调用不重发。"""
    from backend.app.runtime import prompt_real_evaluation as module
    runtime = RealEvaluation(prompt_store)
    manifest = runtime.prepare('sample', 'v1', 'normal', 1)
    authorize(runtime, manifest)
    calls = []

    class FixtureRuntime:
        """替代网络传输，同时保留实际预约与完成预算协议。"""

        def __init__(self, db):
            """保存隔离数据库会话，用于定位测试任务工作区。"""
            self.db = db

        def call(self, task_id, request):
            """模拟一次真实守卫预约；失败用量保持未知。"""
            from backend.app.models import Task
            from pathlib import Path
            root = Path(self.db.get(Task, task_id).workspace_path)
            attempt = repair.reserve_request(root, 'deepseek', request.request_id)
            calls.append(attempt)
            repair.finish_request(root, attempt, 'failed' if failed else 'responded',
                                  None if failed else {'total_tokens': 7})
            if failed:
                raise RuntimeError('fixture_failure')
            return SimpleNamespace(text='{"approved":true}', actions=[], raw_response={'fixture': True})

    monkeypatch.setattr(module, 'DeepSeekRuntime', FixtureRuntime)
    report = runtime.run(manifest['id'])
    assert report['usage']['http'] == 1
    assert report['usage']['unknown_usage'] == int(failed)
    assert runtime.run(manifest['id'])['id'] == report['id']
    assert calls == [1]
    assert runtime.runs('sample')[0]['status'] == 'completed'


def test_existing_database_and_unsafe_paths_never_reset(prompt_store):
    """中断现场、符号链接或路径穿越不能重建为新评测。"""
    runtime = RealEvaluation(prompt_store)
    manifest = runtime.prepare('sample', 'v1', 'normal', 1)
    authorize(runtime, manifest)
    (runtime.path(manifest['id']) / 'test.sqlite').write_text('interrupted')
    with pytest.raises(ValueError, match='recovery_required'):
        runtime.run(manifest['id'])
    assert (runtime.path(manifest['id']) / 'test.sqlite').read_text() == 'interrupted'
    with pytest.raises(ValueError, match='id_invalid'):
        runtime.path('../outside')


def test_api_cannot_create_authorization(prompt_store, monkeypatch):
    """客户端不能用请求体批准外发，已有未批准运行仍被拒绝。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app import prompt_api
    monkeypatch.setattr(prompt_api, 'store', lambda: prompt_store)
    runtime = RealEvaluation(prompt_store)
    manifest = runtime.prepare('sample', 'v1', 'normal', 1)
    app = FastAPI()
    app.include_router(prompt_api.router)
    with TestClient(app) as client:
        assert client.get('/api/prompts/sample/real-runs').json()['runs'][0]['id'] == manifest['id']
        response = client.post('/api/prompts/real-runs/' + manifest['id'] + '/execute',
                               json={'approved': True, 'http_cap': 30})
        assert response.status_code == 409
        assert not (runtime.path(manifest['id']) / 'test.sqlite').exists()


def test_component_parent_is_in_payload_and_approval_identity(prompt_store, monkeypatch):
    """父角色必须实际发送并绑定；父版本改变后旧授权不能继续使用。"""
    from backend.app.runtime.prompt_registry import sha256_text
    root = prompt_store.root
    (root / 'parent').mkdir()
    (root / 'parent/v1.md').write_text('完整消费角色v1')
    registry, _ = prompt_store.registry()
    registry['prompts']['parent'] = {'active': 'v1', 'sha256': sha256_text('完整消费角色v1'),
                                    'versions': {'v1': sha256_text('完整消费角色v1')}}
    atomic_json(root / 'registry.json', registry)
    document, digest = prompt_store.cases('sample')
    document['contract'].update(evaluation_parent='parent', parent_variables={})
    prompt_store.save_cases('sample', document, digest)
    runtime = RealEvaluation(prompt_store)
    payload = runtime.payload('sample', 'v1', 'normal')
    assert payload['instructions'].startswith('完整消费角色v1')
    assert [part['name'] for part in payload['components']] == ['parent', 'sample']
    manifest = runtime.prepare('sample', 'v1', 'normal', 1)
    authorize(runtime, manifest)
    prompt_store.create_version('parent', '完整消费角色v2', prompt_store.registry()[1])
    registry, _ = prompt_store.registry()
    registry['prompts']['parent'].update(active='v2', sha256=sha256_text('完整消费角色v2'))
    atomic_json(root / 'registry.json', registry)
    monkeypatch.setattr(runtime, 'execute', lambda *args: pytest.fail('cannot send changed parent'))
    with pytest.raises(ValueError, match='input_changed'):
        runtime.run(manifest['id'])
    assert not (runtime.path(manifest['id']) / 'test.sqlite').exists()


def test_all_component_payloads_use_registered_parent_and_tools():
    """全部公共片段可在实际角色下准备输入，不读取凭据或发送请求。"""
    from pathlib import Path
    import json
    runtime = RealEvaluation(PromptStore())
    count = 0
    for path in (Path(__file__).resolve().parents[1] / 'prompts/cases').glob('*.json'):
        document = json.loads(path.read_text())
        if document['contract']['role'] != 'component':
            continue
        version = runtime.store.entry(path.stem)['active']
        payload = runtime.payload(path.stem, version, 'normal')
        assert [part['name'] for part in payload['components']][:2] == [document['contract']['evaluation_parent'], path.stem]
        assert [tool['function']['name'] for tool in payload['tools']] == document['contract']['evaluation_tools']
        count += 1
    assert count == 58


def test_repair_probe_preserves_worker_read_only_history_tools():
    """返修真实探针必须保留Worker已提供的历史查询，不因评测入口缺工具失真。"""
    from backend.app.runtime.tools import QUERY_TOOL_SCHEMAS
    runtime = RealEvaluation(PromptStore())
    payload = runtime.payload('repair-executor', 'v5', 'business-change')
    names = [schema['function']['name'] for schema in payload['tools']]
    assert len(names) == len(set(names))
    assert 'verify_and_submit' not in names
    from backend.app.runtime.repair_session import VERIFY_AND_SUBMIT_SCHEMA
    newer = runtime.payload('repair-executor', 'v6', 'business-change')
    assert VERIFY_AND_SUBMIT_SCHEMA in newer['tools']
    for schema in QUERY_TOOL_SCHEMAS:
        assert schema in payload['tools']
