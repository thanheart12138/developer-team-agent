"""仅在隔离副本显式设置输出上限，诊断继续完整链路，不算原流程无干预成功。"""

import json
import os
from pathlib import Path
import shutil
import sys

source = Path(sys.argv[1])
root = Path(sys.argv[2])
shutil.copytree(source, root)
os.environ['SIMULATOR_DATABASE_URL'] = f'sqlite+pysqlite:///{root}/test.db'
os.environ['SIMULATOR_WORKSPACE_ROOT'] = str(root / 'workspace')

import httpx
from sqlalchemy import select
from backend.app.database import SessionLocal
from backend.app.models import Message, StepRun, Task, TaskStatus, TraceRecord
from backend.app.runtime import model, worker
from backend.app.runtime.tracing import sanitize

model.KIMI_STEPS.clear()
worker.MAX_MODEL_CALLS_PER_STEP = 200
worker.FIXED_PRODUCT_CONSTRAINTS = [
    '原生 HTML、CSS、JavaScript 多模块软件，模块职责和接口由架构及 Dev Design 明确',
    '使用 localStorage 保存单用户业务数据，不引入产品依赖、数据库或构建工具',
    '使用 Node 内置测试框架，自动发现测试文件',
    'Python Playwright 验证真实浏览器，本地静态 HTTP 启动与健康检查',
    '本地 HTTP 仅用于预览和验证，来源链接仅保存和打开，不抓取网页',
]
for path in (root / 'adapter').glob('*.py'):
    # 沿用原基准的产品范围适配，不改变正式服务代码。
    exec(compile(path.read_text(), str(path), 'exec'), worker.__dict__)

original_payload = model.DeepSeekRuntime.build_payload


def bounded_payload(runtime, request):
    # 诊断副本显式扩大单次输出上限，原任务和正式服务保持原配置。
    return {**original_payload(runtime, request), 'max_tokens':16384}


model.DeepSeekRuntime.build_payload = bounded_payload
calls = json.loads((source / 'call-count.json').read_text())
prior_calls = calls
original_stream = httpx.Client.stream


def bounded_stream(client, method, url, **kwargs):
    # 延续原测试实际 HTTP 计数，整个测试合计最多二百次。
    global calls
    if str(url).endswith('/chat/completions'):
        if calls >= 200:
            raise RuntimeError('shared_http_budget_200_exceeded')
        calls += 1
        (root / 'call-count.json').write_text(json.dumps(calls))
        (root / 'sent-requests' / f'{calls:03d}.json').write_text(json.dumps(sanitize(kwargs['json']), ensure_ascii=False, indent=2))
        print('MODEL_HTTP', calls, flush=True)
    return original_stream(client, method, url, **kwargs)


httpx.Client.stream = bounded_stream
with SessionLocal() as db:
    task = db.get(Task, 1)
    task.workspace_path = str(root / 'workspace/1')
    for run in db.scalars(select(StepRun).where(StepRun.task_id == task.id)):
        # 修正副本检查点路径，避免写回原始失败证据。
        run.checkpoint_path = str(root / Path(run.checkpoint_path).relative_to(source))
    db.commit()
    for iteration in range(200):
        db.refresh(task)
        print('STATE', iteration, task.status.value, task.cur_step.value, flush=True)
        if task.status in {TaskStatus.failed, TaskStatus.waiting_acceptance, TaskStatus.succeeded}:
            break
        if task.status == TaskStatus.waiting_user:
            latest = db.scalar(select(Message).where(Message.task_id == task.id, Message.role == 'assistant').order_by(Message.id.desc()))
            print('QUESTION', latest.content if latest else '', flush=True)
            break
        worker.process_task(db)
    db.refresh(task)
    usage = []
    for trace in db.scalars(select(TraceRecord).where(TraceRecord.type == 'model_response')):
        detail = json.loads((Path(task.workspace_path) / trace.detail_path).read_text())
        usage.append(detail['payload'].get('raw_response', {}).get('usage', {}))
    summary = {'root':str(root), 'workspace':task.workspace_path, 'status':task.status.value,
               'step':task.cur_step.value, 'failure_reason':task.failure_reason, 'result_url':task.result_url,
               'process_id':task.process_id, 'calls':calls, 'prior_calls':prior_calls, 'usage':usage,
               'repair_round':task.repair_round, 'diagnostic_max_tokens':16384,
               'original_pipeline_succeeded':False}
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print('SUMMARY', json.dumps(summary, ensure_ascii=False), flush=True)
