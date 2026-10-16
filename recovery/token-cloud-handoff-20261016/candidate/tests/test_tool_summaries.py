"""摘要、查询、上下文窗口及恢复的机制验证，不调用付费模型。"""

import hashlib
import json

import pytest

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime import worker
from backend.app.runtime.contracts import ModelResult, ToolCall
from backend.app.runtime.model import build_messages
from backend.app.runtime.tool_summaries import DETAIL_CHARS, ToolSummaryStore
from backend.app.runtime.tools import ToolRuntime
from backend.app.runtime.unit_workflow import UnitTools


def setup_function():
    # 每个用例使用独立的内存任务状态。
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def task_run(db, root):
    # 创建真实 Worker 可用的任务、阶段与工具运行时。
    task = Task(task_name="summary", cur_step=Step.develop, status=TaskStatus.running, workspace_path=str(root))
    db.add(task)
    db.flush()
    run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                  checkpoint_path=str(root / 'evidence/checkpoint.json'))
    db.add(run)
    db.commit()
    return task, run, ToolRuntime(root)


def execute(db, task, run, tools, call, parent='model-a'):
    # 执行真实工具并返回原始检查点形状，用于验证投影不修改历史。
    result = worker.execute_tool(db, task, run, tools, call, parent, 'default')
    return {'model_request_id':parent, 'history_key':'default', 'action':call.__dict__, 'result':result.__dict__}


def test_write_history_versions_and_historical_detail(tmp_path):
    # 文件当前版本与历史写入原文分别可查，前后哈希来自实际字节。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        first = execute(db, task, run, tools, ToolCall('w1', 'write', {'path':'product/app.js', 'content':'old', 'overwrite':False, 'description':'创建入口'}))
        execute(db, task, run, tools, ToolCall('w2', 'write', {'path':'product/app.js', 'content':'new', 'overwrite':True}), 'model-b')
        store = ToolSummaryStore(tmp_path)
        history = store.file_history('product/app.js')
        assert history['matches_last_record'] is True
        latest, oldest = history['items']
        assert latest['before_hash'] == oldest['after_hash'] == hashlib.sha256(b'old').hexdigest()
        assert latest['after_hash'] == hashlib.sha256(b'new').hexdigest()
        assert oldest['description'] == '创建入口'
        raw = json.loads(store.detail(oldest['summary_id'], 'call')['content'])
        assert raw['call']['parameters']['content'] == 'old'
        assert tools.execute(ToolCall('read', 'read', {'path':'product/app.js'})).output['content'] == 'new'
        store.record(run.id, 'default', 'model-a', ToolCall(**first['action']), tools.execute(ToolCall('r', 'read', {'path':'product/app.js'})), {}, {}, {})
        assert len(store.load()) == 2
        (tmp_path / 'product/app.js').write_text('outside write')
        assert store.file_history('product/app.js')['matches_last_record'] is False


def test_replace_is_current_write_and_failed_replace_keeps_last_success(tmp_path):
    # 局部替换必须进入修改历史和当前写入投影；替换失败不能伪造新版本。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history = [execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/app.js', 'content':'old', 'overwrite':False}))]
        history.append(execute(db, task, run, tools, ToolCall('p', 'replace', {'path':'product/app.js', 'old':'old', 'new':'new'}), 'model-b'))
        store = ToolSummaryStore(tmp_path)
        latest = store.file_history('product/app.js')['items'][0]
        assert latest['tool_name'] == 'replace'
        assert latest['operation'] == 'replace'
        assert latest['before_hash'] == hashlib.sha256(b'old').hexdigest()
        assert latest['after_hash'] == hashlib.sha256(b'new').hexdigest()
        assert store.file_history('product/app.js')['matches_last_record'] is True
        state = worker.build_tool_context(task, run, {}, history, 'default')['tool_summaries'][0]
        assert state['latest_write']['tool_call_id'] == 'p'
        assert state['latest_write']['matches_current_files'] is True
        failed = execute(db, task, run, tools, ToolCall('bad', 'replace', {'path':'product/app.js', 'old':'absent', 'new':'bad'}), 'model-c')
        assert failed['result']['status'] == 'failed'
        assert store.load()[-1]['before_hash'] == hashlib.sha256(b'new').hexdigest()
        assert store.load()[-1]['after_hash'] is None
        assert store.file_history('product/app.js')['items'][0]['tool_call_id'] == 'p'


