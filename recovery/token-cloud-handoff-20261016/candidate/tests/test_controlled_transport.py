"""真正模型运行时的受控分支只接内存HTTP，所有凭据读取均设为失败。"""
import json
from dataclasses import replace
import httpx
import pytest
from backend.app.database import Base,engine,SessionLocal
from backend.app.models import Task,Message
from backend.app.runtime.contracts import ModelRequest
from backend.app.runtime.model import DeepSeekRuntime,OpenRouterRuntime
from backend.app.runtime.controlled_transport import ControlledTransport,ControlledTransportError
from backend.app.runtime import task_budget as b,token_lineage as l


@pytest.fixture
def case(tmp_path,monkeypatch):
    """隔离子账与历史源；不引用真实批准或真实密钥。"""
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    root=tmp_path/'execution';root.mkdir();state=b.initialize(root,total_tokens=10000,http_limit=8,max_output_tokens=100)
    source=tmp_path/'source.json';source.write_bytes((root/b.STATE_PATH).read_bytes())
    report=tmp_path/'report.json';report.write_text(json.dumps({'child_budget':state,'cumulative_http':73,'cumulative_known_tokens':2746096,'cumulative_known_input_tokens':2361313,'cumulative_known_output_tokens':384783,'historical_unknown':3,'historical_nonactual_holds':219060}))
    receipt=l.create_contract(tmp_path/'contract.json',execution_root=root,source_budget=source,source_report=report,research_limit=10000000)
    def no_credentials(*args):
        """受控模拟路径绝不能读取任何真实凭据。"""
        raise AssertionError('credential_read_forbidden')
    monkeypatch.setattr(DeepSeekRuntime,'get_api_key',no_credentials)
    monkeypatch.setattr(OpenRouterRuntime,'get_api_key',no_credentials)
    monkeypatch.setattr('backend.app.runtime.opencode.get_api_key',no_credentials)
    return root,state,receipt


def bind(case,handler,channel='direct',provider='deepseek',mode='mock_only'):
    """测试显式构造唯一目的地合同。"""
    root,state,r=case
    model={'direct':{'deepseek':'deepseek-flash','openrouter':'openai/gpt-6-luna'},'go':{'deepseek':'deepseek-v4.1-flash','openrouter':'gpt-6-luna'}}[channel][provider]
    base='https://opencode.ai/inference/go/v1' if channel=='go' else 'https://api.deepseek.com' if provider=='deepseek' else 'https://openrouter.ai/api/v1'
    endpoint=base+('/responses' if channel=='go' and provider=='openrouter' else '/chat/completions')
    return ControlledTransport(r['path'],r['sha256'],state['budget_id'],channel,provider,model,endpoint,50,mode,httpx.MockTransport(handler))


def invoke(case,binding,request_id='controlled'):
    """调用生产runtime.call而不是旁路模拟解析函数。"""
    with SessionLocal() as db:
        task=Task(task_name='controlled fixture',workspace_path=str(case[0]));db.add(task);db.flush()
        cls=DeepSeekRuntime if binding.provider=='deepseek' else OpenRouterRuntime
        request=ModelRequest('system','input',{},[] ,request_id,required_token_budget_id=binding.budget_id,controlled_transport=binding)
        return cls(db).call(task.id,request)


