"""模块／功能设计、真实 Node 测试修复闭环与恢复的机制验证。"""

import copy
import json
import uuid

import pytest

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Message, Step, StepRun, StepStatus, Task, TaskStatus
from backend.app.runtime import unit_workflow as units, worker
from backend.app.runtime.contracts import ToolCall, ToolResult
from backend.app.runtime.tools import ToolRuntime


def setup_function():
    # 每项验证使用独立的内存数据库。
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def plan_fixture(root):
    # 构造两个功能和装配模块，验收规则独立于故障实现。
    docs = root / 'docs'
    docs.mkdir(exist_ok=True)
    (docs / 'product.md').write_text('先计算两数之和，再平方；错误后恢复。')
    (docs / 'architecture.md').write_text('计算模块分加法和平方功能，界面只依赖平方接口。')
    plan = {'version':1, 'product_hash':worker.content_hash((docs / 'product.md').read_text()),
        'architecture_hash':worker.content_hash((docs / 'architecture.md').read_text()),
        'modules':[{'id':'math', 'responsibility':'计算', 'public_interfaces':['add(a,b)', 'squareSum(a,b)']},
                   {'id':'ui', 'responsibility':'装配', 'public_interfaces':['render()']}],
        'units':[{'id':'add', 'module_id':'math', 'kind':'feature', 'name':'加法', 'scope':'两个数求和', 'depends_on':[],
                  'implementation_files':['product/add.cjs'], 'test_files':['product/add.test.cjs'], 'acceptance_criteria':['2+3=5，负数相加正确']},
                 {'id':'square', 'module_id':'math', 'kind':'feature', 'name':'平方', 'scope':'调用加法后平方', 'depends_on':['add'],
                  'implementation_files':['product/square.cjs'], 'test_files':['product/square.test.cjs'], 'acceptance_criteria':['(2+3)^2=25']},
                 {'id':'ui', 'module_id':'ui', 'kind':'module', 'name':'界面', 'scope':'装配完整产品', 'depends_on':['square'],
                  'implementation_files':['product/index.html', 'product/verify_product.py', 'product/implementation.md'],
                  'test_files':['product/ui.test.cjs'], 'acceptance_criteria':['界面完整依赖可加载']}]}
    worker.write_json_atomic(docs / 'development-plan.json', plan)
    return plan


def task_run(db, root, step=Step.develop):
    # 建立真实 Worker 阶段，共享同一个模型调用预算和检查点。
    task = Task(task_name='units', cur_step=step, status=TaskStatus.running, workspace_path=str(root))
    db.add(task)
    db.flush()
    run = StepRun(task_id=task.id, step=step, status=StepStatus.running, attempt=1,
                  checkpoint_path=str(root / 'evidence/checkpoint.json'))
    db.add(run)
    db.commit()
    return task, run


def seed_designs(root, plan):
    # 提供已经评审的单元设计，设计内容含明确预期而非从代码反推。
    for name in ['shared-contract'] + [u['id'] for u in plan['units']]:
        path = root / units.design_path(plan, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{name} 设计：遵守 add 与 squareSum 契约。')
    (root / 'docs/dev-design.md').write_text('设计索引')


def developer(root, fail_first=False, always_fail=False, blocked=False):
    # 让 Fake 模型调用真实写入工具，测试与修复仍由真实 Node 执行。
    calls = []

    def loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        # 按功能模拟实现，同时保留模型收到的真实失败反馈。
        identifier = context['unit']['id']
        calls.append((identifier, copy.deepcopy(context)))
        if blocked:
            return 'BLOCKED: 输入范围需要用户确认。'
        broken = always_fail or (fail_first and identifier == 'add' and sum(c[0] == 'add' for c in calls) == 1)
        files = {
            'add':{'product/add.cjs':"module.exports=(a,b)=>a-b;" if broken else "module.exports=(a,b)=>a+b;",
                'product/add.test.cjs':"const test=require('node:test');const assert=require('node:assert/strict');const add=require('./add.cjs');test('sum',()=>{assert.equal(add(2,3),5);assert.equal(add(-2,-3),-5)});"},
            'square':{'product/square.cjs':"const add=require('./add.cjs');module.exports=(a,b)=>add(a,b)**2;",
                'product/square.test.cjs':"const test=require('node:test');const assert=require('node:assert/strict');test('square sum',()=>assert.equal(require('./square.cjs')(2,3),25));"},
            'ui':{'product/index.html':'<html><body>测试产物</body></html>', 'product/verify_product.py':'# Fake 不作为浏览器能力证据',
                'product/implementation.md':'add → square → ui',
                'product/ui.test.cjs':"const test=require('node:test');const assert=require('node:assert/strict');test('wired',()=>assert.equal(require('./square.cjs')(2,3),25));"}}
        parent = str(uuid.uuid4())
        for path, content in files[identifier].items():
            result = worker.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), 'write',
                {'path':path, 'content':content, 'overwrite':(root / path).exists()}), parent, kwargs['history_key'])
            assert result.status == 'succeeded'
        tested = worker.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), 'run_unit_tests', {}), parent, kwargs['history_key'])
        assert tested.status == 'succeeded'
        if not tested.output['passed']:
            if sum(c[0] == identifier for c in calls) >= 3:
                raise RuntimeError('unit_tests_failed:' + identifier)
            return loop(db, task, run, instructions, input_text,
                        {**context, 'unit_test_feedback':{**tested.output, 'expectations':context['unit']['acceptance_criteria']}}, tools, **kwargs)
        submitted = worker.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), 'submit_unit_for_test', {}), parent, kwargs['history_key'])
        assert submitted.status == 'succeeded'
        return 'SUBMITTED_FOR_TEST'

    return loop, calls