def test_failed_self_test_remains_failure_after_later_read_and_retest_clears_it(tmp_path):
    # 用真实 Node 失败输出复现摘要误报，后续读取不能清除；同一自测成功才闭合。
    with SessionLocal() as db:
        task, run, runtime = task_run(db, tmp_path)
        path = 'product/check.test.cjs'
        runtime._write(path, "require('node:test')('check',()=>{throw Error('EXPECTED_FAILURE')});", False)
        tools = UnitTools(tmp_path, [path], [path], submission_files=[path], self_test_files=[path], test_files=[path])
        history = [execute(db, task, run, tools, ToolCall('test', 'run_unit_tests', {}))]
        assert history[0]['result']['status'] == 'succeeded'
        assert history[0]['result']['output']['passed'] is False
        store = ToolSummaryStore(tmp_path)
        row = store.load()[-1]
        assert row['status'] == 'failed'
        assert row['exit_code'] == 1
        assert 'EXPECTED_FAILURE' in row['error_excerpt']
        history.append(execute(db, task, run, tools, ToolCall('read', 'read', {'path':path}), 'model-b'))
        context = worker.build_tool_context(task, run, {}, history, 'default')
        assert any(f['summary_id'] == row['summary_id'] for f in context['tool_failures'])
        runtime._write(path, "require('node:test')('check',()=>{});", True)
        history.append(execute(db, task, run, tools, ToolCall('retest', 'run_unit_tests', {}), 'model-c'))
        assert store.load()[-1]['status'] == 'succeeded'
        assert not worker.build_tool_context(task, run, {}, history, 'default')['tool_failures']
        runtime._write('product/other.js', 'unrelated', False)
        context = worker.build_tool_context(task, run, {}, history, 'default')
        assert context['latest_execution_versions'][-1]['matches_current_files'] is True
        runtime._write(path, "require('node:test')('changed',()=>{});", True)
        context = worker.build_tool_context(task, run, {}, history, 'default')
        assert context['latest_execution_versions'][-1]['matches_current_files'] is False


def test_partial_read_summary_does_not_claim_complete_file(tmp_path):
    # 成功返回一个行区间不等于读取全文件，摘要必须保留实际范围。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        tools._write('product/a.js', 'first\nsecond\nthird\n', False)
        history = [execute(db, task, run, tools, ToolCall('partial', 'read', {'path':'product/a.js', 'start_line':1, 'end_line':2}))]
        state = worker.build_tool_context(task, run, {}, history, 'default')['tool_summaries'][0]['latest_read']
        assert state['complete'] is False
        assert (state['start_line'], state['end_line'], state['total_lines']) == (1, 2, 3)
        history.append(execute(db, task, run, tools, ToolCall('all', 'read', {'path':'product/a.js', 'start_line':1, 'end_line':3}), 'model-b'))
        state = worker.build_tool_context(task, run, {}, history, 'default')['tool_summaries'][0]['latest_read']
        assert state['complete'] is True


def test_one_model_call_has_multiple_tools_and_system_parent_is_null(tmp_path):
    # 批次按父请求关联，程序执行不伪造模型父调用。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        for index in range(2):
            execute(db, task, run, tools, ToolCall(f'w{index}', 'write', {'path':f'product/{index}.js', 'content':'x', 'overwrite':False}))
        worker.execute_tool(db, task, run, tools, ToolCall('system-read', 'read', {'path':'product/0.js'}))
        store = ToolSummaryStore(tmp_path)
        assert [row['tool_call_id'] for row in store.model_call('model-a')['items']] == ['w0', 'w1']
        assert store.load()[-1]['parent_model_call_id'] is None


def test_write_batches_become_file_states_without_fulltext(tmp_path):
    # 所有写入批次仅投影有效文件状态，原始检查点保持完整。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history = [execute(db, task, run, tools, ToolCall('old', 'write', {'path':'product/old.js', 'content':'OLD_FULLTEXT' * 2000, 'overwrite':False}))]
        for index in range(2):
            history.append(execute(db, task, run, tools, ToolCall(f'new{index}', 'write', {'path':f'product/new{index}.js', 'content':'current', 'overwrite':False}), 'model-b'))
        value = worker.build_tool_context(task, run, {}, history, 'default')
        assert value['tool_history'] == []
        assert len(value['tool_summaries']) == 3
        assert value['recent_model_call_id'] == 'model-b'
        assert 'OLD_FULLTEXT' not in json.dumps(value)
        assert 'OLD_FULLTEXT' in history[0]['action']['parameters']['content']
        assert len(value['product_file_manifest']) == 3