def response(responses=False,tail=b'data: [DONE]\n\n',usage=True):
    """按两种生产协议返回已知小用量。"""
    if responses:
        body={'object':'response','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}]}
        if usage:body['usage']={'input_tokens':10,'output_tokens':2,'total_tokens':12}
        return httpx.Response(200,json=body)
    event={'choices':[{'index':0,'delta':{'content':'ok'},'finish_reason':'stop'}]}
    if usage:event['usage']={'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}
    return httpx.Response(200,content=b'data: '+json.dumps(event).encode()+b'\n\n'+tail)


@pytest.mark.parametrize('channel,provider',[('direct','deepseek'),('direct','openrouter'),('go','deepseek'),('go','openrouter')])
def test_production_paths_scan_settle_then_finish(case,channel,provider):
    """四条明确路由都走真实payload与结果处理但不创建网络连接。"""
    sent=[]
    def handler(request):
        """记录实际HTTPX内存请求对象。"""
        sent.append(request);return response(channel=='go' and provider=='openrouter')
    contract=bind(case,handler,channel,provider);result=invoke(case,contract)
    assert len(sent)==1 and str(sent[0].url)==contract.endpoint
    body=json.loads(sent[0].content);assert body.get('max_tokens',body.get('max_output_tokens'))==50
    assert result.text=='ok' and result.raw_response['actual_network_http']==0
    assert b.load(case[0])['known_tokens']==12
    assert (case[0]/'controlled-response-evidence/controlled/response/manifest.json').exists()


@pytest.mark.parametrize('change',[{'mode':'disabled'},{'mode':'live'},{'transport':None},{'endpoint':'https://unapproved.invalid/chat/completions'},{'model':'other'},{'max_output_tokens':101}])
def test_bad_contract_stops_before_any_attempt(case,change):
    """默认关闭及身份变化在发送或凭据读取前失败。"""
    sent=[];contract=replace(bind(case,lambda request:sent.append(request)),**change)
    with pytest.raises(ControlledTransportError):invoke(case,contract)
    assert sent==[] and b.load(case[0])['http_attempts']==0


@pytest.mark.parametrize('tail',[b'data: [DO',b'\xff',b''])
def test_known_invalid_stream_never_falls_back(case,tail):
    """已知消费保全但坏终态不产生模型消息也不回退。"""
    sent=[]
    def handler(request):
        """构造不完整终态。"""
        sent.append(request);return response(tail=tail)
    with pytest.raises(ControlledTransportError):invoke(case,bind(case,handler,'go'))
    assert len(sent)==1 and b.load(case[0])['known_tokens']==12
    with SessionLocal() as db:assert db.query(Message).count()==0


def test_unknown_blocks_next_call(case):
    """未知响应后再次调用在网络前被连续账阻断。"""
    sent=[]
    def handler(request):
        """返回没有usage的完整回复。"""
        sent.append(request);return response(usage=False)
    contract=bind(case,handler)
    for request_id in ['first','second']:
        with pytest.raises(b.TaskBudgetError):invoke(case,contract,request_id)
    assert len(sent)==1 and b.load(case[0])['attempts'][0]['actual_tokens'] is None


def test_cancel_preserves_pending_and_stops_reentry(case):
    """取消不释放已登记可能发出的预约。"""
    def handler(request):
        """在传输中模拟取消。"""
        raise KeyboardInterrupt()
    contract=bind(case,handler)
    with pytest.raises(KeyboardInterrupt):invoke(case,contract)
    assert b.load(case[0])['attempts'][0]['actual_tokens'] is None
    with pytest.raises(b.TaskBudgetError):invoke(case,contract,'again')


def test_responses_bad_arguments_are_charged_without_result(case):
    """生产Responses分支沿用已审严格工具参数门。"""
    def handler(request):
        """非法工具数组不是可执行参数对象。"""
        return httpx.Response(200,json={'object':'response','status':'completed','usage':{'input_tokens':10,'output_tokens':2,'total_tokens':12},'output':[{'type':'function_call','call_id':'x','name':'tool','arguments':'[]'}]})
    with pytest.raises(ControlledTransportError):invoke(case,bind(case,handler,'go','openrouter'))
    assert b.load(case[0])['known_tokens']==12


@pytest.mark.parametrize('channel,provider',[('direct','deepseek'),('direct','openrouter'),('go','deepseek'),('go','openrouter')])
def test_preserved_body_replacement_rejected_for_every_route(case,monkeypatch,channel,provider):
    """同一份摘要绑定的消费字节贯通结果，替换文件不能漏到模型消息。"""
    original=l.verify
    def replace_after_gate(path,sha):
        """在保全完成和消费之间注入修改。"""
        result=original(path,sha)
        p=case[0]/'controlled-response-evidence/controlled/response/response.json'
        if p.exists():p.write_text('{}')
        return result
    monkeypatch.setattr(l,'verify',replace_after_gate)
    with pytest.raises(ControlledTransportError):
        invoke(case,bind(case,lambda request:response(channel=='go' and provider=='openrouter'),channel,provider))
    assert b.load(case[0])['known_tokens']==12
    with SessionLocal() as db:assert db.query(Message).count()==0


@pytest.mark.parametrize('channel,provider',[('direct','deepseek'),('direct','openrouter'),('go','deepseek'),('go','openrouter')])
def test_readerror_after_complete_usage_kept_for_every_route(case,channel,provider):
    """协议已完整但传输尾报错，保留已知消费同时拒绝任务结果。"""
    raw=response(channel=='go' and provider=='openrouter').content
    class Broken(httpx.SyncByteStream):
        """只返回合成字节，不创建连接。"""
        def __iter__(self):
            yield raw
            raise httpx.ReadError('fixture')
    with pytest.raises(ControlledTransportError):
        invoke(case,bind(case,lambda request:httpx.Response(200,stream=Broken()),channel,provider))
    assert b.load(case[0])['known_tokens']==12
    with SessionLocal() as db:assert db.query(Message).count()==0


@pytest.mark.parametrize('channel,provider',[('direct','deepseek'),('go','openrouter')])
@pytest.mark.parametrize('encoding',['plain','url','base64'])
@pytest.mark.parametrize('location',['content','wire'])
def test_auth_scan_uses_same_synthetic_value_as_headers(case,monkeypatch,channel,provider,encoding,location):
    """替换合成认证值后，两种协议的正文及原始实体泄露均保留消费但禁止执行。"""
    import base64
    from urllib.parse import quote
    from backend.app.runtime import controlled_transport
    secret='synthetic-only+/auth=second-value'
    monkeypatch.setattr(controlled_transport,'FIXTURE_SECRET',secret)
    leak={'plain':secret,'url':quote(secret,safe=''),'base64':base64.b64encode(secret.encode()).decode()}[encoding]
    def handler(request):
        """核认证头与测试合成值一致，仅构造内存响应，不读取认证连接。"""
        assert request.headers['Authorization']=='Bearer '+secret
        raw=response(channel=='go').content
        if location=='content':
            raw=raw.replace(b'"ok"',json.dumps(leak).encode())
        elif channel=='go':
            body=json.loads(raw);body['fixture_metadata']=leak;raw=json.dumps(body).encode()
        else:
            raw=b': '+leak.encode()+b'\n\n'+raw
        return httpx.Response(200,content=raw)
    with pytest.raises(ControlledTransportError):
        invoke(case,bind(case,handler,channel,provider))
    assert b.load(case[0])['known_tokens']==12
    with SessionLocal() as db:assert db.query(Message).count()==0
    evidence=case[0]/'controlled-response-evidence/controlled'
    manifest=json.loads((evidence/'response/manifest.json').read_bytes())
    assert manifest['credentials_redacted'] is True
    assert manifest['received_entity_saved'] is False
    for path in evidence.rglob('*'):
        if path.is_file():
            data=path.read_bytes()
            assert secret.encode() not in data and leak.encode() not in data


@pytest.mark.parametrize('channel,provider',[('direct','deepseek'),('go','openrouter')])
def test_changed_synthetic_auth_accepts_safe_response(case,monkeypatch,channel,provider):
    """不同合成认证标记不影响无泄露回复，且证据仍明确零真实HTTP。"""
    from backend.app.runtime import controlled_transport
    secret='synthetic-safe-second-value'
    monkeypatch.setattr(controlled_transport,'FIXTURE_SECRET',secret)
    def handler(request):
        """核对合成认证后返回安全内存回复。"""
        assert request.headers['Authorization']=='Bearer '+secret
        return response(channel=='go')
    result=invoke(case,bind(case,handler,channel,provider))
    assert result.text=='ok' and result.raw_response['actual_network_http']==0
    assert b.load(case[0])['known_tokens']==12
