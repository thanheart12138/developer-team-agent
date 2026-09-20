"""用户授权的付费多模块手动基准，不由 pytest 自动收集。"""

import inspect
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
import time

root = Path(sys.argv[sys.argv.index('--root') + 1]) if '--root' in sys.argv else Path(tempfile.mkdtemp(prefix='content-workbench-deepseek-'))
root.mkdir(parents=True, exist_ok=True)
max_http = int(sys.argv[sys.argv.index('--max-http') + 1]) if '--max-http' in sys.argv else 200
max_step = int(sys.argv[sys.argv.index('--max-step') + 1]) if '--max-step' in sys.argv else 200
os.environ['SIMULATOR_DATABASE_URL'] = f'sqlite+pysqlite:///{root}/test.db'
os.environ['SIMULATOR_WORKSPACE_ROOT'] = str(root / 'workspace')

import httpx
from sqlalchemy import select
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Event, Message, Step, StepRun, StepStatus, Task, TaskStatus, TraceRecord
from backend.app.runtime import model, worker
from backend.app.runtime.tracing import sanitize

model.KIMI_STEPS.clear()
worker.MAX_MODEL_CALLS_PER_STEP = max_step
worker.FIXED_PRODUCT_CONSTRAINTS = [
    '原生 HTML、CSS、JavaScript 多模块软件，模块职责和接口由架构及 Dev Design 明确',
    '使用 localStorage 保存单用户业务数据，不引入产品依赖、数据库或构建工具',
    '使用 Node 内置测试框架，测试入口 product.test.js',
    'Python Playwright 验证真实浏览器，本地静态 HTTP 启动与健康检查',
    '本地 HTTP 仅用于预览和验证，来源链接仅保存和打开，不抓取网页',
]
adapted = root / 'adapter'
adapted.mkdir(exist_ok=True)
for name in ('handle_product_docs', 'handle_reviewed_doc', 'handle_develop', 'handle_test', 'handle_verify'):
    source = inspect.getsource(getattr(worker, name))
    source = source.replace('固定单模块，并明确', '按已批准架构划分多个模块，并明确')
    source = source.replace('固定的原生 HTML、CSS、JavaScript 单模块软件', '原生 HTML、CSS、JavaScript 多模块软件，按批准的设计实现 localStorage 持久化')
    source = source.replace('calculator.test.js', 'product.test.js')
    source = source.replace('不需要公网、域名或安装包', '不需要公网、域名或安装包；允许原生 JavaScript 多模块与 localStorage')
    if name == 'handle_develop':
        # 正式 Worker 已支持通用入口，测试仅放宽已获授权的产品范围提示。
        source = source.replace('instructions = """', 'instructions = """必须生成设计规定的全部模块文件。Node 测试覆盖模块协作；浏览器验证覆盖原始需求完整流程和边界。\n')
    (adapted / f'{name}.py').write_text(source)
    exec(compile(source, str(adapted / f'{name}.py'), 'exec'), worker.__dict__)

calls = int(sys.argv[sys.argv.index('--prior-calls') + 1]) if '--prior-calls' in sys.argv else 0
original_stream = httpx.Client.stream

def bounded_stream(self, method, url, **kwargs):
    # 在每次实际模型 HTTP 请求前计数，传输重试也受整个测试预算约束。
    global calls
    if str(url).endswith('/chat/completions'):
        if calls >= max_http:
            raise RuntimeError(f'baseline_total_http_budget_{max_http}_exceeded')
        calls += 1
        (root / 'call-count.json').write_text(json.dumps(calls))
        sent = root / 'sent-requests'
        sent.mkdir(exist_ok=True)
        (sent / f'{calls:03d}.json').write_text(json.dumps(sanitize(kwargs.get('json', {})), ensure_ascii=False, indent=2))
        print('MODEL_HTTP', calls, flush=True)
    return original_stream(self, method, url, **kwargs)