def test_latest_snapshot_refreshes_without_write_history(tmp_path):
    # 写入历史不再提供全文，当前快照必须独立刷新。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history = [execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/app.js', 'content':'new', 'overwrite':False}))]
        value = worker.build_tool_context(task, run, {'current_product_files':{'product/app.js':'old'}, 'existing_product_files':[]}, history, 'default')
        assert value['current_product_files'] == {'product/app.js':'new'}
        assert value['existing_product_files'] == ['product/app.js']
        assert value['current_files_omitted_as_recent_fulltext'] == 0


def test_failed_commands_survive_unrelated_success_and_success_becomes_stale(tmp_path):
    # 成功的无关命令不能清除失败，文件修改后旧执行结果不能验证新版本。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/app.js', 'content':'x', 'overwrite':False}))
        fail = execute(db, task, run, tools, ToolCall('fail', 'exec', {'action':'run', 'command':'exit 1'}))
        success = execute(db, task, run, tools, ToolCall('ok', 'exec', {'action':'run', 'command':'exit 0'}), 'model-b')
        value = worker.build_tool_context(task, run, {}, [fail, success], 'default')
        assert len(value['tool_failures']) == 1
        assert all(row['matches_current_files'] for row in value['latest_execution_versions'])
        (tmp_path / 'product/app.js').write_text('changed')
        value = worker.build_tool_context(task, run, {}, [fail, success], 'default')
        assert not any(row['matches_current_files'] for row in value['latest_execution_versions'])


def test_summary_pages_detail_pages_and_cross_task_boundary(tmp_path):
    # 固定分页上限，详情拼接还原原始内容，其他工作区没有摘要访问权。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        for index in range(21):
            execute(db, task, run, tools, ToolCall(f'w{index}', 'write', {'path':f'product/{index}.js', 'content':'large' * 2000 if index == 0 else 'x', 'overwrite':False}))
        store = ToolSummaryStore(tmp_path)
        first = store.model_call('model-a')
        assert len(first['items']) == 20
        assert len(store.model_call('model-a', first['next_cursor'])['items']) == 1
        summary_id = first['items'][0]['summary_id']
        content = ''
        cursor = None
        while True:
            page = store.detail(summary_id, 'call', cursor)
            assert len(page['content']) <= DETAIL_CHARS
            content += page['content']
            cursor = page['next_cursor']
            if cursor is None:
                break
        assert json.loads(content)['call']['parameters']['content'] == 'large' * 2000
        other = ToolRuntime(tmp_path / 'other')
        assert other.execute(ToolCall('query', 'get_tool_execution_detail', {'summary_id':summary_id})).error == 'summary_not_found'
        assert tools.execute(ToolCall('escape', 'get_file_change_history', {'file_path':'../outside'})).status == 'failed'
        assert tools.execute(ToolCall('bad-cursor', 'get_model_call_summaries', {'model_call_id':'model-a', 'cursor':-1})).error == 'invalid_cursor'


def test_query_tools_work_and_their_results_are_not_copied_into_summary(tmp_path):
    # 三个查询工具返回实际记录，查询自己的摘要只保存短结果。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/a.js', 'content':'x', 'overwrite':False}))
        store = ToolSummaryStore(tmp_path)
        row = store.load()[0]
        calls = [ToolCall('q1', 'get_file_change_history', {'file_path':'product/a.js'}),
                 ToolCall('q2', 'get_model_call_summaries', {'model_call_id':'model-a'}),
                 ToolCall('q3', 'get_tool_execution_detail', {'summary_id':row['summary_id']})]
        for call in calls:
            entry = execute(db, task, run, tools, call, 'model-b')
            assert entry['result']['status'] == 'succeeded'
        assert len(store.model_call('model-b')['items']) == 3
        assert 'content' not in store.load()[-1]
        assert 'items' not in store.load()[-1]