@pytest.mark.parametrize('change,reason', [
    ('cycle', 'dependency_or_cycle'), ('unknown', 'dependency_or_cycle'), ('duplicate', 'duplicate_file_owner'),
    ('escape', 'path_outside_product'), ('test_name', 'invalid_test_file'), ('entry', 'product_entries_required'),
    ('reserved', 'reserved_unit_id'), ('duplicate_operation', 'duplicate_operation_owner'),
])
def test_invalid_plan_cannot_advance(tmp_path, change, reason):
    # 无效依赖、文件和模块边界必须在生成或执行前被拒绝。
    plan = plan_fixture(tmp_path)
    if change == 'cycle': plan['units'][0]['depends_on'] = ['square']
    if change == 'unknown': plan['units'][0]['depends_on'] = ['unknown']
    if change == 'duplicate': plan['units'][1]['implementation_files'] = ['product/add.cjs']
    if change == 'escape': plan['units'][0]['implementation_files'] = ['product/../../outside']
    if change == 'test_name': plan['units'][0]['test_files'] = ['product/not-a-test.js']
    if change == 'entry': plan['units'][2]['implementation_files'].remove('product/index.html')
    if change == 'reserved': plan['units'][0]['id'] = 'shared-contract'
    if change == 'duplicate_operation':
        plan['modules'][0]['public_interfaces'].append('remove(id)')
        plan['units'][0]['acceptance_criteria'] = ['remove(id) 返回删除成功']
        plan['units'][1]['acceptance_criteria'] = ['remove(id) 返回保护结果']
    with pytest.raises(ValueError, match=reason):
        units.ordered_units(plan, tmp_path)


def test_multi_unit_module_kind_is_normalized_without_retry(tmp_path, monkeypatch):
    # 核心 module 加其他 feature 是可确定的调度标签错误，程序规范化后直接推进。
    plan = plan_fixture(tmp_path)
    plan['units'][0]['kind'] = 'module'
    current = tmp_path / 'docs/development-plan.json'
    worker.write_json_atomic(current, {**plan, 'product_hash':'stale'})
    calls = []
    def loop(*args, **kwargs):
        calls.append(kwargs['history_key'])
        return json.dumps(plan)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.architecture_docs)
        units.ensure_plan(db, task, run, ToolRuntime(tmp_path))
    saved = json.loads(current.read_text())
    assert len(calls) == 1
    assert [unit['kind'] for unit in saved['units'] if unit['module_id'] == 'math'] == ['feature', 'feature']
    assert saved['normalizations'] == [{'module_id':'math', 'unit_ids':['add'],
                                         'change':'module_to_feature_for_multi_unit_module'}]


def test_plan_generation_is_bound_to_formal_inputs(tmp_path, monkeypatch):
    # 架构完成生成计划，恢复不再调用模型，正式上游改变后不得使用旧计划。
    plan = plan_fixture(tmp_path)
    current = tmp_path / 'docs/development-plan.json'
    # 不删除文件，写入不同血缘模拟需要首次生成正式版本的状态。
    worker.write_json_atomic(current, {**plan, 'product_hash':'stale'})
    calls = []
    def loop(*args, **kwargs):
        # 模拟架构规划器返回结构化清单。
        calls.append(kwargs['history_key'])
        return json.dumps(plan)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.architecture_docs)
        units.ensure_plan(db, task, run, ToolRuntime(tmp_path))
        units.ensure_plan(db, task, run, ToolRuntime(tmp_path))
        assert len(calls) == 1
        assert (tmp_path / 'docs/development-plan-v1.json').is_file()
        (tmp_path / 'docs/product.md').write_text('新的正式需求')
        with pytest.raises(ValueError, match='upstream_changed'):
            units.load_plan(tmp_path)


def test_invalid_plan_feedback_is_bounded(tmp_path, monkeypatch):
    # 无效计划必须收到校验反馈，三次仍无效则停止而不补造设计。
    plan = plan_fixture(tmp_path)
    worker.write_json_atomic(tmp_path / 'docs/development-plan.json', {**plan, 'product_hash':'stale'})
    captured = []
    def loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        # 固定返回缺测试的计划，验证程序反馈和停止条件。
        captured.append(context)
        bad = copy.deepcopy(plan)
        bad['units'][0]['test_files'] = []
        return json.dumps(bad)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.architecture_docs)
        with pytest.raises(RuntimeError, match='unit_plan_validation_failed'):
            units.ensure_plan(db, task, run, ToolRuntime(tmp_path))
        assert len(captured) == 3
        assert captured[1]['validation_feedback']['error'] == 'unit_plan_invalid_test_files'
        assert 'previous_response' not in captured[1]['validation_feedback']
        assert not (tmp_path / 'docs/development-plan-v1.json').exists()


def test_separate_designs_and_index(tmp_path, monkeypatch):
    # 共享契约先于功能设计，独立评审后正式化，根级文件不拼接详细正文。
    plan = plan_fixture(tmp_path)
    captured = []
    def loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        # 文档作者真实写入受限候选，独立 Reviewer 只返回 readiness。
        captured.append(copy.deepcopy(context))
        if kwargs.get('tool_schemas') == []:
            return json.dumps({'action':'ready', 'issues':[], 'question':None})
        path = next(iter(tools.writable))
        call = ToolCall(str(uuid.uuid4()), 'write', {'path':str(path.relative_to(tmp_path)),
            'content':'DETAILED_CONTENT_SENTINEL', 'overwrite':False})
        assert worker.execute_tool(db, task, run, tools, call).status == 'succeeded'
        return 'done'
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.dev_design)
        worker.handle_reviewed_doc(db, task, run, ToolRuntime(tmp_path), 'dev_design')
        assert task.cur_step == Step.develop
        assert len(captured) == 8
        assert 'DETAILED_CONTENT_SENTINEL' not in (tmp_path / 'docs/dev-design.md').read_text()
        assert all((tmp_path / units.design_path(plan, u['id'])).is_file() for u in plan['units'])
        assert all('shared_contract' in c for c in captured[2:])


