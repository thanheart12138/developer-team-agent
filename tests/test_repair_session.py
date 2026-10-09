"""连续返修的权限、恢复与受控提问回归，不进行外部模型请求。"""
import json
from types import SimpleNamespace
import pytest
from backend.app.runtime import repair_runtime as repair, repair_session as session, worker
from backend.app.runtime.contracts import ToolCall
from tests.test_repair_runtime import attempt


@pytest.mark.parametrize('prompt', ['unknown prompt', session.LEGACY_PROMPT])
def test_prompt_binding_rejects_unknown_or_wrong_contract(prompt):
    """未知绑定或错误契约不得静默改用新指令。"""
    import hashlib
    state = {'session': {'context_contract': 'v2', 'prompt_hash': hashlib.sha256(prompt.encode()).hexdigest()}}
    with pytest.raises(RuntimeError, match='repair_session_binding_changed'):
        session.select_prompt(state)


def prepare(root):
    """建立当前尝试会话，不绕过实际工具版本判定。"""
    state = repair.load(root)
    state['session'] = {'id': 'fixture', 'provider': 'deepseek', 'plan': None, 'decisions': []}
    repair.save(root, state)
    return session.RepairTools(root)


def facts_fixture(root, tools, history):
    """用真实文件版本构建新视图，旧摘要仅作为冲突输入。"""
    state = repair.load(root)
    state['session']['context_contract'] = 'v2'
    repair.save(root, state)
    context = {'unit_self_test': {'passed': False}, 'development_state': {'old': True},
               'tool_summaries': [{'latest_read': {'matches_current_files': False}}],
               'carried_file_context': [{'path': 'product/index.html', 'content': 'visible'}],
               'reasoning_tool_history': history, 'unresolved_acceptance_objectives': [{'status': 'open'}]}
    return session.current_facts(context, state, history, tools)


@pytest.mark.parametrize('visible, changed_result', [(True, False), (False, False), (True, True)])
def test_v2_self_test_body_has_one_visible_source(visible, changed_result):
    """有对应协议时去重，接力后保留失败详情，其他错误和原历史不变。"""
    from backend.app.runtime.model import build_messages
    from backend.app.runtime.contracts import ModelRequest
    output = {'command': 'node --test', 'file_hashes_before': {'a': 'hash'},
              'file_hashes_after': {'a': 'hash'}, 'passed': False,
              'result': {'exit_code': 1}, 'failure_details': {'stdout': 'specific failure'}}
    ref = {'model_call_id': 'm1', 'tool_call_id': 't1'}
    history = [{'model_request_id': 'm1', 'reasoning_content': 'original thinking',
                'action': {'tool_name': 'run_unit_tests', 'call_id': 't1', 'parameters': {}},
                'result': {'status': 'succeeded', 'output': output}}]
    failures = [{'parent_model_call_id': 'm1', 'tool_call_id': 't1', 'tool_name': 'run_unit_tests', 'error_excerpt': 'old log'},
                {'parent_model_call_id': 'm1', 'tool_call_id': 't2', 'tool_name': 'read', 'error_excerpt': 'other error'}]
    context = {'current_task_facts': {'contract': 'v2', 'self_test': {
        'state': 'failed', 'evidence': {**output, 'result_ref': ref}}},
        'tool_failures': failures, 'reasoning_tool_history': history if visible else []}
    if changed_result:
        context['current_task_facts']['self_test']['evidence']['passed'] = True
    original = json.dumps(context, sort_keys=True)
    messages = build_messages(ModelRequest('instruction', 'feedback', context, [], 'request'), True)
    projected = json.loads(messages[1]['content'])['context']
    evidence = projected['current_task_facts']['self_test']['evidence']
    deduplicated = visible and not changed_result
    assert ('failure_details' in evidence) is not deduplicated
    assert ('error_excerpt' in projected['tool_failures'][0]) is not deduplicated
    assert projected['tool_failures'][1] == failures[1]
    if visible:
        assert messages[2]['reasoning_content'] == 'original thinking'
        assert json.loads(messages[3]['content'])['output'] == output
    assert json.dumps(context, sort_keys=True) == original