def test_old_checkpoint_without_summary_keeps_original_history(tmp_path):
    # 没有摘要的历史任务保留完整交互，不静默丢失执行信息。
    store = ToolSummaryStore(tmp_path)
    history = [{'model_request_id':'old', 'action':{'call_id':'a'}, 'result':{'status':'succeeded'}}]
    assert store.project(history, 1, 'default', {})['tool_history'] == history


def test_context_window_and_history_scope(tmp_path):
    # 较早摘要限制二十条，其他子循环摘要不能混入当前模型上下文。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history = []
        for index in range(23):
            history.append(execute(db, task, run, tools, ToolCall(f'w{index}', 'write',
                {'path':f'product/{index}.js', 'content':'x', 'overwrite':False}), f'model-{index}'))
        worker.execute_tool(db, task, run, tools, ToolCall('other', 'read', {'path':'product/0.js'}), 'other-model', 'review')
        value = worker.build_tool_context(task, run, {}, history, 'default')
        assert len(value['tool_summaries']) == 20
        assert value['earlier_summary_count'] == 3
        assert value['tool_history'] == []
        assert 'other-model' not in json.dumps(value)


def test_missing_trace_keeps_raw_history_and_rejects_detail(tmp_path):
    # 缺少原始证据时不压缩该交互，详情查询不能伪造结果。
    store = ToolSummaryStore(tmp_path)
    call = ToolCall('w', 'write', {'path':'product/a.js', 'content':'x', 'overwrite':False})
    result = ToolRuntime(tmp_path).execute(call)
    row = store.record(1, 'default', 'old-model', call, result, {}, {}, {})
    history = [{'model_request_id':'old-model', 'action':call.__dict__, 'result':result.__dict__},
               {'model_request_id':'new-model', 'action':{'call_id':'new'}, 'result':{}}]
    assert store.project(history, 1, 'default', {})['tool_history'] == history
    with pytest.raises(ValueError, match='tool_evidence_unavailable'):
        store.detail(row['summary_id'])


def test_blocked_tool_also_has_summary(tmp_path):
    # 被循环保护阻止的执行有独立摘要，文件不会被创建。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        worker.execute_tool(db, task, run, tools, ToolCall('blocked', 'write', {'path':'product/x.js', 'content':'x', 'overwrite':False}), 'model-a', 'default', 'repeated_tool_action')
        assert ToolSummaryStore(tmp_path).load()[0]['status'] == 'blocked'
        assert not (tmp_path / 'product/x.js').exists()


def test_summary_failure_still_returns_executed_tool_result(tmp_path, monkeypatch):
    # 摘要存储故障不能丢掉已执行结果，调用方仍可持久化检查点。
    def fail_record(*args, **kwargs):
        # 固定模拟账本写入失败。
        raise OSError('summary unavailable')

    monkeypatch.setattr(ToolSummaryStore, 'record', fail_record)
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        entry = execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/a.js', 'content':'x', 'overwrite':False}))
        assert entry['result']['status'] == 'succeeded'
        assert (tmp_path / 'product/a.js').read_text() == 'x'


def test_resume_recovers_completed_result_without_repeating_tool(tmp_path, monkeypatch):
    # 覆盖工具结果摘要已落盘而检查点只保存 action 的中断窗口。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        entry = execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/a.js', 'content':'x', 'overwrite':False}))
        entry.pop('result')
        worker.save_checkpoint(run, [entry])
        captured = []

        def finish(runtime, task_id, request):
            # 恢复调用只观察有效状态，不再提出写入。
            captured.extend(build_messages(request))
            return ModelResult(request.request_id, 1, 'done', [], 'completed')

        monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call', finish)
        assert worker.model_tool_loop(db, task, run, 'finish', 'input', {}, tools) == 'done'
        assert not any(message['role'] == 'tool' for message in captured)
        context = json.loads(captured[1]['content'])['context']
        assert context['tool_summaries'][0]['latest_write']['status'] == 'succeeded'
        assert len(ToolSummaryStore(tmp_path).load()) == 1
        assert json.loads((tmp_path / 'evidence/checkpoint.json').read_text())[0]['result']['status'] == 'succeeded'


