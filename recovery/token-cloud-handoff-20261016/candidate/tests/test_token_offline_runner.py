"""只读真实结构的合成离线链，绝不发送HTTP或执行生成工具。"""
import json
import pytest
from backend.app.runtime import task_budget as b,token_lineage as l
from backend.app.runtime.token_offline_runner import run_fixture,FIXTURE_SECRET


@pytest.fixture
def bound(tmp_path):
    """研究前缀与空合成子账绑定，不引用真实授权。"""
    root=tmp_path/'execution';root.mkdir();state=b.initialize(root,total_tokens=10000,http_limit=4,max_output_tokens=100)
    source=tmp_path/'source.json';source.write_bytes((root/b.STATE_PATH).read_bytes())
    report=tmp_path/'report.json';report.write_text(json.dumps({'child_budget':state,'cumulative_http':73,'cumulative_known_tokens':2746096,'cumulative_known_input_tokens':2361313,'cumulative_known_output_tokens':384783,'historical_unknown':3,'historical_nonactual_holds':219060}))
    receipt=l.create_contract(tmp_path/'contract.json',execution_root=root,source_budget=source,source_report=report,research_limit=10000000)
    return root,receipt


def sse(content='ok',done=True,usage=True):
    """生成明确终态SSE而不模拟凭据读取。"""
    event={'choices':[{'index':0,'delta':{'content':content},'finish_reason':'stop'}]}
    if usage:event['usage']={'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}
    return ('data: '+json.dumps(event)+'\n\n'+('data: [DONE]\n\n' if done else '')).encode()


def run(bound,raw,**kw):
    """固定生产预算适配入口，传入的只有字节fixture。"""
    root,r=bound
    return run_fixture(r['path'],r['sha256'],request_id='fixture-1',payload={'model':'fixture','messages':[],'max_tokens':100},response_bytes=raw,**kw)


def test_sse_chain_preserves_exact_wire_and_counts_once(bound):
    """预算与完整响应保全都通过才接受fixture，仍无生成代码执行。"""
    root,_=bound;raw=sse();out=run(bound,raw)
    assert out['fixture_accepted'] and out['actual_network_http']==0 and not out['generated_code_executed']
    assert out['new_simulated_known_tokens']==12 and out['historical_unknown']==3
    assert (root/'offline-response-evidence/fixture-1/response/response-received.sse').read_bytes()==raw


def test_unsafe_response_is_charged_but_never_accepted(bound):
    """已知usage不因凭据回显消失；响应不得作为可执行结果。"""
    root,_=bound;out=run(bound,sse(FIXTURE_SECRET))
    assert not out['fixture_accepted'] and b.load(root)['known_tokens']==12
    for p in (root/'offline-response-evidence').rglob('*'):
        if p.is_file():assert FIXTURE_SECRET.encode() not in p.read_bytes()


def test_missing_done_preserves_known_usage_and_blocks_execution(bound):
    """终态不完整不能靠usage存在而执行。"""
    root,_=bound;out=run(bound,sse(done=False))
    assert not out['fixture_accepted'] and b.load(root)['known_tokens']==12


def test_new_unknown_stops_contract_even_with_old_unknown(bound):
    """历史3unknown不放行新的未知响应。"""
    root,_=bound
    with pytest.raises(l.LineageError,match='new_unknown'):run(bound,sse(usage=False))
    assert b.load(root)['attempts'][0]['actual_tokens'] is None


def test_no_live_switch_or_transport_is_accepted(bound):
    """接口不接受live开关，真实请求不能混入fixture通道。"""
    with pytest.raises(TypeError):run(bound,sse(),live=True)
    assert b.load(bound[0])['http_attempts']==0


def test_duplicate_request_does_not_repeat_reservation(bound):
    """一次fixture证据根排他创建，重启不清计数。"""
    run(bound,sse())
    with pytest.raises(FileExistsError):run(bound,sse())
    assert b.load(bound[0])['http_attempts']==1


def test_responses_json_keeps_original_entity_and_reasoning_once(bound):
    """Responses原JSON与派生包分开，输出含思考不二加。"""
    root,r=bound;raw=json.dumps({'object':'response','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}],'usage':{'input_tokens':10,'output_tokens':3,'total_tokens':13,'output_tokens_details':{'reasoning_tokens':2}}},indent=3).encode()
    out=run_fixture(r['path'],r['sha256'],request_id='responses-1',payload={'model':'fixture','input':[],'max_output_tokens':100},response_bytes=raw,response_format='responses_json')
    assert out['fixture_accepted'] and b.load(root)['known_tokens']==13
    p=root/'offline-response-evidence/responses-1/response'
    assert (p/'response-received.json').read_bytes()==raw
    assert json.loads((p/'manifest.json').read_text())['received_format']=='json'


def test_responses_unencodable_text_keeps_observed_usage(bound):
    """合法JSON孤立代理字符不能使已观察用量丢失，也不能作为安全响应。"""
    root,r=bound
    raw=json.dumps({'object':'response','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'\ud800'}]}],'usage':{'input_tokens':10,'output_tokens':3,'total_tokens':13}}).encode()
    out=run_fixture(r['path'],r['sha256'],request_id='unicode-1',payload={'model':'fixture','input':[],'max_output_tokens':100},response_bytes=raw,response_format='responses_json')
    assert not out['fixture_accepted'] and b.load(root)['known_tokens']==13
