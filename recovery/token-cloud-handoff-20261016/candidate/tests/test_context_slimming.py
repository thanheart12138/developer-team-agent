import copy
import hashlib
import json

import pytest

from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime import worker
from backend.app.runtime.context_relay import DeepSeekContextRelay
from backend.app.runtime.contracts import ModelRequest, ModelResult, ToolCall
from backend.app.runtime.model import build_messages
from backend.app.runtime.tools import ToolRuntime
from backend.app.runtime.unit_workflow import UnitTools


@pytest.mark.parametrize('passed', [True, False])
@pytest.mark.parametrize('same_version', [True, False])
def test_self_test_dedup_preserves_protocol_failure_and_versions(passed, same_version):
    # 只删上下文中的相同结果；真实工具失败、思考与调用配对保持。
    report = {'command':'node --test', 'passed':passed, 'file_hashes_after':{'product/a.js':'v1'},
              'result':{'status':'succeeded', 'output':{'exit_code':0 if passed else 1,
                        'stdout':'UNIQUE_SELF_TEST_OUTPUT', 'stderr':''}}}
    result = {'call_id':'test', 'tool_name':'run_unit_tests', 'status':'succeeded', 'output':report, 'error':None}
    history = [{'model_request_id':'m1', 'reasoning_content':'完整思考，不得删除',
                'action':ToolCall('test', 'run_unit_tests', {}).__dict__, 'result':result}]
    current = copy.deepcopy(report)
    current['matches_current_files'] = passed
    if not same_version:
        current['file_hashes_after'] = {'product/a.js':'v2'}
    context = {'unit_self_test':current, 'reasoning_tool_history':history}
    original = copy.deepcopy(context)
    messages = build_messages(ModelRequest('instructions', 'input', context, [], 'next'), include_reasoning=True)
    value = json.loads(messages[1]['content'])['context']['unit_self_test']
    assert value['passed'] is passed and value['matches_current_files'] is passed
    assert ('result' not in value) is same_version
    assert messages[-2]['reasoning_content'] == history[0]['reasoning_content']
    assert messages[-1]['content'] == json.dumps(result, ensure_ascii=False)
    assert messages[-1]['tool_call_id'] == 'test'
    assert context == original
    assert sum(message['content'].count('UNIQUE_SELF_TEST_OUTPUT') for message in messages if message['content']) == (1 if same_version else 2)
    # 没有实际协议来源时必须保留完整结果，不能仅凭调用历史摘要去重。
    bare = build_messages(ModelRequest('instructions', 'input', {'unit_self_test':current}, [], 'bare'), include_reasoning=True)
    assert json.loads(bare[1]['content'])['context']['unit_self_test']['result'] == report['result']


