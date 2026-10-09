"""受控搜索、分页、实际读取范围及接力可见性回归。"""
import pytest
from pathlib import Path
from backend.app.runtime import repair_session as session
from backend.app.runtime.contracts import ToolCall
from backend.app.runtime.worker import duplicate_read_error
from tests.test_repair_runtime import attempt
from tests.test_repair_session import prepare


def test_search_pagination_and_stale_version(attempt):
    """每页最多五十条，版本变更不能继续旧游标。"""
    root, _, _, _, _ = attempt
    (root/'product/long.js').write_text('needle\n'*60)
    tools=prepare(root)
    first=tools._search('needle')
    assert len(first['matches'])==50 and first['next_cursor']==50
    second=tools._search('needle',first['next_cursor'],first['version'])
    assert len(second['matches'])==10 and second['next_cursor'] is None
    assert [m['line'] for m in first['matches']+second['matches']]==list(range(1,61))
    (root/'product/long.js').write_text('new needle')
    with pytest.raises(ValueError,match='version_changed'):
        tools._search('needle',50,first['version'])


@pytest.mark.parametrize('query,cursor', [('',0),('x',True),('x',-1),('x'*201,0)])
def test_invalid_search(attempt,query,cursor):
    """无效查询和游标不能进入扫描。"""
    root, _, _, _, _=attempt
    with pytest.raises(ValueError,match='parameters_invalid'):
        prepare(root)._search(query,cursor)


def test_scoped_search_filters_authorized_files_and_binds_cursor(attempt):
    """范围内分页完整，换范围或修改范围内文件拒绝旧游标。"""
    root, _, _, _, _ = attempt
    (root/'product/scoped').mkdir()
    (root/'product/scoped/a.js').write_text('needle\n'*60)
    (root/'product/out.js').write_text('needle')
    tools = prepare(root)
    first = tools._search('needle', path='product/scoped')
    assert len(first['matches']) == 50
    assert all(m['path'] == 'product/scoped/a.js' for m in first['matches'])
    second = tools._search('needle', 50, first['version'], path='product/scoped')
    assert len(second['matches']) == 10
    with pytest.raises(ValueError, match='version_changed'):
        tools._search('needle', 50, first['version'], path='product/scoped/a.js')
    (root/'product/out.js').write_text('unrelated change')
    assert len(tools._search('needle', 50, first['version'], path='product/scoped')['matches']) == 10
    (root/'product/scoped/a.js').write_text('changed needle')
    with pytest.raises(ValueError, match='version_changed'):
        tools._search('needle', 50, first['version'], path='product/scoped')
    assert tools.execute(ToolCall('scoped', 'search', {'query':'needle', 'path':'product/scoped/a.js'})).status == 'succeeded'


@pytest.mark.parametrize('path', ['', '.', '..', '../product', '/tmp', 'product/missing.js', 'evidence/private.json', 1])
def test_search_rejects_invalid_or_unauthorized_scope(attempt, path):
    """无效及无授权文件的范围不得扩大搜索权限。"""
    root, _, _, _, _ = attempt
    (root/'evidence/private.json').write_text('needle')
    with pytest.raises(ValueError):
        prepare(root)._search('needle', path=path)


def test_search_rejects_symlink_scope(attempt):
    """即使链接指向授权文件，也不能通过别名绕过范围校验。"""
    root, _, _, _, _ = attempt
    (root/'product/real.js').write_text('needle')
    (root/'alias').symlink_to(root/'product')
    with pytest.raises(ValueError, match='scope_invalid'):
        prepare(root)._search('needle', path='alias/real.js')


def test_search_scope_literal_snippet_and_binary(attempt):
    """字面搜索不执行正则，禁止任务外文件，跳过二进制明确告知。"""
    root, _, _, _, _=attempt
    (root/'evidence/private.json').write_text('only-outside')
    (root/'product/text.js').write_text('a'*500+'literal.*'+'b'*500)
    (root/'product/binary.dat').write_bytes(b'\x00literal.*')
    tools=prepare(root)
    assert tools._search('only-outside')['matches']==[]
    result=tools._search('literal.*')
    assert len(result['matches'])==1
    assert result['matches'][0]['snippet_truncated']
    assert 'literal.*' in result['matches'][0]['snippet']
    assert result['skipped_non_text_files']==['product/binary.dat']
    assert result['content_is_full_file'] is False
    assert tools.execute(ToolCall('search','search',{'query':'literal.*'})).status=='succeeded'


def test_default_preview_does_not_claim_whole_file_and_missing_range_allowed(attempt):
    """默认预览只登记两百行，全文与未覆盖范围仍可读。"""
    root, _, _, _, _=attempt
    (root/'product/long.js').write_text('line\n'*250)
    tools=prepare(root)
    action=ToolCall('read','read',{'path':'product/long.js'})
    result=tools.execute(action)
    assert result.output['end_line']==200 and result.output['truncated']
    history=[{'action':action.__dict__,'result':result.__dict__}]
    context={'reasoning_tool_history':history}
    assert duplicate_read_error(action,history,context,tools)
    full=ToolCall('full','read',{'path':'product/long.js','start_line':1,'end_line':250})
    assert duplicate_read_error(full,history,context,tools) is None
    covered=ToolCall('covered','read',{'path':'product/long.js','start_line':1,'end_line':100})
    assert duplicate_read_error(covered,history,context,tools)
    missing=ToolCall('missing','read',{'path':'product/long.js','start_line':201,'end_line':250})
    assert duplicate_read_error(missing,history,context,tools) is None
    assert duplicate_read_error(covered,history,{},tools) is None
    (root/'product/long.js').write_text('changed\n'*250)
    assert duplicate_read_error(covered,history,context,tools) is None


