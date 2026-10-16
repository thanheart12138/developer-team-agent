"""响应保全离线反例；仅假密钥/字节流，不发HTTP。"""
import io
import json
from unittest.mock import patch
import pytest
from backend.app.runtime import response_evidence as e

SECRET='dummy-quote"\\secret'
USAGE={'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}


def raw(content='safe code', finish='tool_calls', usage=USAGE):
    # 同时覆盖工具参数中的代码正文和模型响应结构。
    return json.dumps({'usage':usage,'choices':[{'finish_reason':finish,'message':{'tool_calls':[
        {'id':'1','type':'function','function':{'name':'write','arguments':json.dumps({'path':'product/a.js','content':content})}}]}}]},indent=3).encode()


def test_exact_received_and_reencoded_preserved(tmp_path):
    # 收到字节与重编码JSON分别命名，参数与代码完整留存可校验。
    calls=[]; data=raw();result=e.capture(tmp_path,data,[SECRET],calls.append)
    assert result['execution_allowed'] and calls==[USAGE]
    assert (tmp_path/'response/response-received.json').read_bytes()==data
    assert (tmp_path/'response/response.json').read_bytes()!=data
    assert 'safe code' in (tmp_path/'response/tool-actions.json').read_text()
    assert e.recover(tmp_path)['evidence_status']=='complete'
    assert not e.recover(tmp_path)['execution_allowed']


@pytest.mark.parametrize('form',['value','key','escaped','base64','url','authorization'])
def test_secret_echo_never_written_and_blocks_execution(tmp_path,form):
    # 用假认证值反证嵌套、转义与常见编码回显。
    import base64
    from urllib.parse import quote
    content={'value':SECRET,'key':json.dumps({SECRET:'x'}),'escaped':json.dumps(SECRET),
             'base64':base64.b64encode(SECRET.encode()).decode(),'url':quote(SECRET,safe=''),
             'authorization':None}[form]
    data=raw(content)
    if form=='authorization':
        body=json.loads(data);body['Authorization']='Bearer other-value';data=json.dumps(body).encode()
    calls=[];result=e.capture(tmp_path,data,[SECRET],calls.append)
    assert not result['execution_allowed'] and result['evidence_status']=='redacted_unsafe'
    assert not (tmp_path/'response/response-received.json').exists()
    assert calls==[USAGE]
    for p in tmp_path.rglob('*'):
        if p.is_file():assert SECRET.encode() not in p.read_bytes()
    assert e.recover(tmp_path)['evidence_status']=='redacted_unsafe'


@pytest.mark.parametrize('finish',['length','content_filter',None])
def test_truncated_incomplete_preserved_but_not_executable(tmp_path,finish):
    # 截断证据保留，当前usage照常记账，不放行模型工具。
    calls=[];result=e.capture(tmp_path,raw(finish=finish),[SECRET],calls.append)
    assert result['evidence_status']=='incomplete_response' and not result['execution_allowed']
    assert calls==[USAGE] and (tmp_path/'response/response-received.json').exists()


def test_oversize_usage_independent_and_no_partial_payload(tmp_path):
    # 传输层独立得到的usage在正文超限时仍结算。
    calls=[];result=e.capture_stream(tmp_path,io.BytesIO(b'x'*501),[SECRET],calls.append,max_bytes=500,observed_usage=USAGE)
    assert not result['execution_allowed'] and calls==[USAGE]
    assert not (tmp_path/'response').exists()
    assert json.loads((tmp_path/'usage-receipt.json').read_text())['actual_known']


@pytest.mark.parametrize('value',[None,{'prompt_tokens':True,'completion_tokens':20,'total_tokens':21},{'prompt_tokens':1,'completion_tokens':2,'total_tokens':4}])
def test_invalid_usage_blocks_without_discarding_safe_evidence(tmp_path,value):
    # 缺失或畸形用量不能作零，安全正文仍可保全。
    calls=[];result=e.capture(tmp_path,raw(usage=value),[SECRET],calls.append)
    assert not result['execution_allowed'] and calls==[None]
    assert (tmp_path/'response/response.json').exists()


def test_usage_conflict_and_invalid_json(tmp_path):
    # 冲突不选有利数字，原样阻断并保留缺证状态。
    calls=[];result=e.capture(tmp_path,raw(),[SECRET],calls.append,observed_usage={**USAGE,'total_tokens':31})
    assert calls==[None] and result['evidence_status']=='usage_conflict_or_invalid'


def test_atomic_write_failure_retains_usage_and_no_bundle(tmp_path):
    # 写正文失败不能撤销独立结算，半成品不出现为完整包。
    original=e._write;calls=[]
    def fail(path,data):
        if path.name=='response.json':raise OSError('simulated')
        original(path,data)
    with patch.object(e,'_write',side_effect=fail):result=e.capture(tmp_path,raw(),[SECRET],calls.append)
    assert calls==[USAGE] and not result['execution_allowed']
    assert (tmp_path/'usage-receipt.json').exists() and not (tmp_path/'response').exists()
    assert e.recover(tmp_path)['evidence_status']=='missing_or_corrupt'


def test_restart_cannot_overwrite_or_recreate(tmp_path):
    # 完整或中断后均禁止再次capture，恢复仅核验，不补造响应。
    e.capture(tmp_path,raw(),[SECRET],lambda _:None)
    with pytest.raises(FileExistsError):e.capture(tmp_path,raw('different'),[SECRET],lambda _:None)
    (tmp_path/'response/response.json').write_text('{}')
    assert e.recover(tmp_path)['evidence_status']=='missing_or_corrupt'


def test_settlement_error_fails_closed(tmp_path):
    # 账本失败与响应缺证分开，不能因有正文执行。
    def fail(_):raise OSError('simulated')
    result=e.capture(tmp_path,raw(),[SECRET],fail)
    assert not result['execution_allowed'] and result['evidence_status']=='usage_settlement_failed'


@pytest.mark.parametrize('member',['manifest.json','response.json','tool-actions.json','response-received.json'])
def test_recovery_rejects_symlink_members(tmp_path,member):
    # 同FD的O_NOFOLLOW拒绝所有包成员符号链。
    e.capture(tmp_path,raw(),[SECRET],lambda _:None)
    p=tmp_path/'response'/member;data=p.read_bytes();p.unlink()
    outside=tmp_path/'outside';outside.write_bytes(data);p.symlink_to(outside)
    assert e.recover(tmp_path)['evidence_status']=='missing_or_corrupt'


@pytest.mark.parametrize('member',['response/manifest.json','capture-status.json','response/response.json'])
def test_recovery_reads_bounded(tmp_path,member):
    # 恢复对元数据和内容均有严格读上限。
    e.capture(tmp_path,raw(),[SECRET],lambda _:None)
    (tmp_path/member).write_bytes(b'x'*(e.MAX_BYTES+1))
    assert e.recover(tmp_path)['evidence_status']=='missing_or_corrupt'


def test_root_replacement_does_not_redirect_writes(tmp_path):
    # usage回调期间路径被替换，固定FD仍写原根，不跟随新链接。
    root=tmp_path/'owned';root.mkdir();old=tmp_path/'original';other=tmp_path/'other';other.mkdir()
    def swap(_):
        root.rename(old);root.symlink_to(other,target_is_directory=True)
    result=e.capture(root,raw(),[SECRET],swap)
    assert not result['execution_allowed'] and result['root_identity_changed']
    assert (old/'response/response.json').is_file() and list(other.iterdir())==[]
    assert e.recover(root)['evidence_status']=='missing_or_corrupt'


def test_settlement_failure_not_relabelled_by_receipt_failure(tmp_path):
    # 双重错误保持独立结算失败事实。
    def settle(_):raise OSError('settlement')
    original=e._write
    def write(member,data):
        if member.name=='usage-receipt.json':raise OSError('receipt')
        original(member,data)
    with patch.object(e,'_write',side_effect=write):result=e.capture(tmp_path,raw(),[SECRET],settle)
    assert result['settlement_succeeded'] is False
    assert not result['execution_allowed']
