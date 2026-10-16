"""显式直连接线的离线验证。拦截HTTPX Client，绝不创建真实socket。"""
from dataclasses import replace
import json
import httpx
import pytest
from test_controlled_transport import case, bind, response
from backend.app.database import SessionLocal
from backend.app.models import Task,Message
from backend.app.runtime.model import DeepSeekRuntime,OpenRouterRuntime
from backend.app.runtime.contracts import ModelRequest
from backend.app.runtime.controlled_transport import ControlledTransportError
from backend.app.runtime.live_token_transport import call_approved_direct
from backend.app.runtime import task_budget as b


@pytest.fixture
def execution(case,monkeypatch):
    """用标准入口构造器的替身确认TLS/代理参数，所有请求由MockTransport消费。"""
    sent=[]; options=[]; behavior=[lambda request:response()]
    original=httpx.Client
    def handler(request):
        """保存合成请求，绝不打印认证头。"""
        sent.append(request);return behavior[0](request)
    def client(**kwargs):
        """拦截标准真实传输构造，禁网守卫提供第二道测试隔离。"""
        options.append(kwargs.copy())
        assert kwargs['transport'] is None and kwargs['follow_redirects'] is False
        kwargs['transport']=httpx.MockTransport(handler)
        return original(**kwargs)
    monkeypatch.setattr(httpx,'Client',client)
    return sent,options,behavior


def invoke_live(case,contract,verify=lambda scope:None,credential=lambda:'synthetic-live-auth',request_id='live-fixture',network_policy_id='synthetic-approved-network'):
    """仅测试的可信回调；生产中没有安装这些lambda。"""
    def approved_client(*,endpoint,timeout):
        """测试专用受控工厂；生产必须核实用户已批准代理/证书路径。"""
        return httpx.Client(transport=None,timeout=timeout,follow_redirects=False)
    with SessionLocal() as db:
        task=Task(task_name='live adapter fixture',workspace_path=str(case[0]));db.add(task);db.flush()
        cls=DeepSeekRuntime if contract.provider=='deepseek' else OpenRouterRuntime
        request=ModelRequest('system','input',{},[],request_id,required_token_budget_id=contract.budget_id,controlled_transport=contract)
        return call_approved_direct(cls(db),task.id,request,verify_current_authorization=verify,load_credential=credential,open_approved_client=approved_client,network_policy_id=network_policy_id)


def live(case,provider='deepseek'):
    """构造显式路由，无MockTransport字段；并不提供真实执行许可。"""
    return replace(bind(case,lambda request:None,provider=provider),mode='live_explicit',transport=None)


@pytest.mark.parametrize('provider',['deepseek','openrouter'])
def test_official_adapter_success(case,execution,provider):
    """同一保全链返回模型结果、计已知usage，记录准确目标与显式模式。"""
    checks=[]
    result=invoke_live(case,live(case,provider),verify=lambda scope:checks.append(scope))
    assert result.text=='ok' and len(execution[0])==1 and len(checks)==2
    assert checks[0].historical_unknown==3 and checks[0].cumulative_known_tokens==2746096
    assert b.load(case[0])['known_tokens']==12
    route=json.loads((case[0]/'controlled-response-evidence/live-fixture/route.json').read_text())
    assert route['mode']=='live_explicit' and route['actual_network_http']==1


@pytest.mark.parametrize('change',[{'channel':'go'},{'provider':'kimi'},{'model':'other'},{'endpoint':'https://unapproved.invalid/chat/completions'}, {'mode':'live'}, {'max_output_tokens':101}, {'transport':httpx.MockTransport(lambda r:response())}])
def test_invalid_route_before_credential(case,execution,change):
    """不能用Go、历史其他模型、换域或提高cap解锁。"""
    loaded=[]
    with pytest.raises(ControlledTransportError):
        invoke_live(case,replace(live(case),**change),credential=lambda:loaded.append(1))
    assert not loaded and not execution[0] and b.load(case[0])['http_attempts']==0


@pytest.mark.parametrize('verify',[None,{},lambda scope:True,lambda scope:{'approved':True}])
def test_no_json_or_boolean_authorization(case,execution,verify):
    """普通JSON及布尔不是受信任上层核验成功。"""
    loaded=[]
    with pytest.raises(ControlledTransportError):invoke_live(case,live(case),verify=verify,credential=lambda:loaded.append(1))
    assert not loaded and not execution[0]


def test_revocation_before_send(case,execution):
    """第二次授权核验失败时不预约、不构造HTTP客户端。"""
    calls=[]
    def verify(scope):
        """模拟认证后许可被撤回。"""
        calls.append(scope)
        if len(calls)==2:raise ValueError('do not expose')
    with pytest.raises(ControlledTransportError,match='live_authorization_not_verified'):
        invoke_live(case,live(case),verify=verify)
    assert not execution[1] and b.load(case[0])['http_attempts']==0


@pytest.mark.parametrize('credential',[None,lambda:'',lambda:None])
def test_missing_credential(case,execution,credential):
    """无连接时不发送，也不调用runtime默认凭据读取或Go回退。"""
    with pytest.raises(ControlledTransportError):invoke_live(case,live(case),credential=credential)
    assert not execution[0] and b.load(case[0])['http_attempts']==0