def test_design_reviewer_invalid_json_retries_same_candidate(tmp_path, monkeypatch):
    # Reviewer JSON 截断时重试同一候选，不生成第二份设计或直接终止任务。
    captured = []
    def loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        captured.append((instructions, copy.deepcopy(context)))
        if kwargs.get('tool_schemas') != []:
            path = next(iter(tools.writable))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('精简设计')
            return 'done'
        if not context.get('protocol_error'):
            return '{"action":"revise","issues":["截断'
        return json.dumps({'action':'ready', 'issues':[], 'question':''})
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.dev_design)
        assert units.reviewed_design(db, task, run, 'docs/dev-design/v1/sample.md',
                                     '样例 Dev Design', '单元输入', {'user_answers':[]})
    assert len(captured) == 3
    assert captured[-1][1]['protocol_error']['instruction'].startswith('返回完整 JSON')
    assert (tmp_path / 'docs/dev-design/v1/sample.md').read_text() == '精简设计'
    assert len(list((tmp_path / 'docs/dev-design/v1').glob('*draft-*.md'))) == 1


def test_design_reviewer_allows_fourth_candidate_to_resolve_dependency_conflict(tmp_path, monkeypatch):
    # 内部职责冲突可由第四份候选在既有依赖契约内收敛，不提前终止或打扰用户。
    captured = []
    review_count = 0

    def loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        nonlocal review_count
        captured.append(instructions)
        if kwargs.get('tool_schemas') == []:
            review_count += 1
            return json.dumps({'action':'ready' if review_count == 4 else 'revise',
                               'issues':[] if review_count == 4 else ['在当前单元内适配既有依赖接口'],
                               'question':''}, ensure_ascii=False)
        path = next(iter(tools.writable))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'候选 {review_count + 1}')
        return 'done'

    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.dev_design)
        assert units.reviewed_design(db, task, run, 'docs/dev-design/v1/sample.md',
                                     '样例 Dev Design', '单元输入', {'user_answers':[]})
    assert review_count == 4
    assert all('不得要求修改其接口或职责' in instruction
               for instruction in captured if '独立设计评审' not in instruction)
    assert (tmp_path / 'docs/dev-design/v1/sample.md').read_text() == '候选 4'


def test_internal_contract_choice_is_revised_without_user_intervention():
    # 共享契约与当前单元描述冲突属于工程裁决，不能进入 waiting_user。
    review = {'action':'clarify', 'issues':['返回形态冲突'],
              'question':'是以共享契约为准，还是改为当前单元 AC 并修订共享契约？'}
    normalized = units.normalize_internal_clarification(review, {'shared_contract':'固定返回对象'})
    assert normalized['action'] == 'revise'
    assert normalized['question'] == ''


def test_failure_feedback_fix_and_next_unit_gate(tmp_path, monkeypatch):
    # 加法先失败后修复，通过前不能开发平方；测试也覆盖先前通过的单元。
    plan = plan_fixture(tmp_path)
    seed_designs(tmp_path, plan)
    loop, calls = developer(tmp_path, fail_first=True)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path)
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert [c[0] for c in calls] == ['add', 'add', 'square', 'ui']
        failure = calls[1][1]['unit_test_feedback']
        assert failure['result']['output']['exit_code'] != 0
        assert failure['expectations'] == plan['units'][0]['acceptance_criteria']
        progress = json.loads((tmp_path / 'evidence/development-progress.json').read_text())
        assert all(s['status'] == 'passed' for s in progress['units'].values())
        ui_report = json.loads((tmp_path / progress['units']['ui']['report']).read_text())
        assert 'add.test.cjs' in ui_report['command'] and 'square.test.cjs' in ui_report['command']
        assert task.cur_step == Step.test and run.status == StepStatus.succeeded


def test_repeated_failure_stops_before_dependents(tmp_path, monkeypatch):
    # 三次真实测试仍失败则终止，不能推进依赖功能。
    plan = plan_fixture(tmp_path)
    seed_designs(tmp_path, plan)
    loop, calls = developer(tmp_path, always_fail=True)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path)
        with pytest.raises(RuntimeError, match='unit_tests_failed:add'):
            worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert [c[0] for c in calls] == ['add'] * 3
        assert not (tmp_path / 'product/square.cjs').exists()
        assert task.cur_step == Step.develop


def test_recovery_requires_current_versions(tmp_path, monkeypatch):
    # 原通过进度可恢复，文件外部改变后必须重测修复，不能复用旧成功。
    plan = plan_fixture(tmp_path)
    seed_designs(tmp_path, plan)
    loop, calls = developer(tmp_path)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path)
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        calls.clear()
        task.cur_step = Step.develop
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert calls == []
        (tmp_path / 'product/add.cjs').write_text('module.exports=(a,b)=>a-b;')
        task.cur_step = Step.develop
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert calls[0][0] == 'add'


def test_unit_ownership_and_scoped_snapshot(tmp_path):
    # 当前单元不能修改依赖，文件快照持续刷新且不携带无关模块全文。
    plan = plan_fixture(tmp_path)
    tools = units.UnitTools(tmp_path, ['product/square.cjs'], ['product/add.cjs'])
    (tmp_path / 'product/add.cjs').write_text('dependency')
    (tmp_path / 'product/unrelated.js').write_text('UNRELATED_FULLTEXT')
    assert tools.execute(ToolCall('bad', 'write', {'path':'product/add.cjs', 'content':'bad', 'overwrite':True})).error == 'unit_write_outside_owned_files'
    assert tools.execute(ToolCall('exec', 'exec', {'action':'run', 'command':'exit 0'})).error == 'unit_tool_not_allowed'
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path)
        context = {'unit_file_scope':['product/add.cjs', 'product/square.cjs']}
        value = worker.build_tool_context(task, run, context, [], 'unit')
        assert value['current_product_files'] == {'product/add.cjs':'dependency'}
        (tmp_path / 'product/add.cjs').write_text('latest')
        assert worker.build_tool_context(task, run, context, [], 'unit')['current_product_files']['product/add.cjs'] == 'latest'
        assert 'UNRELATED_FULLTEXT' not in json.dumps(value)


@pytest.mark.parametrize('stdout', ['# tests 0\n', '# tests 1\n# skipped 1\n', '# tests 1\n# todo 1\n'])
def test_empty_or_skipped_test_cannot_pass(stdout):
    # 退出成功不能替代实际测试执行。
    result = ToolResult('test', 'exec', 'succeeded', {'exit_code':0, 'stdout':stdout})
    assert not units.test_passed(result, {}, {})


