"""只接受离线响应字节的实验入口；没有网络客户端、凭据读取或live开关。"""
import json
import re
from pathlib import Path
from . import token_lineage, token_transport
from .response_evidence import capture, encode, parse, usage_numbers, MAX_BYTES
from .sse_response_evidence import SSEEvidenceGate, ResponseEvidenceError

FIXTURE_SECRET='offline-fixture-only-scan-sentinel'


def _responses(raw, root, sink, status, *, scan_secret, interrupted=False):
    """严格解析Responses，使用调用方认证扫描值保全原实体与派生结构。"""
    body={};usage=None;complete=False;scan='safe';calls=[];text=[];call_ids=set()
    try:
        if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:
            raise ValueError('offline_response_size')
        body=parse(raw)
        source=body.get('usage') if isinstance(body,dict) else None
        if isinstance(source,dict):
            usage=usage_numbers({'prompt_tokens':source.get('input_tokens'),'completion_tokens':source.get('output_tokens'),'total_tokens':source.get('total_tokens')})
        complete=isinstance(body,dict) and body.get('object')=='response' and body.get('status')=='completed' and not body.get('error')
        if not isinstance(body.get('output'),list) or not body['output']:
            complete=False
        for item in body.get('output',[]):
            if item.get('type')=='function_call':
                arguments=item.get('arguments')
                if not isinstance(arguments,str) or not isinstance(parse(arguments),dict):
                    raise ValueError('offline_response_arguments_invalid')
                if not all(isinstance(item.get(k),str) and item[k] for k in ('call_id','name')):
                    raise ValueError('offline_response_tool_invalid')
                if item['call_id'] in call_ids:
                    raise ValueError('offline_response_duplicate_call_id')
                call_ids.add(item['call_id'])
                calls.append({'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':arguments}})
            elif item.get('type')=='message':
                for part in item['content']:
                    if part.get('type')!='output_text' or not isinstance(part.get('text'),str):
                        raise ValueError('offline_response_content_invalid')
                    text.append(part['text'])
            elif item.get('type')!='reasoning':
                raise ValueError('offline_response_output_invalid')
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):
        complete=False;scan='unscannable'
    if interrupted:
        complete=False;scan='unscannable'
    projected={'usage':usage,'original_response':body,'choices':[{'finish_reason':'tool_calls' if complete and calls else 'stop' if complete else None,
               'message':{'content':''.join(text),'tool_calls':calls}}]}
    # 原wire与派生结构分开命名；已知usage先落盘，非法/泄露内容不得执行。
    try:
        encoded=encode(projected)
    except (UnicodeError,ValueError,TypeError,RecursionError):
        # 不能重编码的正文不妨碍保存已核对usage；禁止原wire作为安全结果。
        scan="unscannable"
        encoded=encode({"usage":usage,"choices":[{"finish_reason":None,"message":{"content":"","tool_calls":[]}}]})
    result=capture(root,encoded,[scan_secret],sink,observed_usage=usage,http_status=status,
                   received_entity=raw,received_entity_scan=scan,received_entity_format='json',
                   received_entity_complete=not interrupted)
    return result


def run_fixture(contract_path, contract_sha256, *, request_id, payload, response_bytes,
                response_format='chat_sse', http_status=200):
    """在隔离副本串起合同、真实预算预约、响应保全；不执行生成代码。"""
    if response_format not in {'chat_sse','responses_json'} or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request_id):
        raise ValueError('offline_fixture_invalid')
    before=token_lineage.verify(contract_path,contract_sha256)
    root=Path(before['contract']['execution_root'])
    parent=root/'offline-response-evidence'
    if parent.is_symlink():
        raise ValueError('offline_evidence_parent_invalid')
    parent.mkdir(mode=0o700,exist_ok=True)
    evidence=parent/request_id;evidence.mkdir(mode=0o700,exist_ok=False)
    body=token_transport.prepare(root,payload)
    attempt=None
    def settle(usage):
        """使用实际观察usage一次结算，不把模拟HTTP计作新真实调用。"""
        token_transport.settle(root,attempt,'responded' if usage is not None else 'failed',usage)
    gate=SSEEvidenceGate(evidence,FIXTURE_SECRET,settle,request_id=request_id) if response_format=='chat_sse' else None
    attempt=token_transport.reserve(root,'openrouter' if response_format=='responses_json' else 'deepseek',request_id,body,expected_budget_id=before['budget_id'])
    failure=None
    if gate is not None:
        try:
            gate.consume(iter([response_bytes]),http_status=http_status)
        except ResponseEvidenceError as exc:
            failure=exc.code
        result=gate.result
    else:
        result=_responses(response_bytes,evidence,settle,http_status,scan_secret=FIXTURE_SECRET)
    # verify会把新增unknown当阻塞；历史unknown继续单列，不补零。
    after=token_lineage.verify(contract_path,contract_sha256)
    report={'schema':'token-offline-fixture-result-v1','mode':'offline_fixture','actual_network_http':0,
            'generated_code_executed':False,'fixture_accepted':bool(result and result.get('execution_allowed')),
            'evidence_status':result.get('evidence_status') if result else 'absent','failure':failure,
            'evidence_path':str(evidence),'budget_id':after['budget_id'],'new_simulated_attempts':after['new_http'],
            'new_simulated_known_tokens':after['new_known'],'historical_unknown':after['historical_unknown'],
            'research_known_with_simulated_delta':after['research_known'],'live_authorized':False}
    (evidence/'offline-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report
