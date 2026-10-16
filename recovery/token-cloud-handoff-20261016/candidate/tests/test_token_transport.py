"""生产模型入口与MockTransport联测累计Token、回退及未知阻断，零真实HTTP。"""
import json
import httpx
import pytest
from backend.app.config import settings
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Task
from backend.app.runtime.contracts import ModelRequest
from backend.app.runtime.model import DeepSeekRuntime, OpenRouterRuntime
from backend.app.runtime import task_budget as budget, token_transport as guard


@pytest.fixture
def setup(monkeypatch,tmp_path):
    """所有预算和数据库仅为隔离测试合成状态；真实账本从不初始化。"""
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    monkeypatch.setattr(settings,'opencode_enabled',True)
    monkeypatch.setattr(settings,'deepseek_api_key','fixture')
    monkeypatch.setattr('backend.app.runtime.opencode.get_api_key',lambda:'fixture')
    monkeypatch.setattr('backend.app.runtime.opencode.time.sleep',lambda _:None)
    state=budget.initialize(tmp_path,total_tokens=1000000,http_limit=8,max_output_tokens=65536)
    return tmp_path,state


def response(usage=None,done=True,invalid=False):
    """构造带真实usage语义的安全假SSE；可故障注入截断。"""
    usage=usage if usage is not None else {'prompt_tokens':10,'completion_tokens':2,'total_tokens':12,'completion_tokens_details':{'reasoning_tokens':2}}
    event={'choices':[{'delta':{'content':'ok'},'finish_reason':'stop'}],'usage':usage}
    return httpx.Response(200,text='data: '+json.dumps(event)+'\n\n'+('data: [DONE]\n\n' if done else ''))


def connect(monkeypatch,handler):
    """保留生产HTTPX调用，只换底层传输，不接触实际认证或网络。"""
    cls=httpx.Client
    monkeypatch.setattr('backend.app.runtime.model.httpx.Client',lambda **kw:cls(transport=httpx.MockTransport(handler),**kw))


def invoke(root,identity,runtime_class=DeepSeekRuntime):
    """实际实验入口要求现有budget_id，不允许无账启动。"""
    with SessionLocal() as db:
        task=Task(task_name='offline token fixture',workspace_path=str(root));db.add(task);db.flush()
        return guard.call_experiment(runtime_class(db),task.id,ModelRequest('system','input',{},[],'same'),budget_id=identity)


def test_go_known_usage_counts_once(setup,monkeypatch):
    """思考已在输出内；cap沿用Go32768而非抬高至任务65536。"""
    root,state=setup;sent=[]
    def handler(request):
        """保存真实发送JSON并返回已知响应。"""
        sent.append(json.loads(request.content));return response()
    connect(monkeypatch,handler);invoke(root,state['budget_id'])
    b=budget.load(root);assert b['http_attempts']==1 and b['known_tokens']==12
    assert b['attempts'][0]['input_estimate']==len(json.dumps(sent[0],ensure_ascii=False).encode())
    assert sent[0]['max_tokens']==32768


def test_known_failed_go_charged_then_original_fallback(setup,monkeypatch):
    """已知usage截断不丢账，Go失败和原渠道成功各收费一次。"""
    root,state=setup;hosts=[]
    def handler(request):
        """Go缺DONE但带usage，官方返回完整响应。"""
        hosts.append(request.url.host);return response(done=request.url.host!='opencode.ai')
    connect(monkeypatch,handler);invoke(root,state['budget_id'])
    b=budget.load(root);assert hosts==['opencode.ai','api.deepseek.com']
    assert b['known_tokens']==24 and b['http_attempts']==2
    assert [x['status'] for x in b['attempts']]==['failed','responded']


@pytest.mark.parametrize('status',[401,429,503])
def test_unknown_usage_stops_all_retries_and_fallback(setup,monkeypatch,status):
    """无usage即未知；HTTP状态不能被当作零成本许可。"""
    root,state=setup;sent=[]
    def handler(request):
        """模拟无用量的失败响应。"""
        sent.append(request.url.host);return httpx.Response(status)
    connect(monkeypatch,handler)
    with pytest.raises(budget.TaskBudgetError,match='unresolved'):invoke(root,state['budget_id'])
    assert sent==['opencode.ai'];b=budget.load(root)
    assert b['attempts'][0]['actual_tokens'] is None and b['known_tokens']==0
    with pytest.raises(budget.TaskBudgetError,match='unresolved'):invoke(root,state['budget_id'])
    assert len(sent)==1