def test_design_gap_waits_for_user(tmp_path, monkeypatch):
    # 设计缺口应等待决定，不能推进下一功能或执行虚假测试。
    plan = plan_fixture(tmp_path)
    seed_designs(tmp_path, plan)
    loop, calls = developer(tmp_path, blocked=True)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path)
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert task.status == TaskStatus.waiting_user and run.status == StepStatus.waiting_user
        assert task.cur_step == Step.dev_design
        assert json.loads((tmp_path / 'evidence/unit-design-gap.json').read_text())['active'] is True
        assert len(calls) == 1


def test_design_clarification_can_resume_after_answer(tmp_path, monkeypatch):
    # 用户补充回答后不能反复复用旧 clarify 评审。
    plan_fixture(tmp_path)
    captured = []
    def loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        # 未回答时阻塞，收到回答后重新生成并通过评审。
        captured.append(context['user_answers'])
        if kwargs.get('tool_schemas') == []:
            return json.dumps({'action':'ready' if context['user_answers'] else 'clarify',
                               'issues':[], 'question':'确认输入范围？'})
        path = next(iter(tools.writable))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('明确接口与测试')
        return 'done'
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.dev_design)
        units.handle_design(db, task, run, ToolRuntime(tmp_path))
        assert task.status == TaskStatus.waiting_user
        db.add(Message(task_id=task.id, role='user', content='整数范围已确认'))
        task.status = TaskStatus.running
        run.status = StepStatus.running
        db.commit()
        units.handle_design(db, task, run, ToolRuntime(tmp_path))
        assert task.cur_step == Step.develop
        assert captured[-1] == ['整数范围已确认']


def test_confirmed_design_defect_creates_new_version(tmp_path, monkeypatch):
    # 已确认设计缺陷不能因正式文件存在而复用旧设计，旧版本保持可审计。
    plan = plan_fixture(tmp_path)
    seed_designs(tmp_path, plan)
    monkeypatch.setattr(worker, 'active_bug_triage', lambda task: {'classification':'dev_design_defect'})
    def loop(db, task, run, instructions, input_text, context, tools, **kwargs):
        # 新版本逐份独立评审，通过后保存新索引。
        if kwargs.get('tool_schemas') == []:
            return json.dumps({'action':'ready', 'issues':[], 'question':None})
        path = next(iter(tools.writable))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('修正后的设计')
        return 'done'
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path, Step.dev_design)
        units.handle_design(db, task, run, ToolRuntime(tmp_path))
        assert units.load_plan(tmp_path)['version'] == 2
        assert (tmp_path / 'docs/dev-design/v1/add.md').read_text().startswith('add 设计')
        assert (tmp_path / 'docs/dev-design/v2/add.md').read_text() == '修正后的设计'


def test_recovery_with_missing_files_keeps_failure_feedback(tmp_path, monkeypatch):
    # 失败单元恢复时文件不齐仍必须携带上次报告，不能丢失失败归属。
    plan = plan_fixture(tmp_path)
    seed_designs(tmp_path, plan)
    report = 'evidence/units/add-run-1-attempt-1.json'
    worker.write_json_atomic(tmp_path / report, {'unit_id':'add', 'result':{'error':'PREVIOUS_FAILURE'}})
    worker.write_json_atomic(tmp_path / 'evidence/development-progress.json', {
        'plan_hash':worker.content_hash(json.dumps(plan, sort_keys=True, ensure_ascii=False)),
        'shared_hash':worker.content_hash((tmp_path / units.design_path(plan, 'shared-contract')).read_text()),
        'design_hashes':{u['id']:worker.content_hash((tmp_path / units.design_path(plan, u['id'])).read_text()) for u in plan['units']},
        'units':{'add':{'status':'failed', 'attempt':1, 'report':report}}})
    loop, calls = developer(tmp_path)
    monkeypatch.setattr(worker, 'model_tool_loop', loop)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path)
        worker.handle_develop(db, task, run, ToolRuntime(tmp_path))
        assert calls[0][1]['unit_test_feedback']['result']['error'] == 'PREVIOUS_FAILURE'


def test_submit_checks_files_and_does_not_claim_test_pass(tmp_path):
    # 文件缺失或未自测拒绝提交，通过后仍需后续独立测试。
    owned = ['product/a.cjs', 'product/a.test.cjs']
    scoped = units.UnitTools(tmp_path, owned, [], submission_files=owned, test_files=[owned[1]])
    call = ToolCall('submit', 'submit_unit_for_test', {})
    assert scoped.execute(call).status == 'failed'
    for path, content in zip(owned, ['module.exports=1;', "require('node:test')('works',()=>require('node:assert/strict').equal(require('./a.cjs'),1));"]):
        assert scoped.execute(ToolCall(path, 'write', {'path':path,'content':content,'overwrite':False})).status == 'succeeded'
    assert scoped.execute(call).error == 'unit_self_test_required'
    assert scoped.execute(ToolCall('test', 'run_unit_tests', {})).output['passed']
    result = scoped.execute(call)
    assert result.status == 'succeeded' and result.output['test_state'] == 'pending'
    assert scoped.restore_submission(result.output)
    (tmp_path / owned[0]).write_text('changed')
    assert not scoped.restore_submission(result.output)
    assert units.UnitTools(tmp_path, owned, []).execute(call).status == 'failed'


def strict_context(owned):
    # 为真实模型循环提供当前单元与显式提交约束，不调用远程模型。
    return {'unit':{'id':'fixture'}, 'owned_files':owned, 'unit_file_scope':owned,
            'unit_test_feedback':None,'require_unit_submission':True}