def test_repeated_reads_merge_and_external_change_invalidates_state(tmp_path):
    # 重复读取仅一份文件状态，当前版本外部变化使读取与写入记录同时失效。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history = [execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/a.js','content':'old','overwrite':False}))]
        for index in range(5):
            history.append(execute(db, task, run, tools, ToolCall(f'r{index}', 'read', {'path':'product/a.js'}),f'm{index}'))
        value = worker.build_tool_context(task, run, {}, history, 'default')
        assert len(value['tool_summaries']) == 1
        state = value['tool_summaries'][0]
        assert state['latest_read']['complete'] and state['latest_read']['matches_current_files']
        assert state['latest_read']['tool_call_id'] == 'r4'
        (tmp_path / 'product/a.js').write_text('changed')
        state = worker.build_tool_context(task, run, {}, history, 'default')['tool_summaries'][0]
        assert not state['latest_read']['matches_current_files']
        assert not state['latest_write']['matches_current_files']


def test_current_read_result_references_snapshot_without_mutating_checkpoint(tmp_path):
    # 相同读取全文仅在当前快照提供，历史检查点与 Trace 不被改写。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history = [execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/a.js','content':'current','overwrite':False}))]
        history.append(execute(db, task, run, tools, ToolCall('r', 'read', {'path':'product/a.js'}),'read-call'))
        value = worker.build_tool_context(task, run, {'current_product_files':{'product/a.js':'old'}}, history, 'default')
        assert value['tool_history'] == []
        assert value['current_product_files']['product/a.js'] == 'current'
        output = value['current_requested_data'][0]['output']
        assert 'content' not in output and output['content_source'] == 'current_product_files'
        assert history[-1]['result']['output']['content'] == 'current'
        assert worker.build_tool_context(task, run, {}, history, 'default')['current_requested_data'][0]['output']['content'] == 'current'


def test_truncated_read_is_not_complete_and_deleted_file_is_not_current(tmp_path):
    # 截断读取不代表完整检查，文件缺失不能因空哈希相等被视为有效。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history = [execute(db, task, run, tools, ToolCall('w', 'write', {'path':'product/a.js','content':'x' * 110000,'overwrite':False}))]
        history.append(execute(db, task, run, tools, ToolCall('r', 'read', {'path':'product/a.js'}),'read-call'))
        state = worker.build_tool_context(task, run, {}, history, 'default')['tool_summaries'][0]
        assert not state['latest_read']['complete']
        # 模拟缺失通过更改记录路径，测试本身不删除已有文件。
        store = ToolSummaryStore(tmp_path)
        rows=store.load()
        for row in rows:
            row['file_path']='product/missing.js'
        store.path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        state = store.project([],run.id,'default',{})['tool_summaries'][0]
        assert state['current_hash'] is None and not state['latest_read']['matches_current_files']


def test_unit_handoff_state_does_not_claim_test_pass(tmp_path):
    # 单元文件齐备仅提示交接，失败反馈不能被存在检查覆盖为已通过。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        context={'unit_file_scope':['product/a.js'],'owned_files':['product/a.js'], 'unit':{'id':'ui'},'unit_test_feedback':None}
        state=worker.build_tool_context(task,run,context,[],'default')['development_state']
        assert state['missing_owned_files']==['product/a.js'] and state['next_action']=='develop_missing_files'
        execute(db,task,run,tools,ToolCall('w','write',{'path':'product/a.js','content':'x','overwrite':False}))
        context['unit_test_feedback']={'passed':False}
        state=worker.build_tool_context(task,run,context,[],'default')['development_state']
        assert state['next_action']=='repair_current_unit_from_test_feedback' and state['test_state']=='failed'
        assert state['file_presence_is_not_test_pass']


def test_current_query_returns_data_without_accumulating_old_results(tmp_path):
    # 当前查询保持可用，后一批请求不再自动累积早先查询全文。
    with SessionLocal() as db:
        task, run, tools = task_run(db, tmp_path)
        history=[execute(db,task,run,tools,ToolCall('w','write',{'path':'product/a.js','content':'x','overwrite':False}))]
        history.append(execute(db,task,run,tools,ToolCall('q','get_file_change_history',{'file_path':'product/a.js'}),'query'))
        value=worker.build_tool_context(task,run,{},history,'default')
        assert value['tool_history']==[] and value['current_requested_data'][0]['output']['total']==1
        history.append(execute(db,task,run,tools,ToolCall('r','read',{'path':'product/a.js'}),'next'))
        value=worker.build_tool_context(task,run,{},history,'default')
        assert len(value['current_requested_data'])==1 and value['current_requested_data'][0]['tool_name']=='read'
        assert len(value['tool_summaries'])==1