def test_unknown_blocks_next(case,execution):
    """真实接线共享未知即停语义，不抹去历史未知。"""
    execution[2][0]=lambda request:response(usage=False)
    for rid in ['first','second']:
        with pytest.raises(b.TaskBudgetError):invoke_live(case,live(case),request_id=rid)
    assert len(execution[0])==1 and b.load(case[0])['attempts'][0]['actual_tokens'] is None


def test_connection_failure_preserves_unknown(case,execution):
    """可能发送的失败不释放预算，不重试。"""
    def fail(request):
        """合成传输故障，不接触真实网络。"""
        raise httpx.ConnectError('synthetic-live-auth')
    execution[2][0]=fail
    with pytest.raises(b.TaskBudgetError):invoke_live(case,live(case))
    assert len(execution[0])==1 and b.load(case[0])['attempts'][0]['actual_tokens'] is None


def test_auth_echo_preserved_usage_no_message(case,execution):
    """同一调用侧认证值贯通回显扫描；拒绝执行但保留已知消费。"""
    execution[2][0]=lambda request:httpx.Response(200,content=response().content.replace(b'"ok"',b'"synthetic-live-auth"'))
    with pytest.raises(ControlledTransportError):invoke_live(case,live(case))
    assert b.load(case[0])['known_tokens']==12
    with SessionLocal() as db:assert db.query(Message).count()==0
    for path in (case[0]/'controlled-response-evidence').rglob('*'):
        if path.is_file():assert b'synthetic-live-auth' not in path.read_bytes()


def test_ledger_changed_during_credential(case,execution):
    """认证加载期间外部执行消费同一子账，第二次核验拒绝旧快照。"""
    def credential():
        """只改临时合成账，模拟另一个执行者。"""
        attempt=b.reserve(case[0],provider='deepseek',request_id='other',input_estimate=10,max_output_tokens=10)
        b.finish(case[0],attempt,status='responded',usage={'prompt_tokens':10,'completion_tokens':2,'total_tokens':12})
        return 'synthetic-live-auth'
    with pytest.raises(ControlledTransportError,match='live_current_ledger_changed'):
        invoke_live(case,live(case),credential=credential)
    assert not execution[0] and b.load(case[0])['http_attempts']==1


def test_runtime_route_mismatch_before_credential(case,execution,monkeypatch):
    """配置被改为其他域时拒绝，不把绑定里的官方域当实际连接证明。"""
    from backend.app.config import settings
    monkeypatch.setattr(settings,'deepseek_base_url','https://other.invalid')
    loaded=[]
    with pytest.raises(ControlledTransportError,match='controlled_route_binding_mismatch'):
        invoke_live(case,live(case),credential=lambda:loaded.append(1))
    assert not loaded and not execution[0]


def test_request_secret_rejected_before_write(case,execution):
    """最终payload内出现认证值时发送前拒绝，不保存敏感请求。"""
    with pytest.raises(ControlledTransportError,match='controlled_request_contains_secret'):
        invoke_live(case,live(case),credential=lambda:'system')
    assert not execution[0] and not (case[0]/'controlled-response-evidence').exists()


def test_redirect_does_not_follow(case,execution):
    """302只有一次请求，未知用量保持未知，不访问Location。"""
    execution[2][0]=lambda request:httpx.Response(302,headers={'Location':'https://other.invalid'},content=b'')
    with pytest.raises(b.TaskBudgetError):invoke_live(case,live(case))
    assert len(execution[0])==1 and b.load(case[0])['attempts'][0]['actual_tokens'] is None


@pytest.mark.parametrize('policy',[None,''])
def test_missing_network_policy_rejected(case,execution,policy):
    """没有已核网络策略绑定时不能选择标准默认直连。"""
    with pytest.raises(ControlledTransportError):invoke_live(case,live(case),network_policy_id=policy)
    assert not execution[0] and not execution[1]


@pytest.mark.parametrize('known',[False,True])
def test_dual_ledgers_settle_even_when_token_gate_stops(case,execution,known):
    """同时存在HTTP及Token账时，未知和已知超额均保存观察结果并停止。"""
    import hashlib
    from backend.app.runtime import repair_runtime as rr
    auth=case[0]/'fixture-authorization.json';auth.write_text('{}')
    state={'workflow':'repair-v1','revision':0,'state':'executing','authorization_ref':auth.name,
           'authorization_hash':hashlib.sha256(auth.read_bytes()).hexdigest(),
           'budget':{'provider':'deepseek','total_limit':8,'review_reserve':0,'attempts_used':0,'requests':[]}}
    (case[0]/rr.RUNTIME_PATH).write_text(json.dumps(state))
    if known:
        execution[2][0]=lambda request:httpx.Response(200,content=response().content.replace(b'"prompt_tokens": 10',b'"prompt_tokens": 10001').replace(b'"total_tokens": 12',b'"total_tokens": 10003'))
    else:execution[2][0]=lambda request:response(usage=False)
    with pytest.raises(b.TaskBudgetError):invoke_live(case,live(case))
    token=b.load(case[0])['attempts'][0]
    actual=rr.load(case[0])['budget']['requests'][0]
    assert len(execution[0])==1
    if known:
        assert token['actual_tokens']==10003 and actual['usage']['total_tokens']==10003 and actual['status']=='responded'
    else:
        assert token['actual_tokens'] is None and actual['usage'] is None and actual['status']=='failed'
