"""有界真实 DeepSeek 模块／功能开发回归，不由 pytest 自动执行。"""

import json
import os
from pathlib import Path
import sys
import time
from experiment_storage import prepare_experiment_root, read_call_count, save_call_count

resume = '--resume' in sys.argv
verified_repair_probe = '--verified-repair-probe' in sys.argv
if verified_repair_probe and not resume:
    # 先核对持久源目录，避免用已丢失的历史临时路径创建返修任务。
    if '--verified-source' not in sys.argv:
        raise ValueError('experiment_verified_source_required')
    verified_source = prepare_experiment_root('unit-verified-source-',
        sys.argv[sys.argv.index('--verified-source') + 1], resume=True)
root = prepare_experiment_root('unit-workflow-', sys.argv[1], resume=resume)
os.environ['SIMULATOR_DATABASE_URL'] = f'sqlite+pysqlite:///{root}/test.db'
os.environ['SIMULATOR_WORKSPACE_ROOT'] = str(root / 'workspace')

import httpx
from sqlalchemy import select
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Event, Message, Step, StepRun, StepStatus, Task, TaskStatus, TraceRecord
from backend.app.runtime import model, worker
from backend.app.runtime.tracing import sanitize

calls = read_call_count(root) if resume else (int(sys.argv[2]) if len(sys.argv) > 2 else 0)
save_call_count(root, calls)
development_probe = '--develop-probe' in sys.argv
full_flow = '--full-flow' in sys.argv
assert not (full_flow and development_probe)
http_limit = 300
current_only = '--current-only' in sys.argv
integration_fault = '--integration-fault' in sys.argv
self_test_fault = '--self-test-fault' in sys.argv
fault_applied = False
if self_test_fault:
    from backend.app.runtime.unit_workflow import UnitTools
    assert development_probe and verified_repair_probe and not integration_fault
    original_self_test = UnitTools._run_unit_tests

    def self_test_with_fault(tools):
        # 仅隔离夹具首次加法自测前注入实现错误，保证真实失败结果反馈给模型。
        global fault_applied
        if not fault_applied and 'product/src/add.mjs' in (tools.submission_files or []):
            path = tools.workspace / 'product/src/add.mjs'
            original = path.read_text(encoding='utf-8')
            faulty = 'export function add(a,b) { return a-b; }\nexport default add;\n'
            path.write_text(faulty, encoding='utf-8')
            worker.write_json_atomic(root / 'self-test-fault.json', {'file':'product/src/add.mjs',
                'before_hash':worker.content_hash(original), 'after_hash':worker.content_hash(faulty),
                'purpose':'controlled arithmetic defect before first self-test', 'calls':calls})
            fault_applied = True
            print('INJECTED_SELF_TEST_FAULT', flush=True)
        return original_self_test(tools)

    UnitTools._run_unit_tests = self_test_with_fault
if current_only:
    from backend.app.runtime.tool_summaries import ToolSummaryStore
    original_project = ToolSummaryStore.project

    def current_projection(store, history, run_id, history_key, code_hashes):
        # 对照试验去掉自动历史投影，保留未解决失败和当前请求的读取／查询数据。
        value = original_project(store, history, run_id, history_key, code_hashes)
        latest = history[-1].get('model_request_id') if history else None
        value['current_requested_data'] = [entry['result'] for entry in history
            if entry.get('model_request_id') == latest and entry.get('result')
            and entry.get('action', {}).get('tool_name') in {
                'read', 'get_file_change_history', 'get_model_call_summaries', 'get_tool_execution_detail'}]
        value.update(tool_history=[], tool_summaries=[], recent_model_call_id=None, earlier_summary_count=0)
        return value

    ToolSummaryStore.project = current_projection
    original_messages = model.build_messages

    def current_messages(request):
        # 明确当前试验策略，避免原正式历史提示误导模型继续寻找自动摘要。
        messages = original_messages(request)
        body = json.loads(messages[1]['content'])
        context = body['context']
        for result in context.get('current_requested_data', []):
            output = result.get('output') or {}
            if result.get('tool_name') == 'read' and output.get('content') is not None and not output.get('truncated') and context.get('current_product_files', {}).get(output.get('path')) == output['content']:
                # 当前快照已经提供相同全文，读取回执仅引用它，避免重复传输。
                output.pop('content')
                output['content_source'] = 'current_product_files'
        messages[1]['content'] = json.dumps(body, ensure_ascii=False)
        messages[0]['content'] += '\n当前隔离对照策略覆盖历史提示：不自动提供历史交互或摘要；current_product_files 是当前文件快照，current_requested_data 是你当前请求的读取／查询结果。依据当前设计、文件及失败反馈继续开发，不重复请求已有文件。'
        return messages

    model.build_messages = current_messages