@pytest.mark.parametrize('change', ['implementation', 'test', 'dependency'])
def test_self_test_pass_expires_when_scope_changes(tmp_path, change):
    # 实现、测试或依赖变化都使自测通过过期，不能借旧通过结果提交。
    paths = ['product/a.cjs', 'product/a.test.cjs', 'product/dependency.cjs']
    tools = units.UnitTools(tmp_path, paths[:2], paths[2:], submission_files=paths[:2],
                            self_test_files=paths, test_files=[paths[1]])
    for path, text in zip(paths, ['module.exports=1;', "require('node:test')('check',()=>{});", 'module.exports=2;']):
        target = tmp_path/path;target.parent.mkdir(exist_ok=True);target.write_text(text)
    result = tools.execute(ToolCall('t', 'run_unit_tests', {}))
    assert result.output['passed']
    target = tmp_path/paths[['implementation','test','dependency'].index(change)]
    target.write_text(target.read_text() + '\n// version changed')
    assert tools.execute(ToolCall('s', 'submit_unit_for_test', {})).error == 'unit_self_test_stale'
    assert tools.execute(ToolCall('t2', 'run_unit_tests', {})).output['passed']
    assert tools.execute(ToolCall('s2', 'submit_unit_for_test', {})).status == 'succeeded'


def test_self_test_rejects_command_override_and_failed_test(tmp_path):
    # 自测无法替换命令，真实失败或缺文件都不能授权提交。
    owned=['product/a.test.cjs']
    tools=units.UnitTools(tmp_path,owned,[],submission_files=owned,test_files=owned)
    missing=tools.execute(ToolCall('m','run_unit_tests',{}))
    assert not missing.output['passed'] and 'unit_files_missing' in missing.output['result']['error']
    tools.execute(ToolCall('w','write',{'path':owned[0],'content':"require('node:test')('fails',()=>{throw Error('fail')});",'overwrite':False}))
    assert tools.execute(ToolCall('override','run_unit_tests',{'command':'true'})).status=='failed'
    failed=tools.execute(ToolCall('t','run_unit_tests',{}))
    assert failed.status=='succeeded' and not failed.output['passed']
    assert failed.output['result']['output']['exit_code']==1
    assert tools.execute(ToolCall('s','submit_unit_for_test',{})).error=='unit_self_test_failed'
    assert units.UnitTools(tmp_path,owned,[]).execute(ToolCall('disabled','run_unit_tests',{})).status=='failed'


def test_development_self_test_fix_retest_and_submit(tmp_path, monkeypatch):
    # 真实模型循环内执行失败、修复、重测和提交，下一请求能获取输出与版本状态。
    from backend.app.runtime.contracts import ModelResult
    owned=['product/a.cjs','product/a.test.cjs'];received=[]
    def develop(runtime,task_id,request):
        # 按已确认的期望模拟模型决策，真实工具与 Node 负责验证。
        received.append(copy.deepcopy(request.context));count=len(received)
        if count==1:
            actions=[ToolCall('code','write',{'path':owned[0],'content':'module.exports=0;','overwrite':False}),
                     ToolCall('tests','write',{'path':owned[1],'content':"require('node:test')('one',()=>require('node:assert/strict').equal(require('./a.cjs'),1));",'overwrite':False}),
                     ToolCall('test1','run_unit_tests',{})]
        elif count==2:
            assert request.context['unit_self_test']['result']['output']['exit_code']==1
            assert request.context['development_state']['test_state']=='failed'
            actions=[ToolCall('fix','write',{'path':owned[0],'content':'module.exports=1;','overwrite':True})]
        elif count==3:
            assert request.context['development_state']['test_state']=='stale'
            assert request.context['development_state']['next_action']=='run_unit_tests'
            actions=[ToolCall('test2','run_unit_tests',{})]
        else:
            assert request.context['development_state']['test_state']=='passed'
            assert request.context['development_state']['next_action']=='submit_unit_for_test'
            assert any(row['tool_name']=='run_unit_tests' for row in request.context['current_requested_data'])
            actions=[ToolCall('submit','submit_unit_for_test',{})]
        return ModelResult(request.request_id,1,'',actions,'tool_calls')
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call',develop)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        tools=units.UnitTools(tmp_path,owned,[],submission_files=owned,test_files=[owned[1]])
        assert worker.model_tool_loop(db,task,run,'develop','design',strict_context(owned),tools,
            tool_schemas=[units.RUN_UNIT_TESTS_SCHEMA,units.SUBMIT_UNIT_SCHEMA]+[s for s in units.TOOL_SCHEMAS if s['function']['name'] in {'read','write'}],
            stop_when=lambda:tools.submitted_hashes is not None)=='SUBMITTED_FOR_TEST'
        assert len(received)==4


def test_old_submission_without_self_test_cannot_restore(tmp_path):
    # 旧版本仅文件齐备的提交证据不能绕过新增自测门禁。
    owned=['product/a.test.cjs'];(tmp_path/'product').mkdir();(tmp_path/owned[0]).write_text("require('node:test')('one',()=>{});")
    tools=units.UnitTools(tmp_path,owned,[],submission_files=owned,test_files=owned)
    assert not tools.restore_submission({'file_hashes':tools.submission_versions()})


def test_self_test_checkpoint_restores_before_submission(tmp_path, monkeypatch):
    # 自测完成后中断，恢复必须向模型提供真实通过结果，仍需明确提交。
    from backend.app.runtime.contracts import ModelResult
    owned=['product/a.test.cjs'];received=[]
    def interrupted(runtime,task_id,request):
        # 第一轮自测，第二轮模拟进程中断，恢复轮只提交。
        received.append(request.context)
        if len(received)==1:
            actions=[ToolCall('w','write',{'path':owned[0],'content':"require('node:test')('one',()=>{});",'overwrite':False}),
                     ToolCall('test','run_unit_tests',{})]
        elif len(received)==2:
            raise RuntimeError('controlled_interruption')
        else:
            assert request.context['development_state']['test_state']=='passed'
            actions=[ToolCall('submit','submit_unit_for_test',{})]
        return ModelResult(request.request_id,1,'',actions,'tool_calls')
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call',interrupted)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        def tools():
            # 模拟新进程重新创建受控工具，不沿用内存自测状态。
            return units.UnitTools(tmp_path,owned,[],submission_files=owned,test_files=owned)
        scoped=tools()
        schemas=[units.RUN_UNIT_TESTS_SCHEMA,units.SUBMIT_UNIT_SCHEMA]+[s for s in units.TOOL_SCHEMAS if s['function']['name']=='write']
        with pytest.raises(RuntimeError,match='model_transport_failed:RuntimeError'):
            worker.model_tool_loop(db,task,run,'develop','design',strict_context(owned),scoped,tool_schemas=schemas,
                                  stop_when=lambda:scoped.submitted_hashes is not None)
        restored=tools()
        assert worker.model_tool_loop(db,task,run,'develop','design',strict_context(owned),restored,tool_schemas=schemas,
                                     stop_when=lambda:restored.submitted_hashes is not None)=='SUBMITTED_FOR_TEST'
        assert len(received)==3