def test_current_facts_cumulative_changes_and_stale_test(attempt):
    """接力后累计修改不丢失，新增文件使真实通过证据过期。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    history = []
    for path, content in [('product/index.html', '<h1>fixed</h1>'), ('product/feature.js', '1')]:
        result = tools._write(path, content, path != 'product/feature.js')
        history.append({'model_request_id': 'write-request',
                        'action': {'tool_name': 'write', 'call_id': path, 'parameters': {'path': path}},
                        'result': {'status': 'succeeded', 'output': result},
                        'repair_versions_after': tools.self_test_versions()})
    output = tools._run_unit_tests()
    history.append({'model_request_id': 'test-request', 'reasoning_content': 'real thinking',
                    'action': {'tool_name': 'run_unit_tests', 'call_id': 'test'},
                    'result': {'status': 'succeeded', 'output': output}})
    before = json.dumps(history, sort_keys=True)
    view = facts_fixture(root, tools, history)
    facts = view['current_task_facts']
    assert len(facts['changes']) == 2
    assert all(operation['tool_name'] == 'write' and operation['query_tool'] == 'get_model_call_summaries'
               for change in facts['changes'] for operation in change['operations'])
    assert all(c['latest_write_matches_current_files'] for c in facts['changes'])
    assert facts['self_test']['state'] == 'current_passed'
    assert facts['submission']['known_blockers'] == []
    assert facts['submission']['business_completion'] == 'model_must_judge'
    assert facts['after_submission']['steps'] == ['independent_tests', 'browser_verification']
    assert not facts['submission']['automatic_submit']
    assert 'tool_summaries' not in view and 'unit_self_test' not in view
    assert view['reasoning_tool_history'] == history
    assert view['carried_file_context'][0]['content'] == 'visible'
    assert view['unresolved_acceptance_objectives'][0]['status'] == 'open'
    tools._write('product/new.js', '2', False)
    assert facts_fixture(root, tools, history)['current_task_facts']['self_test']['state'] == 'stale'
    tools._write('product/index.html', '<h1>later</h1>', True)
    assert not facts_fixture(root, tools, history)['current_task_facts']['changes'][0]['latest_write_matches_current_files']
    assert json.dumps(history, sort_keys=True) == before


def test_current_facts_independent_failure_boundary_and_unknown_action(attempt):
    """独立失败后旧自测不能恢复绿灯，未知副作用与损坏边界不得猜成功。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    output = tools._run_unit_tests()
    history = [{'action': {'tool_name': 'run_unit_tests', 'call_id': 'test'},
                'result': {'status': 'succeeded', 'output': output}}]
    state = repair.load(root)
    state['session']['validation_boundary'] = 1
    state['last_failure'] = {'phase': 'verifying', 'evidence': 'evidence/browser-failed.json'}
    repair.save(root, state)
    facts = facts_fixture(root, tools, history)['current_task_facts']
    assert facts['self_test']['state'] == 'not_tested'
    assert facts['latest_validation_failure']['phase'] == 'verifying'
    assert 'current_self_test_required' in facts['submission']['known_blockers']
    history.append({'action': {'tool_name': 'write', 'call_id': 'unknown'}})
    assert 'unknown_side_effect' in facts_fixture(root, tools, history)['current_task_facts']['submission']['known_blockers']
    state = repair.load(root)
    state['session']['validation_boundary'] = 99
    repair.save(root, state)
    assert 'invalid_validation_boundary' in facts_fixture(root, tools, history)['current_task_facts']['submission']['known_blockers']


def test_work_progress_is_versioned_judgment_and_preserves_decision(attempt):
    """工作判断可恢复但不能替代审批；版本变更后明确需要复核。"""
    root, _, task, _, _ = attempt
    tools = prepare(root)
    facts_fixture(root, tools, [])
    plan = tools._update_plan(['修复检索'], '定位原因', findings=['笔记没有进入搜索字段'],
                              open_questions=['浏览器待独立验证'], next_action='补回归后提交')
    view = facts_fixture(root, session.RepairTools(root), [])
    assert view['work_progress']['source'] == 'model_judgment'
    assert view['work_progress']['value'] == plan
    assert view['work_progress']['applicability'] == 'current'
    tools._write('product/feature.js', '1', False)
    assert facts_fixture(root, tools, [])['work_progress']['applicability'] == 'needs_review'
    decision = tools._request_decision('改变业务吗？', '改变搜索规则', '保持原设计')
    facts = facts_fixture(root, tools, [])['current_task_facts']
    assert 'unanswered_decision' in facts['submission']['known_blockers']
    assert session.answer(task, {'decision_id': decision['id'], 'content': '保持原设计'})
    assert facts_fixture(root, tools, [])['current_task_facts']['decisions'][-1]['answer'] == '保持原设计'
    assert (root / 'docs/product.md').read_text() == '批准需求：展示 fixture'