httpx.Client.stream = bounded_stream
Base.metadata.create_all(engine)
requirement = Path('docs/CONTENT_WORKBENCH_REQUIREMENTS_V1_AI_DRAFT.md').read_text()
requirement += '\n\n本次用户确认的执行约束：原生 JavaScript 多模块、localStorage 持久化，无新增依赖；架构与 Dev Design 由被测试系统生成。布局简单即可。优先级采用高／中／低三档；只有删除已关联素材时需要影响确认。单用户正常保存与重启是本次存储验收范围，不增加云同步或复杂灾难恢复。'
print('ROOT', root, flush=True)
with SessionLocal() as db:
    diagnostic = '--verify-existing' in sys.argv
    resume = '--resume' in sys.argv
    if resume:
        task = db.scalar(select(Task).order_by(Task.id))
        if task is None:
            raise RuntimeError('resume_task_missing')
        if '--reset-current-slice-attempt' in sys.argv:
            progress_path = Path(task.workspace_path) / 'evidence/slice-progress.json'
            progress = json.loads(progress_path.read_text())
            pending = next((entry for entry in progress['slices'] if entry.get('status') != 'passed'), None)
            if pending is None:
                raise RuntimeError('resume_pending_slice_missing')
            pending['status'] = 'planned'
            pending['attempt'] = 0
            pending['generation'] = int(pending.get('generation', 0)) + 1
            pending.pop('test', None)
            pending.pop('report', None)
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + '\n')
            print('RESET_SLICE_ATTEMPT', pending['card']['id'], flush=True)
        if ('--resume-internal' in sys.argv and task.status == TaskStatus.failed
                and task.cur_step in {Step.test, Step.start_product, Step.verify_product}):
            # 诊断基准修复 Runtime 后，从已保留的集成失败证据重新进入定向返修。
            task.cur_step = Step.develop
            task.status = TaskStatus.running
            task.failure_reason = None
            db.commit()
        elif ('--resume-internal' in sys.argv and task.status in {TaskStatus.waiting_user, TaskStatus.failed}
                and task.cur_step in {Step.architecture_docs, Step.develop}):
            latest_run = db.scalar(select(StepRun).where(StepRun.task_id == task.id).order_by(StepRun.id.desc()))
            task.status = TaskStatus.running
            task.failure_reason = None
            latest_run.status = StepStatus.running
            latest_run.error = None
            latest_run.finished_at = None
            db.commit()
    else:
        task = Task(task_name='content workbench diagnostic verification' if diagnostic else 'content workbench DeepSeek baseline', status=TaskStatus.pending, cur_step=Step.test if diagnostic else Step.product_docs)
        db.add(task)
        db.flush()
        task.workspace_path = str(root / 'workspace' / str(task.id))
        if diagnostic:
            source_root = Path(sys.argv[sys.argv.index('--verify-existing') + 1])
            for directory in ('docs', 'product'):
                shutil.copytree(source_root / 'workspace/1' / directory, Path(task.workspace_path) / directory)
            requirement = '原始自动任务失败；本任务仅独立验证其已有生成产物，不计为完整基准成功。\n' + requirement
        db.add(Message(task_id=task.id, role='user', content=requirement))
        db.commit()
    for iteration in range(200):
        db.refresh(task)
        print('STATE', iteration, task.status.value, task.cur_step.value, flush=True)
        if task.status in {TaskStatus.failed, TaskStatus.waiting_acceptance, TaskStatus.succeeded}:
            break
        if task.status == TaskStatus.waiting_user:
            run = db.scalar(select(StepRun).where(StepRun.task_id == task.id).order_by(StepRun.id.desc()))
            candidate = Path(task.workspace_path) / 'docs' / f'product-v{run.attempt}-candidate.md'
            if task.cur_step == Step.product_docs and candidate.is_file():
                print('CANDIDATE', candidate, flush=True)
                # 测试控制核对候选后放行，不绕过正式审批事件。
                for _ in range(900):
                    if (root / 'approve').is_file():
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError('candidate_review_timeout')
                db.add(Event(task_id=task.id, type='document_approval', data={'document_type': 'product', 'approved': True, 'document_version': run.attempt}))
                db.commit()
                worker.process_pending_event(db)
            elif task.cur_step == Step.product_docs and '--auto-decide' in sys.argv:
                # 用户已授权测试代理决定非关键界面细节，避免把布局选择升级为人工阻塞。
                answer = ('采用同一页面内的模块切换；工作台点击任务后切换到内容任务模块的编辑视图。'
                          '布局保持简单，不新增弹窗或独立页面。')
                db.add(Event(task_id=task.id, type='user_message', data={'content': answer}))
                db.commit()
                worker.process_pending_event(db)
            else:
                latest = db.scalar(select(Message).where(Message.task_id == task.id, Message.role == 'assistant').order_by(Message.id.desc()))
                print('QUESTION', latest.content if latest else '', flush=True)
                break
        else:
            worker.process_task(db)
    db.refresh(task)
    traces = list(db.scalars(select(TraceRecord).where(TraceRecord.task_id == task.id)))
    usage = []
    for trace in traces:
        if trace.type == 'model_response':
            detail = json.loads((Path(task.workspace_path) / trace.detail_path).read_text())
            usage.append(detail['payload'].get('raw_response', {}).get('usage', {}))
    registry = json.loads(Path('prompts/registry.json').read_text(encoding='utf-8'))['prompts']
    summary = dict(root=str(root), workspace=task.workspace_path, status=task.status.value, step=task.cur_step.value, failure_reason=task.failure_reason, result_url=task.result_url, process_id=task.process_id, calls=calls, max_http=max_http, max_step=max_step, prompt_versions={name:{'version':entry['active'], 'sha256':entry['sha256']} for name, entry in registry.items()}, traces=len(traces), usage=usage, repair_round=task.repair_round)
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print('SUMMARY', json.dumps(summary, ensure_ascii=False), flush=True)
