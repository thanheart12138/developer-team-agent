import os
import tempfile
import sys
from dataclasses import replace
from pathlib import Path
resume = '--resume' in sys.argv
root = (Path(sys.argv[sys.argv.index('--resume') + 1]) if resume
        else Path(tempfile.mkdtemp(prefix='context-full-deepseek-')))
os.environ['SIMULATOR_DATABASE_URL'] = f'sqlite+pysqlite:///{root}/test.db'
os.environ['SIMULATOR_WORKSPACE_ROOT'] = str(root / 'workspace')
import json
from sqlalchemy import select
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Task, TaskStatus, Step, StepRun, Message, Event, TraceRecord
from backend.app.runtime import worker, model
from backend.app.runtime.tracing import sanitize

# 仅覆盖本次隔离进程的模型路由和预算，不修改正式配置。
model.KIMI_STEPS.clear()
worker.MAX_REPAIR_ROUNDS = 2
legacy = '--legacy' in sys.argv
calls = 0
if resume:
    with SessionLocal() as previous_db:
        calls = len(list(previous_db.scalars(select(TraceRecord).where(TraceRecord.type == 'model_request'))))
original_call = model.DeepSeekRuntime.call
def bounded_call(self, task_id, request):
    # 所有实际传输尝试合计最多三十次。
    global calls
    if calls >= 30:
        raise RuntimeError('full_test_total_call_budget_exceeded')
    calls += 1
    (root / 'call-count.json').write_text(json.dumps(calls))
    print(f'MODEL_CALL {calls}', flush=True)
    # Legacy 模式仅重建优化前的请求内容，不撤销返修正确性修复。
    if legacy:
        context = dict(request.context)
        for key in ('input_source', 'document_sources', 'snapshot', 'failure_evidence_source'):
            context.pop(key, None)
        user_messages = list(self.db.scalars(select(Message.content).where(
            Message.task_id == task_id, Message.role == 'user').order_by(Message.id)))
        if 'conversation_history' in context:
            path = root / 'workspace' / str(task_id) / 'docs/product.md'
            context['current_product'] = path.read_text(encoding='utf-8') if path.is_file() else ''
            context['unpaired_user_requests'] = user_messages
        elif 'unpaired_user_requests' in context:
            context.pop('unpaired_user_requests')
            context['user_messages'] = user_messages
        if 'phase' in context:
            context['approved_product'] = request.input
        if 'previous_upstream' in context:
            context['upstream_diff'] = request.input
        if 'design_source' in context:
            context['approved_product'] = request.input
            if context['design_source'] == 'approved_product_and_constraints':
                context['dev_design'] = (f"正式产品需求：\n{request.input}\n\n现有架构：\n"
                    f"{context['existing_architecture'] or '无独立架构文档'}"
                    "\n\n项目固定实现约束：\n" + "\n".join(worker.FIXED_PRODUCT_CONSTRAINTS))
            if not context.get('previous_dev_design'):
                context['dev_design_diff'] = worker.unified_text_diff(
                    '', context['dev_design'], 'previous-missing', 'dev-design.md')
        request = replace(request, context=context)
    # Worker 请求 Trace 在本测试覆盖前生成；另存实际发送体，避免混淆两者。
    sent_dir = root / 'sent-requests'
    sent_dir.mkdir(exist_ok=True)
    (sent_dir / f'{calls:03d}.json').write_text(
        json.dumps(sanitize(self.build_payload(request)), ensure_ascii=False, indent=2))
    return original_call(self, task_id, request)
model.DeepSeekRuntime.call = bounded_call
requirement = ('做一个自用浏览器按钮计算器，检验普通计算与错误后恢复。仅鼠标按钮输入，不支持键盘或历史保存。'
               '数字0到9、小数点、加减乘除、等于和清空C。初始0；每个操作数至多一个小数点，重复小数点忽略，'
               '允许以小数点开始。只支持一次二元运算，不支持连续计算。未输入第二个数时等于无效果；'
               '计算后再按等于无效果；结果后按数字开始新计算，结果后运算符无效果。'
               '计算结果保留两位小数，四舍五入，例如1.235+0=1.24。除零显示Error；'
               '错误后输入新数字或C可恢复。C任何时候重置到0。验收：2+3=5.00，7-2=5.00，'
               '3*4=12.00，9/4=2.25；5/0=Error，随后输入6+4=10.00；长结果完整显示。'
               '原生HTML/CSS/JS单模块，不引入依赖，无网络请求、数据库或安装包；界面样式采用最简单默认。')
Base.metadata.create_all(engine)
print('ROOT', root, 'legacy', legacy, flush=True)
with SessionLocal() as db:
    if resume:
        task = db.get(Task, 1)
        if (root / 'call-count.json').is_file():
            calls = json.loads((root / 'call-count.json').read_text())
        worker.process_pending_event(db)
    else:
        task = Task(task_name='context full DeepSeek validation', status=TaskStatus.pending, cur_step=Step.product_docs)
        db.add(task); db.flush()
        task.workspace_path = str(root / 'workspace' / str(task.id))
        db.add(Message(task_id=task.id, role='user', content=requirement)); db.commit()
    for iteration in range(30):
        db.refresh(task)
        print('STATE', iteration, task.status.value, task.cur_step.value, flush=True)
        if task.status in {TaskStatus.failed, TaskStatus.waiting_acceptance, TaskStatus.succeeded}:
            break
        if task.status == TaskStatus.waiting_user:
            run = db.scalar(select(StepRun).where(StepRun.task_id==task.id).order_by(StepRun.id.desc()))
            candidate = Path(task.workspace_path) / 'docs' / f'product-v{run.attempt}-candidate.md'
            if task.cur_step == Step.product_docs and candidate.is_file():
                print('CANDIDATE', candidate, flush=True)
                # 暂停等待独立核对候选，外部批准文件仅用于隔离测试控制。
                import time
                for _ in range(300):
                    if (root / 'approve').is_file(): break
                    time.sleep(1)
                else: raise RuntimeError('candidate_review_timeout')
                event = Event(task_id=task.id, type='document_approval', data={'document_type': 'product', 'approved': True, 'document_version': run.attempt})
            else:
                latest = db.scalar(select(Message).where(Message.task_id==task.id, Message.role=='assistant').order_by(Message.id.desc()))
                print('QUESTION', latest.content if latest else '', flush=True)
                raise RuntimeError('requires_test_user_answer')
            db.add(event);db.commit();worker.process_pending_event(db)
        else:
            worker.process_task(db)
    db.refresh(task)
    traces = list(db.scalars(select(TraceRecord).where(TraceRecord.task_id==task.id).order_by(TraceRecord.sequence)))
    usage=[]
    for trace in traces:
        if trace.type=='model_response':
            detail=json.loads((Path(task.workspace_path)/trace.detail_path).read_text())
            usage.append(detail['payload'].get('raw_response',{}).get('usage',{}))
    summary=dict(root=str(root),workspace=task.workspace_path,status=task.status.value,step=task.cur_step.value,
                 failure_reason=task.failure_reason,result_url=task.result_url,process_id=task.process_id,
                 calls=calls,traces=len(traces),usage=usage,legacy=legacy)
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print('SUMMARY',json.dumps(summary,ensure_ascii=False),flush=True)