def test_old_plan_contract_rejects_new_progress_fields(attempt):
    """旧会话不偷偷接收新工具字段，新判断也必须有效。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    old_plan = tools._update_plan(['修复'], '原计划')
    assert old_plan == {'steps': ['修复'], 'reason': '原计划'}
    with pytest.raises(ValueError, match='contract_required'):
        tools._update_plan(['修复'], '原因', findings=['原因'])
    facts_fixture(root, tools, [])
    with pytest.raises(ValueError, match='progress_invalid'):
        tools._update_plan(['修复'], '原因', open_questions=[''])


def test_current_facts_failure_details_and_command_invalidation(attempt):
    """真实失败详情不能丢失；命令不匹配不能成为当前通过证据。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    tools._write('product/app.test.js', "require('node:test').test('broken',()=>{throw Error('actual defect')});", True)
    output = tools._run_unit_tests()
    history = [{'action': {'tool_name': 'run_unit_tests', 'call_id': 'test'},
                'result': {'status': 'succeeded', 'output': output}}]
    facts = facts_fixture(root, tools, history)['current_task_facts']
    assert facts['self_test']['state'] == 'failed'
    assert 'actual defect' in facts['self_test']['evidence']['failure_details']['stdout']
    output['command'] = 'node --test selected.test.js'
    assert facts_fixture(root, tools, history)['current_task_facts']['self_test']['state'] == 'stale'


def test_task_scope_new_files_and_stale_self_test(attempt):
    """新增产品文件被版本集合包含，不能复用旧绿灯。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    assert tools.execute(ToolCall('new', 'write', {'path': 'product/feature.js', 'content': '1', 'overwrite': False})).status == 'succeeded'
    output = tools._run_unit_tests()
    assert output['passed']
    assert tools.self_test_command() == 'node --test'
    tools._write('product/new.test.js', "require('node:test').test('new',()=>{});", False)
    assert not tools.restore_self_test(output)
    assert 'product/new.test.js' in tools.submission_versions()
    assert tools._run_unit_tests()['passed']
    assert tools._submit_unit_for_test()['test_state'] == 'pending'


@pytest.mark.parametrize('path', ['docs/product.md', 'evidence/repair-runtime-v1.json', '../other.js',
                                  'product/.env', 'product/AGENTS.md', 'product/.aws/file'])
def test_protected_writes(attempt, path):
    """跨任务、治理、需求与认证路径均不允许写入。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    assert tools.execute(ToolCall('bad', 'write', {'path': path, 'content': 'x', 'overwrite': False})).status == 'failed'


