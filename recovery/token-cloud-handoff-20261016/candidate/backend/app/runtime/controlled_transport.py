"""默认调用分支只接受内存模拟HTTP；显式真实入口在live_token_transport。"""
from dataclasses import dataclass
from pathlib import Path
import json
import hashlib
import os
import re
import httpx
from . import token_lineage, token_transport
from .task_budget import TaskBudgetError
from .response_evidence import parse, MAX_BYTES, _Directory, _read
from .sse_response_evidence import SSEEvidenceGate, ResponseEvidenceError
from .token_offline_runner import _responses, FIXTURE_SECRET


@dataclass(frozen=True)
class ControlledTransport:
    """固定一个渠道和模型，不能从失败中扩大目的地或预算。"""
    lineage_path: str
    lineage_sha256: str
    budget_id: str
    channel: str
    provider: str
    model: str
    endpoint: str
    max_output_tokens: int
    mode: str = 'disabled'
    transport: object = None


class ControlledTransportError(TaskBudgetError):
    """所有受控错误都终止实验，不交给重试或换模型逻辑。"""


def validate(binding):
    """在认证、文件写入及连接构造前核固定模式与连续账。"""
    if (not isinstance(binding,ControlledTransport) or binding.mode!='mock_only'
            or type(binding.transport) is not httpx.MockTransport):
        raise ControlledTransportError('controlled_transport_disabled')
    if binding.channel not in {'direct','go'} or binding.provider not in {'deepseek','openrouter'}:
        raise ControlledTransportError('controlled_route_not_allowed')
    if type(binding.max_output_tokens) is not int or binding.max_output_tokens<=0:
        raise ControlledTransportError('controlled_output_cap_required')
    current=token_lineage.verify(binding.lineage_path,binding.lineage_sha256)
    if current['budget_id']!=binding.budget_id:
        raise ControlledTransportError('controlled_budget_mismatch')
    if binding.max_output_tokens>current['contract']['baseline']['limits']['max_output_tokens']:
        raise ControlledTransportError('controlled_output_cap_exceeds_budget')
    return current


def call_selected(original,task_id,request):
    """选择合同中唯一渠道；不调用默认渠道选择或任何回退。"""
    binding=request.controlled_transport
    validate(binding)
    if original.provider!=binding.provider or request.required_token_budget_id!=binding.budget_id:
        raise ControlledTransportError('controlled_request_binding_mismatch')
    if binding.channel=='go':
        from .opencode import OpenCodeRuntime
        selected=OpenCodeRuntime(original)
    else:
        selected=original
    return selected._call_direct(task_id,request)


def read_verified_response(evidence,identity,result):
    """只消费同目录FD读取且匹配本次保全摘要的字节，不验证后再重读路径。"""
    directory=target=None
    try:
        directory=_Directory(evidence)
        stat=os.fstat(directory.fd)
        if (stat.st_dev,stat.st_ino)!=identity:
            raise ControlledTransportError('controlled_evidence_identity_changed')
        target=directory.child('response')
        manifest_bytes=_read(target/'manifest.json',65536)
        if hashlib.sha256(manifest_bytes).hexdigest()!=result.get('manifest_sha256'):
            raise ControlledTransportError('controlled_evidence_manifest_changed')
        manifest=parse(manifest_bytes)
        body=_read(target/'response.json',MAX_BYTES)
        if hashlib.sha256(body).hexdigest()!=manifest['files']['response.json']:
            raise ControlledTransportError('controlled_evidence_body_changed')
        return parse(body)
    finally:
        if target is not None:target.close()
        if directory is not None:directory.close()


def call_direct(runtime,task_id,request):
    """走生产运行时的构造与结果链，网络层被限定为内存模拟传输。"""
    binding=request.controlled_transport
    state=validate(binding)
    return _execute(runtime,task_id,request,state,transport=binding.transport,
                    credential_loader=lambda: FIXTURE_SECRET,execution_mode='mock_only')


