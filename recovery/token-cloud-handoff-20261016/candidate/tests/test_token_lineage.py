"""连续账合同只用合成文件；不改真实报告或原账。"""
import json
from pathlib import Path
import pytest
from backend.app.runtime import task_budget as b, token_lineage as l


@pytest.fixture
def case(tmp_path):
    """构造研究已含子账成本的历史前缀。"""
    root=tmp_path/'execution';root.mkdir();b.initialize(root,total_tokens=1000,http_limit=8,max_output_tokens=10)
    attempt=b.reserve(root,provider='fixture',request_id='old',input_estimate=1,max_output_tokens=1)
    b.finish(root,attempt,status='responded',usage={'prompt_tokens':70,'completion_tokens':30,'total_tokens':100})
    source=tmp_path/'original-budget.json';source.write_bytes((root/b.STATE_PATH).read_bytes())
    report=tmp_path/'report.json';report.write_text(json.dumps({'cumulative_http':73,'cumulative_known_tokens':10000,'cumulative_known_input_tokens':8000,'cumulative_known_output_tokens':2000,'historical_unknown':3,'historical_nonactual_holds':200,'child_budget':b.load(root)}))
    receipt=l.create_contract(tmp_path/'contract.json',execution_root=root,source_budget=source,source_report=report,research_limit=20000)
    return root,source,report,receipt


def test_continuous_accounting_does_not_count_child_prefix_twice(case):
    """原子账100已含研究10000，新消费只加差值。"""
    root,source,report,r=case
    assert l.verify(r['path'],r['sha256'])['research_known']==10000
    a=b.reserve(root,provider='fixture',request_id='new',input_estimate=1,max_output_tokens=1)
    b.finish(root,a,status='responded',usage={'total_tokens':12})
    v=l.verify(r['path'],r['sha256']);assert v['research_known']==10012 and v['research_http']==74
    assert v['historical_unknown']==3 and v['historical_nonactual_holds']==200
    assert not v['actual_total_exact'] and not v['live_authorized']


def test_new_unknown_blocks_despite_historical_unknown_allowance(case):
    """历史未知明确保留不等于允许新增未知。"""
    root,_,_,r=case;b.reserve(root,provider='fixture',request_id='new',input_estimate=1,max_output_tokens=1)
    with pytest.raises(l.LineageError,match='new_unknown'):l.verify(r['path'],r['sha256'])


@pytest.mark.parametrize('target',['source','report','contract','limits','old_attempt'])
def test_contract_and_old_sources_are_immutable(case,target):
    """修改来源、额度或已计消费都拒绝，不能凭新文件名清账。"""
    root,source,report,r=case
    if target in {'source','report','contract'}:
        p={'source':source,'report':report,'contract':Path(r['path'])}[target];p.write_bytes(p.read_bytes()+b' ')
    else:
        state=b.load(root)
        if target=='limits':
            state['limits']['total_tokens']+=1
            marker=json.loads((root/b.MARKER_PATH).read_text());marker['limits']=state['limits'];b._write(root/b.MARKER_PATH,marker)
        else:state['attempts'][0]['request_id']='rewritten'
        b._write(root/b.STATE_PATH,state)
    with pytest.raises(b.TaskBudgetError):l.verify(r['path'],r['sha256'])


def test_contract_creation_never_overwrites(case):
    """已经存在的合同保留，不把新的批准覆盖旧来源。"""
    root,source,report,r=case
    with pytest.raises(FileExistsError):l.create_contract(r['path'],execution_root=root,source_budget=source,source_report=report,research_limit=20000)


def test_child_remainder_cannot_exceed_research_remainder(case,tmp_path):
    """研究历史占额参与准入，不能只看子账余量。"""
    root,source,report,r=case
    with pytest.raises(l.LineageError,match='exceeds'):l.create_contract(tmp_path/'bad.json',execution_root=root,source_budget=source,source_report=report,research_limit=10500)


@pytest.mark.parametrize('alias',['same','resolve','hardlink','symlink'])
def test_source_execution_alias_rejected_before_writes(case,tmp_path,alias):
    """直接路径或别名均不得让原账变成可写执行账。"""
    import os
    root,source,report,r=case
    state=root/b.STATE_PATH;before=state.read_bytes()
    if alias=='same':source=state
    elif alias=='resolve':source=state.parent/'..'/state.parent.name/state.name
    else:
        source=tmp_path/('alias-'+alias)
        if alias=='hardlink':os.link(state,source)
        else:source.symlink_to(state)
    destination=tmp_path/'rejected-contract.json'
    with pytest.raises(l.LineageError):
        l.create_contract(destination,execution_root=root,source_budget=source,source_report=report,research_limit=20000)
    assert state.read_bytes()==before and not destination.exists()


def test_execution_replaced_by_source_hardlink_rejected_before_runner(case):
    """使用时重新核对独立性，不能只在创建合同时检查。"""
    import os
    root,source,_,r=case
    state=root/b.STATE_PATH;state.unlink();os.link(source,state)
    before=source.read_bytes()
    with pytest.raises(l.LineageError,match='not_isolated'):l.verify(r['path'],r['sha256'])
    assert source.read_bytes()==before
