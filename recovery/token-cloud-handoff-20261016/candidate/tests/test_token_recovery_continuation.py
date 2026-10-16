"""恢复后明确核对新主线续传协议；不把旧OpenRouter双表示补丁强行套入Go。"""
from copy import deepcopy
import json

from backend.app.config import settings
from backend.app.runtime.contracts import ModelRequest
from backend.app.runtime.model import DeepSeekRuntime
from backend.app.runtime.opencode import OpenCodeRuntime


def request_with_history():
    """生成含重复语句和两个配对工具结果的同批历史，防止按正文误去重。"""
    thought='检查完整来源。' * 8625
    history=[]
    for name in ('first', 'second'):
        history.append({'model_request_id':'same-batch','reasoning_content':thought,
                        'assistant_content':'继续实现',
                        'action':{'call_id':name,'tool_name':'read','parameters':{'path':name+'.js'}},
                        'result':{'call_id':name,'status':'succeeded','output':{'content':'source '+name}}})
    return ModelRequest('原指令','完整任务',{'tool_history':history},[], 'offline-request'),thought


def test_go_continuation_keeps_full_thought_once_per_batch(monkeypatch):
    """Go续传完整思考一次，不增加旧实验的reasoning_details重复表示。"""
    monkeypatch.setattr(settings,'deepseek_reasoning_effort','low')
    request,thought=request_with_history();before=deepcopy(request.context)
    body=OpenCodeRuntime(DeepSeekRuntime(None)).build_payload(request)
    assistant=[m for m in body['messages'] if m['role']=='assistant']
    assert len(assistant)==1
    assert assistant[0]['reasoning_content']==thought
    assert 'reasoning_details' not in assistant[0]
    assert [t['id'] for t in assistant[0]['tool_calls']]==['first','second']
    results=[m for m in body['messages'] if m['role']=='tool']
    assert [m['tool_call_id'] for m in results]==['first','second']
    assert [json.loads(m['content']) for m in results]==[x['result'] for x in before['tool_history']]
    assert body['reasoning_effort']=='low' and body['max_tokens']==32768
    assert request.context==before


def test_official_fallback_retains_low_and_full_batch(monkeypatch):
    """官方回退维持low和完整配对，不把渠道输出cap误当任务总Token上限。"""
    monkeypatch.setattr(settings,'deepseek_reasoning_effort','low')
    monkeypatch.setattr(settings,'deepseek_model','deepseek-flash')
    request,thought=request_with_history()
    body=DeepSeekRuntime(None).build_payload(request)
    assert body['reasoning_effort']=='low'
    assert body['thinking']=={'type':'enabled'}
    assert body['messages'][2]['reasoning_content']==thought
    assert 'reasoning_details' not in body['messages'][2]
    assert [m['role'] for m in body['messages']]==['system','user','assistant','tool','tool']
