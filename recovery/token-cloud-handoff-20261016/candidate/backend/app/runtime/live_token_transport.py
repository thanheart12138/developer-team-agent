"""显式官方直连适配器。无自动启动、无默认授权器、无凭据存储。

这里的回调是受信任应用代码接口，不是抵抗恶意Python调用者的安全边界。
JSON、mode及离线连续账都不是用户许可。只有实际获准的上层操作者在核实
最新完整账本、供应商预算、子轮边界和连接后，才可提供核验器及凭据加载器。
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
from . import task_budget, token_lineage, token_transport
from .controlled_transport import ControlledTransport, ControlledTransportError, _execute


@dataclass(frozen=True)
class ExecutionScope:
    """交给上层核验的单次具体目标；不包含认证值或请求源码。"""
    binding: ControlledTransport
    request_id: str
    execution_root: str
    child_state_sha256: str
    payload_sha256: str
    network_policy_id: str
    cumulative_http: int
    cumulative_known_tokens: int
    historical_unknown: int
    historical_nonactual_holds: int


_ROUTES={
    'deepseek':('https://api.deepseek.com/chat/completions', 'deepseek-flash'),
    'openrouter':('https://openrouter.ai/api/v1/chat/completions', 'openai/gpt-6-luna'),
}


def _scope(binding,request,payload_sha256,network_policy_id):
    """校验唯一官方路由和当前账；原offline合同只用于连续记账，不改授权位。"""
    if (type(binding) is not ControlledTransport or binding.mode!='live_explicit'
            or binding.transport is not None or binding.channel!='direct'
            or _ROUTES.get(binding.provider)!=(binding.endpoint,binding.model)):
        raise ControlledTransportError('live_route_not_allowed')
    if type(binding.max_output_tokens) is not int or binding.max_output_tokens<=0:
        raise ControlledTransportError('live_output_cap_required')
    state=token_lineage.verify(binding.lineage_path,binding.lineage_sha256)
    if (state['budget_id']!=binding.budget_id or request.required_token_budget_id!=binding.budget_id
            or binding.max_output_tokens>state['contract']['baseline']['limits']['max_output_tokens']):
        raise ControlledTransportError('live_budget_binding_mismatch')
    root=state['contract']['execution_root']
    raw=token_lineage._read(Path(root)/task_budget.STATE_PATH)
    return state,ExecutionScope(binding,request.request_id,root,hashlib.sha256(raw).hexdigest(),payload_sha256,network_policy_id,
        state['research_http'],state['research_known'],state['historical_unknown'],
        state['historical_nonactual_holds'])


def call_approved_direct(runtime,task_id,request,*,verify_current_authorization=None,load_credential=None,
                         open_approved_client=None,network_policy_id=None):
    """单次真实入口，无重试/回退；缺少受信任上层核验与安全认证回调即拒绝。

    verify_current_authorization(scope) 必须核对当前用户许可、scope中的准确路由/
    模型/cap/子账摘要、所有环境最新连续账、供应商累计预算及未知处理决定。
    成功仅返回None，无法核实则抛异常；不是读JSON里的approved=true。
    load_credential() 仅由获准现有连接提供，不从本模块读环境/文件或保存密钥。
    open_approved_client(endpoint=...,timeout=...) 必须复用已核准的网络路径，
    TLS/代理/证书和零重试设置由该工厂确认；缺策略绑定就拒绝，不强制直连。
    调用方不能把测试lambda充当生产授权器。未提供生产调用方，默认仍关闭。
    """
    if (not callable(verify_current_authorization) or not callable(load_credential)
            or not callable(open_approved_client) or not isinstance(network_policy_id,str)
            or not network_policy_id.strip()):
        raise ControlledTransportError('live_trusted_callbacks_required')
    binding=request.controlled_transport
    state,_=_scope(binding,request,'',network_policy_id)
    payload=token_transport.prepare(Path(state['contract']['execution_root']),runtime.build_payload(request))
    payload['max_tokens']=min(payload['max_tokens'],binding.max_output_tokens)
    payload_sha256=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    state,scope=_scope(binding,request,payload_sha256,network_policy_id)
    def verify():
        """发送前复核同一快照；回调失败不泄露其异常或更换路由重试。"""
        _,current=_scope(binding,request,payload_sha256,network_policy_id)
        if current!=scope:
            raise ControlledTransportError('live_current_ledger_changed')
        try:
            result=verify_current_authorization(current)
        except Exception:
            raise ControlledTransportError('live_authorization_not_verified') from None
        if result is not None:
            raise ControlledTransportError('live_authorization_not_verified')
        if _scope(binding,request,payload_sha256,network_policy_id)[1]!=scope:
            raise ControlledTransportError('live_current_ledger_changed')
    verify()
    # _execute在认证回调前检查实际runtime/任务/payload，发送前再次核验。
    # 不自行构造真实网络配置。获准上层工厂必须沿用已核准代理/TLS/证书策略，
    # 禁止重试，不能因为连接失败绕开代理；策略身份同样进入授权核验scope。
    return _execute(runtime,task_id,request,state,transport=None,credential_loader=load_credential,
                    execution_mode='live_explicit',before_send=verify,prepared_payload=payload,client_factory=open_approved_client)