original_stream = httpx.Client.stream


def bounded_stream(client, method, url, **kwargs):
    # 每轮最多三百次实际 HTTP，传输重试计入；可传入本轮恢复计数，不合并旧轮。
    global calls
    if str(url).endswith('/chat/completions'):
        if calls >= http_limit:
            raise RuntimeError('unit_validation_total_http_budget_300_exceeded')
        calls += 1
        save_call_count(root, calls)
        (root / f'sent-{calls:03d}.json').write_text(json.dumps(sanitize(kwargs['json']), ensure_ascii=False, indent=2))
        print('MODEL_HTTP', calls, flush=True)
    return original_stream(client, method, url, **kwargs)


httpx.Client.stream = bounded_stream
model.KIMI_STEPS.clear()
Base.metadata.create_all(engine)
product = '''隔离机制验证任务，正式测试需求如下。开发原生 HTML/CSS/JavaScript 两模块软件：math 负责计算，ui 负责输入展示。
math 模块按两个功能单元设计与开发：add(a,b) 加法；squareSum(a,b) 必须调用 add 后平方。ui 只使用公共接口。
架构需决定共享契约、模块目录与依赖，不得跳过架构或 Dev Design；每个功能／模块均独立设计、开发、测试，依赖无环。
固定交互：页面两个有 label 的输入框 A 和 B，两个按钮「求和」「求和后平方」，输出区域有 id=result。
输入限定 -1000 到 1000 的十进制整数，空白、非数字、小数或超出范围均显示「输入错误」，之后有效输入可以正常使用。
2 和 3 求和显示 5，求和后平方显示 25；-2 和 3 分别显示 1、1。平方功能须通过明确接口复用加法。
不用存储、不新增依赖、不开网络请求，布局简单默认；入口、Node 测试、实现文档和 Playwright 验证遵守系统契约。
这是对已确认逐模块／功能流程的合成验证输入，业务范围和交互已明确，不扩展生产产品需求。'''
with SessionLocal() as db:
    if resume and full_flow:
        # 只恢复本轮已核实的 URL 运行事实澄清，不代答业务或架构决定。
        previous = json.loads((root / 'summary.json').read_text())
        assert previous['full_flow'] and previous['status'] == 'waiting_user' and previous['step'] == 'dev_design'
        task = db.get(Task, 1)
        assert task.workspace_path == str(root / 'workspace/1') and task.status == TaskStatus.waiting_user
        question = db.scalar(select(Message).where(Message.task_id == task.id, Message.role == 'assistant').order_by(Message.id.desc()))
        assert question.content.startswith('请确认 `verify_product.py` 执行时实际 URL')
        worker.write_json_atomic(root / 'summary-before-runtime-url-answer.json', previous)
        answer = ('已核实系统运行约定：Worker 启动产品 HTTP 服务后，将现有 URL 作为 argv[1] 传给 verify_product.py；'
                  '脚本不得自行启动服务，不使用 VERIFY_URL。缺 URL 时不能认定 AC6 或浏览器验收通过。'
                  '这是 backend/app/runtime/worker.py 的 handle_verify 已实现的调用行为，不新增业务规则。')
        worker.write_json_atomic(root / 'runtime-url-answer.json', {'question':question.content, 'answer':answer,
            'source':'backend/app/runtime/worker.py:handle_verify', 'calls_before_answer':calls})
        db.add(Event(task_id=task.id, type='user_message', data={'content':answer}))
        db.commit()
        worker.process_pending_event(db)
    elif resume:
        # 只恢复本测试已知的预算中断，保留原摘要、Trace、检查点与模型调用计数。
        previous = json.loads((root / 'summary.json').read_text())
        assert previous['calls'] == 30 and previous['failure_reason'] == 'model_transport_failed:RuntimeError'
        assert previous['prepared_design_development_probe'] and development_probe
        (root / 'summary-before-300.json').write_text(json.dumps(previous, ensure_ascii=False, indent=2))
        task = db.get(Task, 1)
        assert task.workspace_path == str(root / 'workspace/1') and task.status == TaskStatus.failed
        run = db.scalar(select(StepRun).where(StepRun.task_id == task.id).order_by(StepRun.id.desc()))
        assert run.step == Step.develop and run.status == StepStatus.failed
        task.status, task.failure_reason = TaskStatus.running, None
        run.status, run.error, run.finished_at = StepStatus.running, None, None
        db.commit()
    else:
        task = Task(task_name='unit workflow DeepSeek regression',
                    cur_step=Step.develop if development_probe else Step.product_docs if full_flow else Step.architecture_docs, status=TaskStatus.pending)
        db.add(task)
        db.flush()
        task.workspace_path = str(root / 'workspace/1')
        docs = Path(task.workspace_path) / 'docs'
        docs.mkdir(parents=True)
        if not full_flow:
            # 单独架构／开发探针需要固定需求，完整流程只从初始用户消息开始。
            (docs / 'product.md').write_text(product, encoding='utf-8')
        if development_probe:
            # 固定合成设计只用于单独验证开发机制，不当作真实自主架构设计通过。
            from backend.app.runtime.unit_workflow import design_path
            (docs / 'architecture.md').write_text('math 分 add 与 squareSum 功能；ui 依赖 math，使用 ES Modules .mjs。')
            plan = {'version':1, 'product_hash':worker.content_hash(product),
                    'architecture_hash':worker.content_hash((docs / 'architecture.md').read_text()),
                    'modules':[{'id':'math', 'responsibility':'纯计算', 'public_interfaces':['add(a,b)','squareSum(a,b)']},
                               {'id':'ui', 'responsibility':'输入校验和界面', 'public_interfaces':['parseInteger(raw)','init(root)']}],
                    'units':[]}
            for identifier, module, kind, dependencies, files, test, scope in [
                ('add','math','feature',[],['product/src/add.mjs'],'product/tests/add.test.mjs','导出 add(a,b)，两个数求和，2,3 得5；-2,3 得1，无副作用。'),
                ('square','math','feature',['add'],['product/src/square.mjs'],'product/tests/square.test.mjs','导出 squareSum(a,b)，静态导入 ./add.mjs 的 add 并调用后平方；2,3 得25；-2,3 得1。测试可核对源文件实际导入／调用路径，不添加探针接口。'),
                ('ui','ui','module',['add','square'],['product/src/ui.mjs','product/index.html','product/verify_product.py','product/implementation.md'],
                 'product/tests/ui.test.mjs','导出 parseInteger(raw) 和 init(root)，两个 label 为 A/B 的输入框，按钮求和／求和后平方，id=result。parseInteger 非法返回 null，有效返回整数；范围 -1000到1000，空白／非数字／小数／越界提示输入错误，修正后恢复。Node 测试纯解析和装配，Python Playwright 真实操作验收并使用 argv[1] 的现有 URL。模块在 Node 导入时不得访问未定义的 document。')]:
                plan['units'].append({'id':identifier,'module_id':module,'kind':kind,'name':identifier,'scope':scope,
                    'depends_on':dependencies,'implementation_files':files,'test_files':[test],'acceptance_criteria':[scope]})
            worker.write_json_atomic(docs / 'development-plan.json', plan)
            for identifier in ['shared-contract','add','square','ui']:
                path = Path(task.workspace_path) / design_path(plan, identifier)
                path.parent.mkdir(parents=True, exist_ok=True)
                scope = next((u['scope'] for u in plan['units'] if u['id'] == identifier),
                    '纯函数 add(a,b) 与 squareSum(a,b)，ES Modules .mjs，ui 使用数学公共接口；UI 输入错误返回统一文案，固定交互见正式需求。')
                path.write_text(scope, encoding='utf-8')
            (docs / 'dev-design.md').write_text('固定合成设计索引，仅验证单元开发机制。')
            if verified_repair_probe:
                # 仅返修探针复用已验证字节与测试进度，不作为新软件自主开发成功证据。
                source = verified_source / 'workspace/1'
                copied = []
                for unit in plan['units']:
                    for relative in unit['implementation_files'] + unit['test_files']:
                        destination = Path(task.workspace_path) / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes((source / relative).read_bytes())
                        copied.append(relative)
                for relative in ['evidence/development-progress.json','evidence/implementation-lineage.json']:
                    destination = Path(task.workspace_path) / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((source / relative).read_bytes())
                worker.write_json_atomic(root / 'verified-fixture.json', {'source':str(source),
                    'copied_files':copied,'hashes':worker.product_code_hashes(task),'purpose':'only integration repair probe'})
                task.cur_step = Step.test
                if self_test_fault:
                    # 复用产品但重新进入加法开发，让模型主动自测，不能按历史通过跳过。
                    evidence = Path(task.workspace_path) / 'evidence/development-progress.json'
                    progress = json.loads(evidence.read_text())
                    progress['units']['add'] = {'status':'developing', 'attempt':1}
                    worker.write_json_atomic(evidence, progress)
                    task.cur_step = Step.develop
        db.add(Message(task_id=task.id, role='user', content=product))
        db.commit()
    for iteration in range(300):
        db.refresh(task)
        print('STATE', iteration, task.status.value, task.cur_step.value, flush=True)
        if full_flow and task.status == TaskStatus.waiting_user and task.cur_step == Step.product_docs:
            # 完整测试仍保留产品审批门禁，测试控制读取候选后才写批准标记。
            run = db.scalar(select(StepRun).where(StepRun.task_id == task.id).order_by(StepRun.id.desc()))
            candidate = Path(task.workspace_path) / 'docs' / f'product-v{run.attempt}-candidate.md'
            if candidate.is_file():
                print('CANDIDATE', candidate, flush=True)
                deadline = time.monotonic() + 900
                while not (root / 'approve').is_file() and time.monotonic() < deadline:
                    time.sleep(1)
                if not (root / 'approve').is_file():
                    raise RuntimeError('candidate_review_timeout')
                db.add(Event(task_id=task.id, type='document_approval', data={
                    'document_type':'product', 'approved':True, 'document_version':run.attempt}))
                db.commit()
                worker.process_pending_event(db)
                db.refresh(task)
        if integration_fault and task.status == TaskStatus.waiting_acceptance and not fault_applied:
            # 初始真实验证通过后注入脚本断言错误，保留原文件与版本，不改正式任务。
            verifier = Path(task.workspace_path) / 'product/verify_product.py'
            original = verifier.read_text(encoding='utf-8')
            (root / 'fault-original-verify_product.py').write_text(original, encoding='utf-8')
            injected = '\nraise AssertionError("INJECTED_TEST_EXPECTATION: 正式需求 2+3=5，本验证脚本却要求 6，测试断言错误")\n'
            position = original.rfind('\nif __name__')
            # 放到入口前，防止脚本 sys.exit(main()) 使末尾故障代码不可达。
            verifier.write_text(original[:position] + injected + original[position:] if position >= 0 else original + injected, encoding='utf-8')
            worker.write_json_atomic(root / 'fault-injection.json', {'calls_before_fault':calls,
                'file':'product/verify_product.py','before_hash':worker.content_hash(original),
                'after_hash':worker.content_hash(verifier.read_text(encoding='utf-8')),
                'initial_status':task.status.value,'result_url':task.result_url})
            task.status, task.cur_step = TaskStatus.running, Step.verify_product
            db.commit()
            fault_applied = True
            print('INJECTED_VERIFY_FAULT', flush=True)
        if task.status in {TaskStatus.failed, TaskStatus.waiting_user, TaskStatus.waiting_acceptance, TaskStatus.succeeded}:
            break
        worker.process_task(db)
    db.refresh(task)
    usage = []
    for trace in db.scalars(select(TraceRecord).where(TraceRecord.type == 'model_response')):
        usage.append(json.loads((Path(task.workspace_path) / trace.detail_path).read_text())['payload'].get('raw_response', {}).get('usage', {}))
    summary = {'status':task.status.value, 'step':task.cur_step.value, 'failure_reason':task.failure_reason,
               'calls':calls, 'http_limit':http_limit, 'resumed':resume, 'current_only':current_only, 'result_url':task.result_url, 'process_id':task.process_id, 'usage':usage,
               'prepared_design_development_probe':development_probe,'integration_fault_applied':integration_fault and fault_applied,
               'verified_repair_probe':verified_repair_probe, 'self_test_fault_applied':self_test_fault and fault_applied,
               'full_flow':full_flow, 'budget_scope':'this validation round'}
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print('SUMMARY', json.dumps(summary, ensure_ascii=False), flush=True)