def _execute(runtime,task_id,request,state,*,transport,credential_loader,
             execution_mode,before_send=None,prepared_payload=None,client_factory=None):
    """共用已审保全链；真实入口负责上层授权，私有函数不是权限边界。"""
    from ..models import Task
    from .repair_runtime import reserve_request,finish_request
    binding=request.controlled_transport
    from .opencode import OpenCodeRuntime
    is_go=isinstance(runtime,OpenCodeRuntime)
    responses=is_go and runtime.provider=='openrouter'
    endpoint=runtime.base_url.rstrip('/')+('/responses' if responses else '/chat/completions')
    task=runtime.db.get(Task,task_id)
    root=Path(task.workspace_path).absolute() if task and task.workspace_path else None
    if (root!=Path(state['contract']['execution_root']) or runtime.provider!=binding.provider
            or runtime.model_name!=binding.model or endpoint!=binding.endpoint
            or is_go!=(binding.channel=='go') or request.required_token_budget_id!=binding.budget_id):
        raise ControlledTransportError('controlled_route_binding_mismatch')
    if not isinstance(request.request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request.request_id):
        raise ControlledTransportError('controlled_request_id_invalid')
    payload=token_transport.prepare(root,runtime.build_payload(request)) if prepared_payload is None else prepared_payload
    key='max_output_tokens' if responses else 'max_tokens'
    payload[key]=min(payload[key],binding.max_output_tokens)
    # 先核任务、唯一端点和最终payload，再由受信任调用方提供认证值。
    try:
        auth_secret=credential_loader()
    except Exception:
        raise ControlledTransportError('controlled_credential_unavailable') from None
    if not isinstance(auth_secret,str) or not auth_secret.strip():
        raise ControlledTransportError('controlled_credential_unavailable')
    from .response_evidence import sanitize
    if sanitize(payload,[auth_secret])[1]:
        raise ControlledTransportError('controlled_request_contains_secret')
    parent=root/'controlled-response-evidence'
    if parent.is_symlink():raise ControlledTransportError('controlled_evidence_path_invalid')
    parent.mkdir(mode=0o700,exist_ok=True)
    evidence=parent/request.request_id;evidence.mkdir(mode=0o700,exist_ok=False)
    stat=evidence.stat();evidence_identity=(stat.st_dev,stat.st_ino)
    (evidence/'route.json').write_text(json.dumps({'mode':execution_mode,'actual_network_http':0,
        'channel':binding.channel,'provider':binding.provider,'model':binding.model,
        'endpoint':endpoint,'max_output_tokens':payload[key],'budget_id':binding.budget_id}))
    token_attempt=None;http_attempt=None;settlement_called=False
    def settle(usage):
        """保全门只结算一次；已知失败仍记账，未知阻断所有后续尝试。"""
        nonlocal settlement_called
        if settlement_called:raise ControlledTransportError('controlled_double_settlement')
        settlement_called=True
        try:
            token_transport.settle(root,token_attempt,'responded' if usage is not None else 'failed',usage)
        finally:
            # 未知或已知超额会在token账落盘后抛出，HTTP账仍保存同一观察结果。
            finish_request(root,http_attempt,'responded' if usage is not None else 'failed',usage)
    # 同一局部认证值贯通请求头及保全扫描；从不保存认证值。
    gate=None if responses else SSEEvidenceGate(evidence,auth_secret,settle,request_id=request.request_id)
    try:
        # 模拟分支不读环境；真实分支必须使用上层核实过的网络策略和客户端。
        if before_send is not None:before_send()
        context=(httpx.Client(transport=transport,trust_env=False,follow_redirects=False,timeout=runtime.timeout)
                 if client_factory is None else client_factory(endpoint=endpoint,timeout=runtime.timeout))
        with context as client:
            http_attempt=reserve_request(root,runtime.provider,request.request_id)
            token_attempt=token_transport.reserve(root,runtime.provider,request.request_id,payload,expected_budget_id=binding.budget_id)
            if execution_mode=='live_explicit':
                # 调用stream前记录可能已经发送；连接失败也不能填为零消费。
                route_path=evidence/'route.json'
                route=json.loads(route_path.read_text())
                route.update(actual_network_http=1,http_count_kind='attempted_may_have_sent')
                route_path.write_text(json.dumps(route))
            with client.stream('POST',endpoint,json=payload,headers=runtime.request_headers(task_id,request,auth_secret),follow_redirects=False) as response:
                if responses:
                    chunks=[];size=0;interrupted=False
                    try:
                        for chunk in response.iter_bytes():
                            size+=len(chunk)
                            if size>MAX_BYTES:
                                interrupted=True;break
                            chunks.append(chunk)
                    except Exception:
                        # 完整合法JSON已含usage时，后续断流不抹去可核消费。
                        interrupted=True
                    result=_responses(b''.join(chunks),evidence,settle,response.status_code,scan_secret=auth_secret,interrupted=interrupted)
                else:
                    gate.consume(response.iter_bytes(),http_status=response.status_code)
                    result=gate.result
        token_lineage.verify(binding.lineage_path,binding.lineage_sha256)
        if not result or not result.get('execution_allowed'):
            raise ControlledTransportError('controlled_response_not_ready')
        # 只在安全保全与连续账复核后让正常运行时消费已扫描派生结构。
        body=read_verified_response(evidence,evidence_identity,result)
        message=body['choices'][0]['message'];text=message.get('content') or '';calls=message.get('tool_calls') or []
        merged={'text':text,'tool_calls':calls,'usage':result['usage'],
                'reasoning_content':message.get('reasoning_content') or '',
                'transport_provider':binding.channel,'transport_model':binding.model,
                'response_evidence_path':str(evidence),'mode':execution_mode,'actual_network_http':int(execution_mode=='live_explicit')}
        output=runtime._finish(task_id,request,text,calls,merged)
        if request.on_delta and text:request.on_delta(text)
        return output
    except Exception as exc:
        if token_attempt is not None and not settlement_called:
            settle(None)
        if isinstance(exc,TaskBudgetError):raise
        raise ControlledTransportError('controlled_transport_failed') from None
    # 取消等BaseException不释放预约；pending在下一次合同核对时阻断。