def test_visible_adjacent_ranges_merge_but_search_does_not_cover_read(attempt):
    """相邻已知范围合并去重，搜索片段不冒充完整代码。"""
    root, _, _, _, _=attempt
    (root/'product/ranges.js').write_text('line\n'*10)
    tools=prepare(root)
    history=[]
    for i,(start,end) in enumerate([(1,5),(6,10)]):
        call=ToolCall(str(i),'read',{'path':'product/ranges.js','start_line':start,'end_line':end})
        history.append({'action':call.__dict__,'result':tools.execute(call).__dict__})
    request=ToolCall('whole','read',{'path':'product/ranges.js'})
    assert duplicate_read_error(request,history,{'reasoning_tool_history':history},tools)
    search=ToolCall('search','search',{'query':'line'})
    found=[{'action':search.__dict__,'result':tools.execute(search).__dict__}]
    assert duplicate_read_error(request,found,{'reasoning_tool_history':found},tools) is None
    assert duplicate_read_error(request,history,{},tools) is None


def test_text_only_thinking_survives_worker_restore(attempt,monkeypatch):
    """未调用工具的思考也必须原样恢复，普通结束文本不能提交。"""
    from backend.app.runtime.contracts import ModelResult
    from backend.app.runtime.model import build_messages
    root,db,task,_,_=attempt
    tools=prepare(root)
    from backend.app.runtime import worker
    run=worker.create_step_run(db,task)
    db.commit()
    seen=[]
    class Fixed:
        """完全固定的协议响应，不进行 HTTP 请求。"""
        provider='deepseek'
        model_name='fixed-text-restore'
        def build_payload(self,request):
            return {'messages':build_messages(request,include_reasoning=True)}
        def call(self,task_id,request):
            seen.append(self.build_payload(request)['messages'])
            if len(seen)==1:
                return ModelResult(request.request_id,1,'我完成了',[],'completed',{'reasoning_content':'text-only-thought'})
            if len(seen)==2:
                raise RuntimeError('controlled_pause')
            assert any(m.get('reasoning_content')=='text-only-thought' for m in seen[-1])
            return ModelResult(request.request_id,1,'',[ToolCall('decision','request_decision',
                {'question':'请选择方案','impact':'影响交互','proposal':'保持原样'})],'tool_calls',{'reasoning_content':'decision-thought'})
    from backend.app.runtime import worker
    monkeypatch.setattr(worker,'create_model_runtime',lambda *a:Fixed())
    context={'repair_session':True,'session_id':'fixture','unit_file_scope':tools.self_test_files}
    kwargs={'history_key':'text-restore','tool_schemas':[session.DECISION_SCHEMA],
            'stop_when':lambda:session.repair.load(root)['state']=='waiting_decision'}
    with pytest.raises(RuntimeError,match='model_transport_failed'):
        worker.model_tool_loop(db,task,run,'fixed','task',context,tools,**kwargs)
    assert tools.submitted_hashes is None
    worker.model_tool_loop(db,task,run,'fixed','task',context,tools,**kwargs)
    assert len(seen)==3 and session.repair.load(root)['state']=='waiting_decision'


def test_three_same_reads_allowed_when_file_version_changes(attempt,monkeypatch):
    """合法新版本读取不受历史相同动作次数误拦截。"""
    from backend.app.runtime import worker
    from backend.app.runtime.contracts import ModelResult
    from backend.app.runtime.model import build_messages
    root,db,task,_,_=attempt
    (root/'product/version.js').write_text('version-0')
    tools=prepare(root)
    run=worker.create_step_run(db,task);db.commit()
    calls=[]
    class Fixed:
        """模拟两次外部版本更新，所有响应均在本地生成。"""
        provider='deepseek'
        model_name='fixed-version-read'
        def build_payload(self,request):
            return {'messages':build_messages(request,include_reasoning=True)}
        def call(self,task_id,request):
            calls.append(request)
            if len(calls)<=3:
                (root/'product/version.js').write_text(f'version-{len(calls)}')
                actions=[ToolCall(str(len(calls)),'read',{'path':'product/version.js'})]
            else:
                actions=[ToolCall('decision','request_decision',{'question':'确认方案','impact':'影响实现','proposal':'保持业务'})]
            return ModelResult(request.request_id,1,'',actions,'tool_calls',{'reasoning_content':'fixed'})
    monkeypatch.setattr(worker,'create_model_runtime',lambda *a:Fixed())
    worker.model_tool_loop(db,task,run,'fixed','task',{'repair_session':True,'session_id':'fixture',
        'unit_file_scope':tools.self_test_files},tools,history_key='version-read',
        tool_schemas=[session.DECISION_SCHEMA],stop_when=lambda:session.repair.load(root)['state']=='waiting_decision')
    import json
    history=json.loads(Path(run.checkpoint_path).read_text())
    reads=[e['result'] for e in history if e.get('action',{}).get('tool_name')=='read']
    assert len(reads)==3 and all(r['status']=='succeeded' for r in reads)
    assert [r['output']['content'] for r in reads]==['version-1','version-2','version-3']