@pytest.mark.parametrize('valid_reference', [True, False])
def test_old_failure_reference_keeps_actual_current_error_and_original_goal(tmp_path, valid_reference):
    # 保留原始事实及可查报告；引用失效时不丢失失败正文。
    tools = ToolRuntime(tmp_path)
    tools._write('product/a.js', 'current', False)
    old = 'old failure' * 1000
    report_path = tmp_path / 'evidence/origin.json'
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps({'failure_report':old}))
    goal = {'id':'E1-1', 'status':'open', 'original_feedback':'纠正后可以继续使用',
            'current_behavior':'旧错误残留', 'expected_behavior':'显示成功', 'reproduction_examples':['纠正后保存'],
            'original_verification_report':old, 'latest_review':{'reason':'old review'}}
    ledger = tmp_path / 'evidence/repair-objectives.json'
    ledger.write_text(json.dumps({'items':[goal]}))
    versions = {'product/a.js':hashlib.sha256(b'current').hexdigest()}
    context = {'repair_task':{'goal':'original goal'}, 'unit_file_scope':['product/a.js'],
        'owned_files':['product/a.js'], 'require_unit_submission':True,
        'unresolved_acceptance_objectives':[goal],
        'unit_diagnostic':{'passed':False, 'file_hashes_after':versions,
                           'failure_report':'product/a.js:1 actual=1 expected=2'},
        'unit_test_feedback':{'failure_report':old, 'detail_path':'evidence/origin.json',
                             'report_sha256':hashlib.sha256(report_path.read_bytes()).hexdigest() if valid_reference else 'wrong'}}
    original = copy.deepcopy(context)
    task = Task(task_name='repair', workspace_path=str(tmp_path), cur_step=Step.develop, status=TaskStatus.running)
    run = StepRun(task_id=1, step=Step.develop, status=StepStatus.running, attempt=1)
    value = worker.build_tool_context(task, run, context, [], 'repair')
    assert ('failure_report' not in value['unit_test_feedback']) is valid_reference
    assert value['unit_diagnostic']['failure_report'] == context['unit_diagnostic']['failure_report']
    assert value['development_state']['test_state'] == 'failed'
    assert value['development_state']['next_action'] == 'repair_current_unit_from_diagnostic'
    if valid_reference:
        assert value['current_task']['latest_evidence']['integration_failure_ref'] == 'unit_test_feedback.detail_path'
    compact = value['unresolved_acceptance_objectives'][0]
    for key in ('id', 'original_feedback', 'current_behavior', 'expected_behavior', 'reproduction_examples'):
        assert compact[key] == goal[key]
    assert compact['current_review_required'] is True and 'original_verification_report' not in compact
    assert json.loads(ledger.read_text())['items'][0] == goal
    assert context == original
    assert json.loads(report_path.read_text())['failure_report'] == old
    scoped = UnitTools(tmp_path, ['product/a.js'], ['evidence/origin.json'],
                       submission_files=['product/a.js'], self_test_files=['product/a.js'])
    assert scoped.execute(ToolCall('early', 'submit_unit_for_test', {})).error == 'unit_self_test_required'
    assert scoped.execute(ToolCall('detail', 'read', {'path':'evidence/origin.json'})).status == 'succeeded'


@pytest.mark.parametrize('passed,failure,current,expected', [
    (False, 'test at product/b.js:3', True, {'product/a.js','product/b.js'}),
    (True, 'successful product/c.js', True, {'product/a.js'}),
    (False, 'unknown failure', True, {'product/a.js','product/b.js','product/c.js'}),
    (False, 'test at product/b.js:3', False, {'product/a.js','product/b.js','product/c.js'}),
])
def test_relay_focus_preserves_fallback_and_allows_omitted_source_read(tmp_path, passed, failure, current, expected):
    # 只在证据有效且能定位时收窄，省略源码不参加读取拦截。
    paths = ['product/a.js','product/b.js','product/c.js']
    tools = UnitTools(tmp_path, paths, [])
    for path in paths:
        tools._write(path, path + '\n', False)
    history = []
    for index, path in enumerate(paths):
        action = ToolCall(f'r{index}', 'read', {'path':path})
        history.append({'model_request_id':'read', 'reasoning_content':'original reasoning',
                        'action':action.__dict__, 'result':tools.execute(action).__dict__})
    action = ToolCall('write', 'write', {'path':paths[0], 'content':'changed\n', 'overwrite':True})
    history.append({'model_request_id':'edit', 'reasoning_content':'edit reasoning',
                    'action':action.__dict__, 'result':tools.execute(action).__dict__})
    original = copy.deepcopy(history)
    relay = DeepSeekContextRelay(tools, 1, 'repair')
    relay.complete_batch(history, 'edit', ['write'], {'detail_path':'evidence/diag.json'})
    context = {'unit_diagnostic':{'passed':passed, 'matches_current_files':current, 'failure_report':failure},
               'product_file_manifest':[{'path':path} for path in paths]}
    replay, value = relay.project(history, context)
    assert replay == [] and history == original
    assert {item['path'] for item in value['carried_file_context']} == expected
    if paths[2] not in expected:
        read = ToolCall('necessary', 'read', {'path':paths[2]})
        assert worker.duplicate_read_error(read, history, value, tools) is None
        assert tools.execute(read).output['content'] == paths[2] + '\n'
        assert value['carried_file_refs'][0]['content_source'] == 'read_on_demand'
    assert worker.duplicate_read_error(ToolCall('repeat', 'read', {'path':paths[0]}), history, value, tools)