def test_link_and_frozen_write_rejected(attempt):
    """内部链接也拒绝；提交后不能继续改产品。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    (root / 'product/link').symlink_to(root / 'docs/product.md')
    result = tools.execute(ToolCall('link', 'write', {'path': 'product/link', 'content': 'x', 'overwrite': True}))
    assert result.status == 'failed'


def test_decision_requires_matching_answer_and_preserves_budget(attempt):
    """问题与回答明确配对，回答不更改正式文档或实际额度。"""
    root, _, task, _, _ = attempt
    tools = prepare(root)
    before = repair.load(root)['budget']
    decision = tools._request_decision('选择交互方案？', '影响显示顺序', '维持现有业务')
    assert repair.load(root)['state'] == 'waiting_decision'
    with pytest.raises(ValueError, match='answer_mismatch'):
        session.answer(task, {'content': '维持'})
    assert session.answer(task, {'decision_id': decision['id'], 'content': '维持现有业务'})
    assert repair.load(root)['session']['decisions'][-1]['answer'] == '维持现有业务'
    assert repair.load(root)['budget'] == before
    assert (root / 'docs/product.md').read_text() == '批准需求：展示 fixture'


def test_unknown_batch_stops_without_model(attempt, monkeypatch):
    """未完成整批意图阻止重放，且不发送模型请求。"""
    root, db, task, _, _ = attempt
    prepare(root)
    state = repair.load(root);state['session']['pending_actions'] = [{'call_id': 'unknown'}];repair.save(root,state)
    monkeypatch.setattr(worker, 'model_tool_loop', lambda *a, **k: pytest.fail('must not call model'))
    with pytest.raises(RuntimeError, match='unknown_side_effect'):
        session.execute(db, task, SimpleNamespace())


@pytest.mark.parametrize('content', [None, ['批准']])
def test_decision_rejects_non_text_answer(attempt, content):
    """空值和列表不能被字符串转换误当作用户明确回答。"""
    root, _, task, _, _ = attempt
    decision = prepare(root)._request_decision('选择方案？', '影响交互', '保持现状')
    with pytest.raises(ValueError, match='answer_mismatch'):
        session.answer(task, {'decision_id': decision['id'], 'content': content})
    assert repair.load(root)['state'] == 'waiting_decision'


def test_entry_bypasses_planner_and_keeps_original_goal(attempt, monkeypatch):
    """显式入口直接进入主会话，不再调用旧选卡规划。"""
    root, db, task, event, _ = attempt
    monkeypatch.setattr(worker, 'plan_acceptance_feedback', lambda *a: pytest.fail('old planner'))
    worker.consume_event(db, event, task)
    assert task.cur_step.value == 'develop'
    assert task.status.value == 'running'
    assert json.loads((root/'evidence/repair-objectives.json').read_text())['items'][-1]['original_feedback'] == '修复 fixture'


def test_validation_failure_returns_to_same_protocol(attempt, monkeypatch):
    """真实 Node 自测配合固定模型响应，验证跨 Run 思考／工具协议保持。"""
    from backend.app.runtime.contracts import ModelResult
    from backend.app.runtime.model import build_messages
    from backend.app.models import Step, TaskStatus
    root, db, task, _, _ = attempt
    seen = []
    calls = [
        [('run_unit_tests', {})],
        [('submit_unit_for_test', {})],
        [('write', {'path':'product/feature.js','content':'fixed','overwrite':False})],
        [('run_unit_tests', {})],
        [('submit_unit_for_test', {})],
    ]
    class FixedModel:
        """仅供机制测试的固定模型，绝不访问外部服务。"""
        provider = 'deepseek'
        model_name = 'fixed-model'
        def build_payload(self, request):
            return {'messages': build_messages(request, include_reasoning=True)}
        def call(self, task_id, request):
            seen.append(self.build_payload(request)['messages'])
            batch = calls.pop(0)
            return ModelResult(request.request_id, 1, '',
                [ToolCall(f'call-{len(seen)}-{i}',name,params) for i,(name,params) in enumerate(batch)],
                'tool_calls', {'reasoning_content':f'thought-{len(seen)}'})
    monkeypatch.setattr(worker,'create_model_runtime',lambda *a:FixedModel())
    task.status = TaskStatus.running;db.commit()
    assert worker.process_task(db)
    first = repair.load(root)
    assert first['state'] == 'submitted'
    session_id = first['session']['id']
    checkpoint = root / f'evidence/repair-session-{session_id}-checkpoint.json'
    original = json.loads(checkpoint.read_text())
    # 注入已证实的验证失败，不删除协议历史，也不能复用先前提交。
    first['state']='executing'
    first['session']['validation_boundary']=len(original)
    first['last_failure']={'phase':'reviewing','evidence':first['validation_ref']}
    repair.save(root,first)
    task.cur_step=Step.develop;task.status=TaskStatus.running;db.commit()
    assert worker.process_task(db)
    second=repair.load(root)
    assert second['session']['id']==session_id
    assert second['submission_number']==2
    assert (root/'product/feature.js').read_text()=='fixed'
    assert json.loads(checkpoint.read_text())[:len(original)]==original
    assert any(m.get('reasoning_content')=='thought-1' for m in seen[2])
    assert not calls


def test_self_test_reuses_current_success_after_restore(attempt, monkeypatch):
    """同版本重复和恢复复用原真实绿灯，文件变化后重新执行。"""
    from backend.app.runtime.unit_workflow import UnitTools
    root, _, _, _, _ = attempt
    original = UnitTools._run_unit_tests
    executed = []

    def run(scoped):
        """记录真正进入原测试执行的次数。"""
        executed.append(1)
        return original(scoped)

    monkeypatch.setattr(UnitTools, '_run_unit_tests', run)
    tools = prepare(root)
    first = tools._run_unit_tests()
    assert first['passed'] and not first['reused']
    second = tools._run_unit_tests()
    assert second['passed'] and second['reused'] and len(executed) == 1
    restored = session.RepairTools(root)
    assert restored.restore_self_test(second)
    assert restored._run_unit_tests()['reused'] and len(executed) == 1
    restored._write('product/new.js', '/* changed set */', False)
    assert restored._run_unit_tests()['reused'] is False and len(executed) == 2
    assert first['file_hashes_after'] != restored.self_test['file_hashes_after']


@pytest.mark.parametrize('change', ['implementation', 'test', 'command'])
def test_changed_self_test_scope_cannot_reuse(attempt, monkeypatch, change):
    """实现、测试或固定命令变更均使当前版本证据失效。"""
    root, _, _, _, _ = attempt
    tools = prepare(root)
    first = tools._run_unit_tests()
    if change == 'command':
        monkeypatch.setattr(tools, 'self_test_command', lambda: 'node --test app.test.js')
    else:
        path = root / ('product/index.html' if change == 'implementation' else 'product/app.test.js')
        path.write_text(path.read_text() + '\n/* version changed */')
    assert not tools.restore_self_test(first)
    assert tools._run_unit_tests()['reused'] is False


def test_failed_self_test_runs_again_and_keeps_diagnostic(attempt):
    """失败不能缓存成通过，摘要保留真实断言信息供模型修复。"""
    root, _, _, _, _ = attempt
    (root / 'product/app.test.js').write_text("const {test}=require('node:test');test('broken',()=>{throw Error('known failure');});")
    tools = prepare(root)
    first = tools._run_unit_tests()
    second = tools._run_unit_tests()
    assert not first['passed'] and not second['passed'] and not second['reused']
    assert first['result']['call_id'] != second['result']['call_id']
    view = session.self_test_view(second)
    assert 'known failure' in view['failure_details']['stdout']
    assert view['result']['counts']['fail'] == 1


def test_large_failure_diagnostic_is_bounded_and_queryable():
    """大量失败与非 TAP 异常明确截断，完整日志保留引用。"""
    output = {'passed': False, 'result': {'status': 'succeeded', 'output': {
        'exit_code': 1, 'stdout': 'exception-' + 'x' * 20000, 'stderr': 'y' * 8000}}}
    ref = {'model_call_id': 'original', 'query_tool': 'get_model_call_summaries'}
    view = session.self_test_view(output, ref)
    assert len(view['failure_details']['stdout']) == 16000
    assert len(view['failure_details']['stderr']) == 6000
    assert view['failure_details']['truncated'] and view['result_ref'] == ref
    assert len(output['result']['output']['stdout']) > 20000


def test_model_projection_preserves_reasoning_pairs_and_audit():
    """首次及续传摘要一致，成功 TAP 不进协议，原日志与思考不丢失。"""
    import copy
    from backend.app.runtime.model import build_messages
    from backend.app.runtime.contracts import ModelRequest
    output = {'command': 'node --test', 'passed': True, 'file_hashes_before': {'a': 'v'},
              'file_hashes_after': {'a': 'v'}, 'result': {'status': 'succeeded', 'output': {
                  'exit_code': 0, 'stdout': ('ok 1 - original-audit-only\n' * 4000) + '# tests 1\n# pass 1\n# fail 0\n', 'stderr': ''}}}
    entry = {'model_request_id': 'request-a', 'reasoning_content': 'preserved thinking', 'assistant_content': '',
             'action': {'call_id': 'tool-a', 'tool_name': 'run_unit_tests', 'parameters': {}},
             'result': {'call_id': 'tool-a', 'tool_name': 'run_unit_tests', 'status': 'succeeded', 'output': output}}
    history = [entry]
    original = copy.deepcopy(history)
    projected = session.project_test_history(history)
    assert projected == session.project_test_history(history) and history == original
    messages = build_messages(ModelRequest('instruction', 'feedback', {'reasoning_tool_history': projected}, [], 'request-b'), include_reasoning=True)
    assert messages[-2]['reasoning_content'] == 'preserved thinking'
    assert messages[-2]['tool_calls'][0]['id'] == messages[-1]['tool_call_id'] == 'tool-a'
    assert 'original-audit-only' not in messages[-1]['content']
    assert len(messages[-1]['content']) < 2000
    assert json.loads(messages[-1]['content'])['output']['result']['counts']['pass'] == 1
    submitted = {**entry, 'action': {**entry['action'], 'tool_name': 'submit_unit_for_test'},
                 'result': {**entry['result'], 'output': {'test_state': 'pending', 'self_test': output}}}
    assert 'original-audit-only' not in json.dumps(session.project_test_history([submitted]))


@pytest.mark.parametrize('legacy, previous', [(False, False), (True, False), (False, True)])
def test_main_loop_compact_results_explicit_submit_and_original_log_query(attempt, monkeypatch, legacy, previous):
    """主循环可复用结果、继续必要阅读并显式提交，审计仍可分页取全日志。"""
    from backend.app.runtime.contracts import ModelResult
    from backend.app.runtime.model import build_messages
    from backend.app.runtime.tool_summaries import ToolSummaryStore
    from backend.app.models import TaskStatus
    root, db, task, _, _ = attempt
    batches = [[('run_unit_tests', {})], [('run_unit_tests', {})], [('read', {'path': 'docs/product.md'})], [('submit_unit_for_test', {})]]
    requests = []

    class FixedModel:
        """固定模型只验证实际主循环与工具，禁止外部请求。"""
        provider = 'deepseek'
        model_name = 'fixed-selftest-cost'

        def build_payload(self, request):
            """调用实际协议序列化以核对模型真正接收的结果。"""
            return {'messages': build_messages(request, include_reasoning=True)}

        def call(self, task_id, request):
            """四个有序动作保留必要阅读及模型明确交接。"""
            requests.append(request)
            batch = batches.pop(0)
            return ModelResult(request.request_id, 1, '', [ToolCall(f'cost-{len(requests)}', name, parameters) for name, parameters in batch], 'tool_calls', {'reasoning_content': f'cost-thinking-{len(requests)}'})

    monkeypatch.setattr(worker, 'create_model_runtime', lambda *a: FixedModel())
    if legacy or previous:
        import hashlib
        state = repair.load(root)
        state['session'] = {'id': f'{task.id}-{state["event_id"]}', 'provider': 'deepseek',
                            'prompt_hash': hashlib.sha256((session.LEGACY_PROMPT if legacy else session.PREVIOUS_PROMPT).encode()).hexdigest(),
                            'plan': None, 'decisions': [], 'original_tests': {
                                'app.test.js': (root / 'product/app.test.js').read_text(),
                                'verify_product.py': (root / 'product/verify_product.py').read_text()}}
        if previous:
            state['session']['context_contract'] = 'v2'
        repair.save(root, state)
    task.status = TaskStatus.running
    db.commit()
    assert worker.process_task(db)
    assert repair.load(root)['state'] == 'submitted' and not batches
    expected_prompt = session.LEGACY_PROMPT if legacy else session.PREVIOUS_PROMPT if previous else session.PROMPT
    assert all(expected_prompt in request.instructions for request in requests)
    if legacy or previous:
        assert all('调查推进规则：' not in request.instructions for request in requests)
    for request in requests[1:]:
        if legacy:
            assert 'current_task_facts' not in request.context
            assert request.context['development_state']['current_version_passed']
            assert not request.context['development_state']['automatic_submit']
            test = request.context['unit_self_test']
        else:
            facts = request.context['current_task_facts']
            assert facts['self_test']['state'] == 'current_passed'
            assert not facts['submission']['automatic_submit']
            test = facts['self_test']['evidence']
        assert 'result_ref' in test
        assert 'stdout' not in test['result']
        plan_schema = next(s for s in request.tools if s['function']['name'] == 'update_plan')
        assert ('findings' in plan_schema['function']['parameters']['properties']) is not legacy
    second_tool = json.loads(build_messages(requests[2], True)[-1]['content'])
    assert second_tool['output']['reused'] is True
    context = json.loads(build_messages(requests[1], True)[1]['content'])['context']
    assert context['current_requested_data'][0]['content_source'] == 'tool_message'
    checkpoint = next((root / 'evidence').glob('repair-session-*-checkpoint.json'))
    entries = json.loads(checkpoint.read_text())
    raw = entries[0]['result']['output']['result']['output']['stdout']
    assert 'pass 1' in raw
    store = ToolSummaryStore(root)
    row = store.model_call(requests[0].request_id)['items'][0]
    detail = store.detail(row['summary_id'])
    assert 'stdout' in detail['content'] and 'pass 1' in detail['content']
    assert repair.load(root)['budget']['attempts_used'] == 7


def test_split_modify_selftest_relay_retains_progress_and_batches_plan_submit(attempt, monkeypatch):
    """新上下文携带上一调用修改及当前自测，计划更新可与提交同批且不自动提交。"""
    from backend.app.models import TaskStatus
    from backend.app.runtime.contracts import ModelResult
    from backend.app.runtime.model import build_messages
    root, db, task, _, _ = attempt
    requests = []
    batches = [[('replace', {'path': 'product/index.html', 'old': 'fixture', 'new': 'fixed fixture'}),
                ('update_plan', {'steps': ['修复已写入，待自测'], 'reason': '保持接力工作线索',
                                 'findings': ['fixture展示已修改'], 'open_questions': ['等待独立浏览器验证'],
                                 'next_action': '全量自测后提交'})],
               [('run_unit_tests', {})],
               [('update_plan', {'steps': ['修复及当前自测完成'], 'reason': '按已完成证据交接'}), ('submit_unit_for_test', {})]]

    class FixedModel:
        """固定响应通过实际主循环复现跨批次修改后接力。"""
        provider = 'deepseek'
        model_name = 'fixed-progress'

        def build_payload(self, request):
            """使用实际序列化确认新模型上下文的协议边界。"""
            return {'messages': build_messages(request, include_reasoning=True)}

        def call(self, task_id, request):
            """第三次请求检查实证，再由固定模型主动提交。"""
            requests.append(request)
            if len(requests) == 3:
                context = request.context
                assert len(build_messages(request, True)) == 2
                facts = context['current_task_facts']
                assert facts['changes'][0]['path'] == 'product/index.html'
                assert facts['changes'][0]['latest_write_matches_current_files']
                assert facts['self_test']['state'] == 'current_passed'
                assert facts['self_test']['matches_current_files']
                assert context['work_progress']['value']['findings'] == ['fixture展示已修改']
                assert context['work_progress']['applicability'] == 'current'
                assert '不得把历史执行成功当作当前代码已验证' not in request.instructions
                assert 'current_task_facts是当前事实' in request.instructions
                assert not facts['submission']['automatic_submit']
            batch = batches.pop(0)
            return ModelResult(request.request_id, 1, '', [ToolCall(f'progress-{len(requests)}-{i}', name, parameters) for i, (name, parameters) in enumerate(batch)], 'tool_calls', {'reasoning_content': f'progress-thinking-{len(requests)}'})

    monkeypatch.setattr(worker, 'create_model_runtime', lambda *args: FixedModel())
    task.status = TaskStatus.running
    db.commit()
    assert worker.process_task(db)
    state = repair.load(root)
    assert state['state'] == 'submitted' and len(requests) == 3
    assert state['session']['plan']['steps'] == ['修复及当前自测完成']
    checkpoint = next((root / 'evidence').glob('repair-session-*-checkpoint.json'))
    history = json.loads(checkpoint.read_text())
    assert history[0]['reasoning_content'] == 'progress-thinking-1'
    assert history[0]['action']['tool_name'] == 'replace'
    assert history[-1]['action']['tool_name'] == 'submit_unit_for_test'
    assert state['budget']['attempts_used'] == 7