def test_plain_completion_cannot_replace_submit(tmp_path, monkeypatch):
    # 完成文本即使文件齐备也不能绕过提交，三次无效文本后有界停止。
    from backend.app.runtime.contracts import ModelResult
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call',
        lambda runtime, task_id, request: ModelResult(request.request_id,1,'done',[],'stop'))
    with SessionLocal() as db:
        task, run = task_run(db,tmp_path)
        scoped = units.UnitTools(tmp_path,['product/a.cjs'],[],submission_files=['product/a.cjs'])
        scoped.execute(ToolCall('w','write',{'path':'product/a.cjs','content':'x','overwrite':False}))
        with pytest.raises(RuntimeError,match='unit_submission_required'):
            worker.model_tool_loop(db,task,run,'develop','design',strict_context(['product/a.cjs']),scoped,
                tool_schemas=[units.SUBMIT_UNIT_SCHEMA],stop_when=lambda:scoped.submitted_hashes is not None)
        assert run.model_call_count == 3 and scoped.submitted_hashes is None


def test_alternating_reads_with_new_descriptions_stop_without_progress(tmp_path, monkeypatch):
    # 交替读取且描述变化仍是无文件进展，四轮提示、八轮终止。
    from backend.app.runtime.contracts import ModelResult
    owned=['product/a.cjs','product/b.cjs']; received=[]
    def read_again(runtime,task_id,request):
        # 模拟交替诊断工具循环，保留每次程序生成的提醒。
        received.append(copy.deepcopy(request.context))
        count=len(received)
        return ModelResult(request.request_id,1,'inspect',[ToolCall(str(count),'read',{
            'path':owned[count % 2], 'description':f'inspect {count}'})],'tool_calls')
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call',read_again)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        scoped=units.UnitTools(tmp_path,owned,[],submission_files=owned)
        for path in owned:
            scoped.execute(ToolCall(path,'write',{'path':path,'content':'x','overwrite':False}))
        with pytest.raises(RuntimeError,match='unit_development_no_progress'):
            worker.model_tool_loop(db,task,run,'develop','design',strict_context(owned),scoped,
                tool_schemas=[units.SUBMIT_UNIT_SCHEMA],stop_when=lambda:scoped.submitted_hashes is not None)
        assert len(received)==8 and received[4]['unit_no_progress']['instruction']


def test_current_passing_self_test_gets_one_submission_turn_at_idle_limit(tmp_path, monkeypatch):
    # 第八批刚取得真实通过时不得在提交前误杀，下一批只能立即交接。
    from backend.app.runtime.contracts import ModelResult
    owned = ['product/a.test.cjs']
    scoped = units.UnitTools(tmp_path, owned, [], submission_files=owned, test_files=owned)
    scoped.execute(ToolCall('w', 'write', {'path':owned[0],
        'content':"require('node:test')('ok',()=>{});", 'overwrite':False}))
    result = scoped.execute(ToolCall('t', 'run_unit_tests', {}))
    assert result.output['passed'] is True
    versions = units.file_hashes(tmp_path, owned)
    checkpoint = tmp_path / 'evidence/checkpoint.json'
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps([{'history_key':'unit', 'model_request_id':f'r{i}',
        'action':{'call_id':f'c{i}', 'tool_name':'read', 'parameters':{'path':owned[0]}},
        'result':{'status':'succeeded'}, 'unit_versions_before':versions,
        'unit_versions_after':versions} for i in range(8)]))
    received = []
    def submit(runtime, task_id, request):
        received.append(copy.deepcopy(request.context))
        return ModelResult(request.request_id, 1, '', [ToolCall('s', 'submit_unit_for_test', {})], 'tool_calls')
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call', submit)
    with SessionLocal() as db:
        task, run = task_run(db, tmp_path)
        run.checkpoint_path = str(checkpoint)
        db.commit()
        worker.model_tool_loop(db, task, run, 'develop', 'design', strict_context(owned), scoped,
            tool_schemas=[units.SUBMIT_UNIT_SCHEMA], stop_when=lambda:scoped.submitted_hashes is not None,
            history_key='unit')
    assert scoped.submitted_hashes == versions
    assert '只能立即调用' in received[0]['unit_no_progress']['instruction']


def test_submission_must_be_last_and_recovers_without_model_call(tmp_path, monkeypatch):
    # 提交后还有写入时拒绝交接；正确提交及恢复不额外调用模型。
    from backend.app.runtime.contracts import ModelResult
    owned=['product/a.test.cjs']; received=[]
    def finish(runtime,task_id,request):
        # 首批模拟错误提交顺序，第二批仅提交。
        received.append(request)
        actions=[ToolCall('s'+str(len(received)),'submit_unit_for_test',{})]
        if len(received)==1:
            actions.append(ToolCall('w','write',{'path':owned[0],'content':"require('node:test')('ready',()=>{});",'overwrite':False}))
        else:
            actions.insert(0,ToolCall('test','run_unit_tests',{}))
        return ModelResult(request.request_id,1,'',actions,'tool_calls')
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call',finish)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        scoped=units.UnitTools(tmp_path,owned,[],submission_files=owned,test_files=owned)
        context=strict_context(owned)
        assert worker.model_tool_loop(db,task,run,'develop','design',context,scoped,
            tool_schemas=[units.RUN_UNIT_TESTS_SCHEMA,units.SUBMIT_UNIT_SCHEMA],stop_when=lambda:scoped.submitted_hashes is not None)=='SUBMITTED_FOR_TEST'
        assert len(received)==2
        restored=units.UnitTools(tmp_path,owned,[],submission_files=owned,test_files=owned)
        assert worker.model_tool_loop(db,task,run,'develop','design',context,restored,
            tool_schemas=[units.RUN_UNIT_TESTS_SCHEMA,units.SUBMIT_UNIT_SCHEMA],stop_when=lambda:restored.submitted_hashes is not None)=='SUBMITTED_FOR_TEST'
        assert len(received)==2 and restored.submitted_hashes is not None