def test_compact_planner_can_inspect_formal_document_then_drop_old_body(tmp_path, monkeypatch):
    # 原 inspect 能补读取正式依据，正文只随紧接的一次决策提供，后续保留引用。
    from backend.app.database import Base, SessionLocal, engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    tools = ToolRuntime(tmp_path)
    tools._write('product/a.js', 'current', False)
    for path, body in [('docs/product.md','FORMAL_DETAIL' * 1000),
                       ('evidence/test-report.md','OLD_TEST_OUTPUT' * 1000)]:
        target = tmp_path / path
        target.parent.mkdir(exist_ok=True)
        target.write_text(body)
    (tmp_path / 'evidence/acceptance-triage-7.json').write_text(json.dumps({
        'event_id':7, 'classification':'implementation_defect', 'planner_action':'modify_code',
        'user_feedback':'keep original user goal', 'inspected_evidence':{}}))
    requests = []

    def call(runtime, task_id, request):
        # 模拟结构化规划，实际读取仍由原 Worker 执行。
        requests.append(request)
        action = 'inspect' if len(requests) == 1 else 'run_test'
        return ModelResult(request.request_id, 1, json.dumps({'action':action,
            'path':'docs/product.md' if action == 'inspect' else None, 'reason':'inspect contract',
            'evidence_refs':['docs/product.md']}), [], 'completed')

    monkeypatch.setattr('backend.app.runtime.model.KimiRuntime.call', call)
    with SessionLocal() as db:
        task = Task(task_name='planner', cur_step=Step.test, status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        run = worker.create_step_run(db, task)
        db.commit()
        assert worker.plan_bug_action(db, task, run, tools) == 'inspect'
        assert worker.plan_bug_action(db, task, run, tools) == 'run_test'
        assert worker.plan_bug_action(db, task, run, tools) == 'run_test'
    first, second, third = [request.context for request in requests]
    assert all(request.input == 'keep original user goal' for request in requests)
    assert 'approved_documents' not in first and 'reports' not in first
    assert first['current_evidence'] == {'tested_current':False, 'verified_current':False}
    assert 'docs/product.md' in first['remaining_files']
    assert second['inspected_content']['docs/product.md'] == 'FORMAL_DETAIL' * 1000
    assert third['inspected_content'] == {} and third['inspection_refs']['docs/product.md']['body_in_context'] is False
    assert third['approved_document_refs']['product.md']['sha256'] == hashlib.sha256(('FORMAL_DETAIL' * 1000).encode()).hexdigest()
    assert 'OLD_TEST_OUTPUT' not in json.dumps(third) and 'FORMAL_DETAIL' not in json.dumps(third)


@pytest.fixture
def planner_history(tmp_path):
    # 建立与真实失败相同的跨阶段起点：已读源码、完成测试、进入启动，原目标仍待验证。
    from backend.app.database import Base, SessionLocal, engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    tools = ToolRuntime(tmp_path)
    body = 'export const saveMessage = "任务保存成功。";\n'
    tools._write('product/a.js', body, False)
    (tmp_path / 'evidence/acceptance-triage-7.json').write_text(json.dumps({
        'event_id':7, 'classification':'implementation_defect', 'planner_action':'modify_code',
        'user_feedback':'成功保存后应清除旧错误', 'inspected_evidence':{}}))
    goal_path = tmp_path / 'evidence/repair-objectives.json'
    goal_path.write_text(json.dumps({'items':[{'id':'E7-1', 'status':'open',
        'original_feedback':'成功保存后应清除旧错误', 'expected_behavior':'正确保存并恢复使用'}]}))
    with SessionLocal() as db:
        task = Task(task_name='planner recovery', cur_step=Step.start_product,
                    status=TaskStatus.running, workspace_path=str(tmp_path))
        db.add(task); db.flush()
        develop = StepRun(task_id=task.id, step=Step.develop, attempt=1,
                          status=StepStatus.succeeded, output_path='product/implementation.md')
        test = StepRun(task_id=task.id, step=Step.test, attempt=1,
                       status=StepStatus.succeeded, output_path='evidence/test-report.md')
        db.add_all([develop, test]); db.flush()
        digest = hashlib.sha256(body.encode()).hexdigest()
        trace = worker.safe_record_trace(db, task, test, 'bug_planner_inspect', 'succeeded', '已有调查',
            'product/a.js', {'path':'product/a.js', 'content':body, 'sha256':digest},
            {'event_id':7, 'path':'product/a.js', 'sha256':digest})
        worker.safe_record_trace(db, task, test, 'bug_planner_decision', 'succeeded', '测试行动',
            'run_test', {}, {'event_id':7, 'action':'run_test', 'path':None})
        (tmp_path / 'evidence/bug-tested-code-hashes.json').write_text(json.dumps(worker.product_code_hashes(task)))
        run = worker.create_step_run(db, task)
        db.commit()
        return {'tools':tools, 'task_id':task.id, 'run_id':run.id, 'trace_id':trace.id,
                'trace_path':trace.detail_path, 'test_run_id':test.id, 'body':body,
                'goal_path':goal_path, 'goal_bytes':goal_path.read_bytes(),
                'trace_bytes':(tmp_path / trace.detail_path).read_bytes()}


def test_planner_recovers_cross_run_inspection_without_product_read(planner_history, monkeypatch):
    # 跨 Run 复用原 Trace 并按需省略正文，不能重复执行同版本产品 read 或核销目标。
    from sqlalchemy import select
    from backend.app.database import SessionLocal
    from backend.app.models import TraceRecord
    fixture = planner_history
    requests = []

    def call(runtime, task_id, request):
        # 模拟模型主动恢复证据后按当前阶段启动，不用假调用替代实际证据恢复。
        requests.append(copy.deepcopy(request.context))
        action = 'inspect' if len(requests) == 1 else 'start_product'
        return ModelResult(request.request_id, 1, json.dumps({'action':action,
            'path':'product/a.js' if action == 'inspect' else None, 'reason':'依当前门禁推进'}), [], 'completed')

    def no_product_read(call):
        # 已读版本必须从 Trace 恢复，测试禁止再次触发文件读取工具。
        pytest.fail(f'不应再次执行文件工具：{call.tool_name}')

    monkeypatch.setattr('backend.app.runtime.model.KimiRuntime.call', call)
    monkeypatch.setattr(fixture['tools'], 'execute', no_product_read)
    with SessionLocal() as db:
        task, run = db.get(Task, fixture['task_id']), db.get(StepRun, fixture['run_id'])
        assert worker.plan_bug_action(db, task, run, fixture['tools']) == 'inspect'
        assert worker.plan_bug_action(db, task, run, fixture['tools']) == 'start_product'
        assert worker.plan_bug_action(db, task, run, fixture['tools']) == 'start_product'
        traces = list(db.scalars(select(TraceRecord).where(TraceRecord.type == 'bug_planner_inspect')
                                 .order_by(TraceRecord.sequence)))
        assert len(traces) == 2 and traces[-1].metadata_json['content_source'] == 'saved_inspection'
        assert traces[-1].metadata_json['reused_from'] == fixture['trace_path']
        assert task.status == TaskStatus.running
    first, restored, omitted = requests
    assert first['inspected_content'] == {}
    assert first['inspection_refs']['product/a.js']['available_for_inspect'] is True
    assert first['inspection_refs']['product/a.js']['evidence_ref'] == fixture['trace_path']
    assert first['current_evidence']['tested_current'] is True
    assert first['execution_state']['suggested_action'] == 'start_product'
    assert first['execution_state']['development_run']['status'] == 'succeeded'
    assert first['execution_state']['user_feedback_role'] == 'original_acceptance_feedback'
    assert restored['inspected_content']['product/a.js'] == fixture['body']
    assert 'product/a.js' not in restored['remaining_files']
    assert omitted['inspected_content'] == {} and omitted['inspection_refs']['product/a.js']['body_in_context'] is False
    assert fixture['goal_path'].read_bytes() == fixture['goal_bytes']
    assert (fixture['tools'].workspace / fixture['trace_path']).read_bytes() == fixture['trace_bytes']


def test_planner_corrects_same_run_repeat_with_saved_body(planner_history, monkeypatch):
    # 同 Run 的非法重选应指出 path 原因，恢复旧结果供纠错，不能再执行 read。
    from backend.app.database import SessionLocal
    from backend.app.models import TraceRecord
    fixture, requests = planner_history, []
    with SessionLocal() as db:
        trace = db.get(TraceRecord, fixture['trace_id'])
        trace.step_run_id = fixture['run_id']
        db.commit()

    def call(runtime, task_id, request):
        # 第一次重选非法路径，第二次必须得到具体拒绝原因与有效旧正文。
        requests.append(copy.deepcopy(request.context))
        action = 'inspect' if len(requests) == 1 else 'start_product'
        return ModelResult(request.request_id, 1, json.dumps({'action':action,
            'path':'product/a.js' if action == 'inspect' else None, 'reason':'按反馈纠正'}), [], 'completed')

    def no_product_read(call):
        # 协议纠错只恢复缓存，不能产生重复文件工具执行。
        pytest.fail('同 Run 的重选不应执行产品读取')

    monkeypatch.setattr('backend.app.runtime.model.KimiRuntime.call', call)
    monkeypatch.setattr(fixture['tools'], 'execute', no_product_read)
    with SessionLocal() as db:
        assert worker.plan_bug_action(db, db.get(Task, fixture['task_id']),
                                     db.get(StepRun, fixture['run_id']), fixture['tools']) == 'start_product'
    assert len(requests) == 2 and requests[0]['inspected_content'] == {}
    error = next(item for item in requests[1]['protocol_error']['errors'] if item['field'] == 'path')
    assert error['code'] == 'inspect_path_not_available'
    assert '当前 Run 已调查' in error['message']
    assert requests[1]['inspected_content']['product/a.js'] == fixture['body']
    assert fixture['goal_path'].read_bytes() == fixture['goal_bytes']


@pytest.mark.parametrize('invalid_evidence', ['missing', 'wrong_content', 'non_string', 'changed_file'])
def test_planner_never_restores_missing_corrupt_or_stale_body(planner_history, monkeypatch, invalid_evidence):
    # 同路径不足以复用；坏证据不注入正文，新版本可按原额度实际读取。
    from backend.app.database import SessionLocal
    from backend.app.models import TraceRecord
    fixture, requests = planner_history, []
    tools = fixture['tools']
    with SessionLocal() as db:
        task, old = db.get(Task, fixture['task_id']), db.get(TraceRecord, fixture['trace_id'])
        task.cur_step = Step.test
        if invalid_evidence == 'changed_file':
            tools._write('product/a.js', 'export const current = 2;\n', True)
        else:
            # 缺失证据只改变测试索引；不删除已有文件或覆盖不可变原 Trace。
            old.detail_path = 'evidence/unavailable-test-trace.json'
            if invalid_evidence != 'missing':
                (tools.workspace / old.detail_path).write_text(json.dumps({'payload':{
                    'path':'product/a.js', 'sha256':old.metadata_json['sha256'],
                    'content':1 if invalid_evidence == 'non_string' else 'incorrect cached text'}}))
        run = worker.create_step_run(db, task)
        db.commit()
        run_id = run.id

    def call(runtime, task_id, request):
        # 只观察当前证据，选择正常测试，不用模型假成功掩盖坏缓存。
        requests.append(copy.deepcopy(request.context))
        return ModelResult(request.request_id, 1, json.dumps({'action':'run_test', 'path':None,
            'reason':'按当前测试门禁推进'}), [], 'completed')

    monkeypatch.setattr('backend.app.runtime.model.KimiRuntime.call', call)
    with SessionLocal() as db:
        assert worker.plan_bug_action(db, db.get(Task, fixture['task_id']), db.get(StepRun, run_id), tools) == 'run_test'
    context = requests[0]
    assert context['inspected_content'] == {}
    assert context['inspection_refs']['product/a.js']['matches_current_file'] is False
    assert context['inspection_refs']['product/a.js']['available_for_inspect'] is False
    assert ('product/a.js' in context['remaining_files']) is (invalid_evidence == 'changed_file')
    assert 'incorrect cached text' not in json.dumps(context)
    assert fixture['goal_path'].read_bytes() == fixture['goal_bytes']


def test_cache_recovery_keeps_original_inspection_limit(planner_history, monkeypatch):
    # 已用三次调查时即使旧缓存有效也不能新增 inspect 或重置额度。
    from backend.app.database import SessionLocal
    fixture, requests = planner_history, []
    with SessionLocal() as db:
        task, old_run = db.get(Task, fixture['task_id']), db.get(StepRun, fixture['test_run_id'])
        for name in ('b', 'c'):
            path, body = f'product/{name}.js', f'export const {name} = 1;\n'
            fixture['tools']._write(path, body, False)
            digest = hashlib.sha256(body.encode()).hexdigest()
            worker.safe_record_trace(db, task, old_run, 'bug_planner_inspect', 'succeeded', '历史调查', path,
                {'path':path, 'content':body, 'sha256':digest}, {'event_id':7, 'path':path, 'sha256':digest})
        (fixture['tools'].workspace / 'evidence/bug-tested-code-hashes.json').write_text(json.dumps(worker.product_code_hashes(task)))
        db.commit()

    def call(runtime, task_id, request):
        # 模拟一次越额度行动，纠错后使用合法启动，不放大原预算。
        requests.append(copy.deepcopy(request.context))
        action = 'inspect' if len(requests) == 1 else 'start_product'
        return ModelResult(request.request_id, 1, json.dumps({'action':action,
            'path':'product/a.js' if action == 'inspect' else None, 'reason':'观察原额度'}), [], 'completed')

    monkeypatch.setattr('backend.app.runtime.model.KimiRuntime.call', call)
    with SessionLocal() as db:
        assert worker.plan_bug_action(db, db.get(Task, fixture['task_id']),
            db.get(StepRun, fixture['run_id']), fixture['tools']) == 'start_product'
    assert len(requests) == 2 and 'inspect' not in requests[0]['allowed_actions']
    assert requests[0]['inspection_refs']['product/a.js']['available_for_inspect'] is False
    assert requests[1]['protocol_error']['errors'][0]['field'] == 'action'


def test_planner_still_fails_after_one_invalid_correction(planner_history, monkeypatch):
    # 两次都选择工作区外路径仍失败，不替模型选启动、不追加逻辑调用。
    from backend.app.database import SessionLocal
    fixture, requests = planner_history, []

    def call(runtime, task_id, request):
        # 持续非法回复用于验证原有一次纠错上限。
        requests.append(copy.deepcopy(request.context))
        return ModelResult(request.request_id, 1, json.dumps({'action':'inspect',
            'path':'../outside.js', 'reason':'非法路径'}), [], 'completed')

    monkeypatch.setattr('backend.app.runtime.model.KimiRuntime.call', call)
    with SessionLocal() as db:
        run = db.get(StepRun, fixture['run_id'])
        with pytest.raises(RuntimeError, match='bug_planner_protocol_failed'):
            worker.plan_bug_action(db, db.get(Task, fixture['task_id']), run, fixture['tools'])
        assert run.model_call_count == 2
    assert len(requests) == 2 and requests[1]['protocol_error']['errors'][0]['field'] == 'path'
    assert fixture['goal_path'].read_bytes() == fixture['goal_bytes']


@pytest.mark.parametrize('value,field,code', [
    (None, 'response', 'json_object_required'),
    ([], 'response', 'json_object_required'),
    ({'action':'finish', 'reason':'invalid'}, 'action', 'action_not_allowed'),
    ({'action':'start_product', 'reason':' '}, 'reason', 'reason_required'),
    ({'action':'start_product', 'reason':'ok', 'path':'product/a.js'}, 'path', 'unexpected_path'),
    ({'action':'clarify', 'reason':'unknown', 'clarifying_question':' '}, 'clarifying_question', 'question_required'),
])
def test_planner_protocol_errors_identify_actual_field(value, field, code):
    # 非法输入与空字段应给出精确拒绝原因，不通过宽松解析隐藏问题。
    errors = worker.bug_planner_protocol_errors(value, ['start_product', 'inspect', 'clarify'], [], {})
    assert errors[0]['field'] == field and errors[0]['code'] == code