def test_responses_normalizes_usage_and_reserves_output(setup,monkeypatch):
    """Luna Responses与Chat共享账，不重复加reasoning。"""
    root,state=setup
    def handler(request):
        """返回Responses完整结果与使用量。"""
        assert json.loads(request.content)['max_output_tokens']==32768
        return httpx.Response(200,json={'object':'response','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}], 'usage':{'input_tokens':20,'output_tokens':5,'total_tokens':25,'output_tokens_details':{'reasoning_tokens':4}}})
    connect(monkeypatch,handler);invoke(root,state['budget_id'],OpenRouterRuntime)
    assert budget.load(root)['known_tokens']==25


def test_pre_send_rejection_uses_existing_consumption(setup,monkeypatch):
    """已有消费不清零；余额不足在HTTP前拒绝。"""
    root,state=setup;a=budget.reserve(root,provider='fixture',request_id='historical',input_estimate=1,max_output_tokens=1)
    budget.finish(root,a,status='responded',usage={'total_tokens':999999})
    sent=[];connect(monkeypatch,lambda req:sent.append(req))
    with pytest.raises(budget.TaskBudgetError):invoke(root,state['budget_id'])
    assert not sent and budget.load(root)['known_tokens']==999999 and budget.load(root)['http_attempts']==1


def test_missing_budget_is_not_compatible_experiment(tmp_path,monkeypatch):
    """普通产品可未启用，但实验入口必须明确拒绝无账。"""
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    monkeypatch.setattr('backend.app.runtime.opencode.get_api_key',lambda:pytest.fail('must not read auth'))
    with pytest.raises(budget.TaskBudgetError,match='binding'):invoke(tmp_path,'missing')


def test_worker_never_retries_or_changes_model_on_token_error(setup,monkeypatch):
    """外层Worker也把Token拒绝当终态，不能换模型绕过通道门。"""
    from backend.app.models import Step, StepRun, StepStatus, TaskStatus
    from backend.app.runtime.worker import model_tool_loop
    from backend.app.runtime.tools import ToolRuntime
    root,state=setup;calls=[]
    def failed(runtime,task_id,request):
        """模拟底层已明确停止的预算错误。"""
        calls.append(runtime.provider);raise budget.TaskBudgetError('task_budget_unresolved_attempt')
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call',failed)
    with SessionLocal() as db:
        task=Task(task_name='budget-stop',cur_step=Step.product_docs,status=TaskStatus.running,workspace_path=str(root));db.add(task);db.flush()
        run=StepRun(task_id=task.id,step=Step.product_docs,status=StepStatus.running,attempt=1,checkpoint_path=str(root/'evidence/checkpoint.json'));db.add(run);db.commit()
        with pytest.raises(budget.TaskBudgetError):model_tool_loop(db,task,run,'gate','input',{},ToolRuntime(root))
    assert len(calls)==1


def test_cancelled_send_remains_unknown_and_blocks_new_request(setup,monkeypatch):
    """取消无法假定没有服务端消费；持久预约保留且不可自动重发。"""
    root,state=setup;sent=[]
    def cancelled(request):
        """模拟发送中断，不制造零usage。"""
        sent.append(request);raise KeyboardInterrupt()
    connect(monkeypatch,cancelled)
    with pytest.raises(KeyboardInterrupt):invoke(root,state['budget_id'])
    b=budget.load(root);assert b['attempts'][0]['status']=='send_unknown' and b['attempts'][0]['actual_tokens'] is None
    with pytest.raises(budget.TaskBudgetError):invoke(root,state['budget_id'])
    assert len(sent)==1


def test_responses_unknown_cannot_fallback(setup,monkeypatch):
    """Responses即使内容完整，缺usage也不能交付成功或走备用渠道。"""
    root,state=setup;sent=[]
    def unknown(request):
        """模拟成功状态但缺用量的响应。"""
        sent.append(request);return httpx.Response(200,json={'object':'response','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}]})
    connect(monkeypatch,unknown)
    with pytest.raises(budget.TaskBudgetError):invoke(root,state['budget_id'],OpenRouterRuntime)
    assert len(sent)==1 and budget.load(root)['attempts'][0]['actual_tokens'] is None


def test_bound_budget_identity_rechecked_inside_reservation(setup,monkeypatch):
    """绑定检查后若换成另一完整账，预约锁内仍拒绝并保持零发送。"""
    root,state=setup
    with pytest.raises(budget.TaskBudgetError,match='binding'):
        budget.reserve(root,provider='fixture',request_id='wrong-identity',input_estimate=1,max_output_tokens=1,expected_budget_id='0'*32)
    assert budget.load(root)['http_attempts']==0


def test_required_budget_cannot_disappear_into_legacy_mode(tmp_path):
    """实验绑定不能因预算目录被清空而静默降级为无Token门旧模式。"""
    with pytest.raises(budget.TaskBudgetError,match='binding'):
        guard.reserve(tmp_path,'fixture','request',{'max_tokens':1},expected_budget_id='0'*32)
    with pytest.raises(budget.TaskBudgetError,match='binding'):
        budget.reserve(tmp_path,provider='fixture',request_id='request',input_estimate=1,max_output_tokens=1,expected_budget_id='0'*32)


def test_budget_disappearing_between_binding_and_load_is_rejected(setup,monkeypatch):
    """独审反例：两次读取间整账消失仍不能返回无保护的None。"""
    root,state=setup;observations=iter([state,None])
    monkeypatch.setattr(budget,'load',lambda root:next(observations))
    with pytest.raises(budget.TaskBudgetError,match='binding'):
        guard.reserve(root,'fixture','request',{'max_tokens':1},expected_budget_id=state['budget_id'])