@pytest.mark.parametrize('patch',[
    {'unit_ids':['unknown']},{'unit_ids':['ui','ui']},{'confidence':True},{'confidence':0.2},
    {'category':'cross_unit_error','unit_ids':['ui']},{'repair_target':''},{'reason':''},
])
def test_invalid_diagnosis_never_authorizes_repair(tmp_path,monkeypatch,patch):
    # 非法归属、低置信、空修复目标均进入澄清，不授权写入。
    plan=plan_fixture(tmp_path);seed_designs(tmp_path,plan)
    decision={'category':'test_script_error','unit_ids':['ui'],'confidence':0.95,
              'reason':'验证输入未重置，与已确认需求不一致','repair_target':'修正测试输入，保留需求预期'}
    decision.update(patch)
    def diagnose(*args,**kwargs):
        # 定位器无工具权限，只返回模拟诊断对象。
        assert kwargs['tool_schemas']==[]
        return json.dumps(decision)
    monkeypatch.setattr(worker,'model_tool_loop',diagnose)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        result=units.integration_repair_decision(db,task,run,ToolRuntime(tmp_path),plan,{'error':'verify failed'})
        assert result['category']=='unclear' and result['unit_ids']==[]


def test_diagnosis_cache_is_bound_to_current_versions(tmp_path,monkeypatch):
    # 版本未变复用诊断，文件变化需要新诊断，原责任目标不冒充当前结果。
    plan=plan_fixture(tmp_path);seed_designs(tmp_path,plan);calls=[]
    def diagnose(*args,**kwargs):
        # 返回有据且受限的责任单元，并统计模型调用。
        calls.append(1)
        return json.dumps({'category':'test_script_error','unit_ids':['ui'],'confidence':0.95,
                          'reason':'脚本保留错误输入','repair_target':'重置输入，不改需求'})
    monkeypatch.setattr(worker,'model_tool_loop',diagnose)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        tools=ToolRuntime(tmp_path);failure={'error':'verify failed'}
        units.integration_repair_decision(db,task,run,tools,plan,failure)
        units.integration_repair_decision(db,task,run,tools,plan,failure)
        assert len(calls)==1
        tools.execute(ToolCall('w','write',{'path':'product/verify_product.py','content':'changed','overwrite':False}))
        units.integration_repair_decision(db,task,run,tools,plan,failure)
        assert len(calls)==2


@pytest.mark.parametrize('category,targets,expected',[
    ('test_script_error',['ui'],['ui']),
    ('implementation_error',['add'],['add']),
    ('cross_unit_error',['add','square'],['add','square']),
    ('cross_unit_error',['square','ui'],['square','ui']),
    ('design_conflict',['add','square'],[]),
    ('unclear',[],[]),
])
def test_integration_failure_only_reaches_responsible_units(tmp_path,monkeypatch,category,targets,expected):
    # 真实 Node 校验后注入集成失败，定位只交责任单元，设计冲突不调用开发。
    plan=plan_fixture(tmp_path);seed_designs(tmp_path,plan)
    develop,calls=developer(tmp_path)
    monkeypatch.setattr(worker,'model_tool_loop',develop)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        worker.handle_develop(db,task,run,ToolRuntime(tmp_path));calls.clear()
        failure=StepRun(task_id=task.id,step=Step.verify_product,status=StepStatus.failed,
                        attempt=1,error='browser failure')
        db.add(failure);db.flush()
        task.repair_round=1;task.cur_step=Step.develop
        repair=StepRun(task_id=task.id,step=Step.develop,status=StepStatus.running,attempt=2,
                       checkpoint_path=str(tmp_path/'evidence/repair-checkpoint.json'))
        db.add(repair);db.commit()
        def route(*args,**kwargs):
            # 无工具诊断明确责任，开发仍走真实受限工具与 Node。
            if kwargs.get('tool_schemas')==[]:
                return json.dumps({'category':category,'unit_ids':targets,'confidence':0.95,
                    'reason':'确认失败依据及文件所有权','repair_target':'按原需求修复当前责任文件'})
            return develop(*args,**kwargs)
        monkeypatch.setattr(worker,'model_tool_loop',route)
        worker.handle_develop(db,task,repair,ToolRuntime(tmp_path))
        assert [item[0] for item in calls]==expected
        if expected:
            assert task.cur_step==Step.test
            assert all(item[1]['global_failure']['diagnosis']['unit_ids']==targets for item in calls)
        else:
            assert task.status==TaskStatus.waiting_user and task.cur_step==Step.dev_design


def test_noop_writes_are_not_progress(tmp_path,monkeypatch):
    # 同字节反复写入不能重置无进展预算，描述变化也不影响版本判定。
    from backend.app.runtime.contracts import ModelResult
    owned=['product/a.cjs'];calls=[]
    def rewrite(runtime,task_id,request):
        # 模拟写工具成功但内容不变的循环。
        calls.append(1)
        return ModelResult(request.request_id,1,'',[ToolCall(str(len(calls)),'write',{
            'path':owned[0],'content':'same','overwrite':True,'description':str(len(calls))})],'tool_calls')
    monkeypatch.setattr('backend.app.runtime.model.ChatCompletionsRuntime.call',rewrite)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        scoped=units.UnitTools(tmp_path,owned,[],submission_files=owned)
        scoped.execute(ToolCall('initial','write',{'path':owned[0],'content':'same','overwrite':False}))
        with pytest.raises(RuntimeError,match='unit_development_no_progress'):
            worker.model_tool_loop(db,task,run,'develop','design',strict_context(owned),scoped,
                tool_schemas=[units.SUBMIT_UNIT_SCHEMA],stop_when=lambda:scoped.submitted_hashes is not None)
        assert len(calls)==8


def test_idle_counts_batches_and_resets_after_version_change():
    # 同一批多个读取只算一次，无进展计数在实际版本变化后重新开始。
    changed={'model_request_id':'write','unit_versions_before':{'a':'old'},'unit_versions_after':{'a':'new'}}
    history=[changed]
    for call in range(4):
        for tool in range(2):
            history.append({'model_request_id':str(call),'unit_versions_before':{'a':'new'},'unit_versions_after':{'a':'new'}})
    assert worker.unit_idle_calls(history,{'a':'new'})==4
    assert worker.unit_idle_calls(history,{'a':'external'})==0


def test_failed_self_test_blocks_overlapping_read_until_file_change():
    # 自测失败区域已读取后，改变行号或描述不能绕过修改门禁；非重叠依赖仍可读取。
    history = [{
        'history_key': 'slice:a:1',
        'action': {'tool_name': 'run_unit_tests', 'parameters': {}},
        'result': {'status': 'succeeded', 'output': {'passed': False}},
    }, {
        'history_key': 'slice:a:1',
        'action': {'tool_name': 'read', 'parameters': {
            'path': 'product/a.test.js', 'start_line': 220, 'end_line': 245,
            'description': 'first diagnosis'}},
        'result': {'status': 'succeeded', 'output': {'content': 'failure'}},
    }]
    overlapping = ToolCall('overlap', 'read', {
        'path': 'product/a.test.js', 'start_line': 223, 'end_line': 232,
        'description': 'different description'})
    dependency = ToolCall('dependency', 'read', {
        'path': 'product/a.js', 'start_line': 1, 'end_line': 40,
        'description': 'necessary dependency'})

    assert worker._repeated_failed_self_test_read(history, 'slice:a:1', overlapping) is True
    assert worker._repeated_failed_self_test_read(history, 'slice:a:1', dependency) is False

    history.append({
        'history_key': 'slice:a:1',
        'action': {'tool_name': 'replace', 'parameters': {'path': 'product/a.test.js'}},
        'result': {'status': 'succeeded', 'output': {}},
    })
    assert worker._repeated_failed_self_test_read(history, 'slice:a:1', overlapping) is False


def test_failed_unit_change_requires_test_on_next_model_batch():
    # 同一批可以完成相关修改，下一批必须先复测；复测后按新结果重新决定。
    history = [{
        'history_key': 'slice:a:1', 'model_request_id': 'modify',
        'action': {'tool_name': 'replace', 'parameters': {'path': 'product/a.test.js'}},
        'result': {'status': 'succeeded', 'output': {}},
    }]
    read = ToolCall('read', 'read', {'path': 'product/a.test.js'})
    test = ToolCall('test', 'run_unit_tests', {})

    assert worker._failed_unit_change_requires_test(
        history, 'slice:a:1', 'modify', read, external_failure=True) is False
    assert worker._failed_unit_change_requires_test(
        history, 'slice:a:1', 'next', read, external_failure=True) is True
    assert worker._failed_unit_change_requires_test(
        history, 'slice:a:1', 'next', test, external_failure=True) is False

    history.append({
        'history_key': 'slice:a:1', 'model_request_id': 'next',
        'action': {'tool_name': 'run_unit_tests', 'parameters': {}},
        'result': {'status': 'succeeded', 'output': {'passed': False}},
    })
    assert worker._failed_unit_change_requires_test(
        history, 'slice:a:1', 'after-test', read, external_failure=True) is False


def test_submission_changed_before_test_cannot_validate_unsubmitted_version(tmp_path,monkeypatch):
    # 提交与程序测试之间的外部变化不能被当成本次已提交版本。
    plan=plan_fixture(tmp_path);seed_designs(tmp_path,plan)
    develop,_=developer(tmp_path)
    def change_after_submit(*args,**kwargs):
        # 完成有效提交后模拟文件被外部改写。
        result=develop(*args,**kwargs)
        file=tmp_path/'product/add.cjs'
        file.write_text(file.read_text()+'\n// external change')
        return result
    monkeypatch.setattr(worker,'model_tool_loop',change_after_submit)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        with pytest.raises(RuntimeError,match='unit_submission_stale'):
            worker.handle_develop(db,task,run,ToolRuntime(tmp_path))
        assert not (tmp_path/'evidence/units/add-run-1-attempt-1.json').exists()


def test_old_developing_checkpoint_with_files_requires_new_submission(tmp_path,monkeypatch):
    # 旧 developing 状态文件齐备也要重新交接，不按存在直接进入测试。
    plan=plan_fixture(tmp_path);seed_designs(tmp_path,plan)
    develop,calls=developer(tmp_path)
    monkeypatch.setattr(worker,'model_tool_loop',develop)
    with SessionLocal() as db:
        task,run=task_run(db,tmp_path)
        worker.handle_develop(db,task,run,ToolRuntime(tmp_path));calls.clear()
        path=tmp_path/'evidence/development-progress.json';progress=json.loads(path.read_text())
        progress['units']['add']['status']='developing'
        worker.write_json_atomic(path,progress)
        task.cur_step=Step.develop
        worker.handle_develop(db,task,run,ToolRuntime(tmp_path))
        assert calls[0][0]=='add' and calls[0][1]['require_unit_submission']


def test_unit_tools_preview_large_file_and_allow_line_range(tmp_path):
    path = tmp_path / 'product/large.js'
    path.parent.mkdir(parents=True)
    path.write_text(''.join(f'line-{index}\n' for index in range(1, 251)), encoding='utf-8')
    tools = units.UnitTools(tmp_path, ['product/large.js'], [])

    preview = tools.execute(ToolCall('preview', 'read', {'path':'product/large.js'}))
    selected = tools.execute(ToolCall('selected', 'read', {
        'path':'product/large.js', 'start_line':220, 'end_line':225}))

    assert preview.status == 'succeeded'
    assert preview.output['truncated'] is True
    assert preview.output['total_lines'] == 250
    assert preview.output['hint'] == 'large_file_preview_use_start_line_and_end_line'
    assert 'line-201' not in preview.output['content']
    assert selected.output['content'] == ''.join(f'line-{index}\n' for index in range(220, 226))
