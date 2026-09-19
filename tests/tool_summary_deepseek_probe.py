"""用户授权的真实历史查询探针，不由 pytest 收集；与完整基准共用 200 次总预算。"""

import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
baseline = Path(sys.argv[2])
prior_calls = json.loads((baseline / 'call-count.json').read_text())
limit = min(8, 200 - prior_calls)
if limit <= 0:
    raise RuntimeError('shared_http_budget_exhausted')
root.mkdir(parents=True, exist_ok=True)
os.environ['SIMULATOR_DATABASE_URL'] = f'sqlite+pysqlite:///{root}/test.db'
os.environ['SIMULATOR_WORKSPACE_ROOT'] = str(root / 'workspace')

import httpx
from sqlalchemy import select
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Step, StepRun, StepStatus, Task, TaskStatus, TraceRecord
from backend.app.runtime import model, worker
from backend.app.runtime.contracts import ToolCall
from backend.app.runtime.tool_summaries import ToolSummaryStore
from backend.app.runtime.tools import TOOL_SCHEMAS, ToolRuntime
from backend.app.runtime.tracing import sanitize

calls = 0
original_stream = httpx.Client.stream


def bounded_stream(client, method, url, **kwargs):
    # 传输重试也计入探针与整体预算，发送体脱敏保存以核对实际上下文。
    global calls
    if str(url).endswith('/chat/completions'):
        if calls >= limit:
            raise RuntimeError('probe_http_budget_exhausted')
        calls += 1
        (root / 'call-count.json').write_text(json.dumps(calls))
        (root / f'sent-{calls:03d}.json').write_text(json.dumps(sanitize(kwargs['json']), ensure_ascii=False, indent=2))
        print('MODEL_HTTP', calls, flush=True)
    return original_stream(client, method, url, **kwargs)


httpx.Client.stream = bounded_stream
model.KIMI_STEPS.clear()
worker.MAX_MODEL_CALLS_PER_STEP = limit
Base.metadata.create_all(engine)
with SessionLocal() as db:
    task = Task(task_name='historical query DeepSeek probe', cur_step=Step.develop,
                status=TaskStatus.running, workspace_path=str(root / 'workspace/1'))
    db.add(task)
    db.flush()
    run = StepRun(task_id=task.id, step=Step.develop, status=StepStatus.running, attempt=1,
                  checkpoint_path=str(Path(task.workspace_path) / 'evidence/checkpoint.json'))
    db.add(run)
    db.commit()
    tools = ToolRuntime(Path(task.workspace_path))
    history = []
    for parent, content in [('seed-old-model', '历史版本：蓝色'), ('seed-current-model', '当前版本：绿色')]:
        call = ToolCall(f'{parent}-write', 'write', {'path':'product/state.txt', 'content':content,
                                                  'overwrite':parent == 'seed-current-model', 'description':'构造历史查询样本'})
        result = worker.execute_tool(db, task, run, tools, call, parent, 'probe')
        history.append({'model_request_id':parent, 'history_key':'probe', 'action':call.__dict__, 'result':result.__dict__})
    worker.save_checkpoint(run, history)
    initial = worker.build_tool_context(task, run, {}, history, 'probe')
    assert '历史版本：蓝色' not in json.dumps(initial, ensure_ascii=False)
    assert '当前版本：绿色' in json.dumps(initial, ensure_ascii=False)
    text = worker.model_tool_loop(db, task, run,
        '这是只读审计，不修改或执行代码。必须实际使用 get_file_change_history 查询 product/state.txt；'
        '用 get_model_call_summaries 查询 seed-old-model；根据所得 summary_id 使用 get_tool_execution_detail，section=call，'
        '取回该历史写入的 content；用 read 读取当前 product/state.txt。四种工具都必须调用，不能从描述猜原文。'
        '完成后只输出 JSON：{"historical_content":"原始历史全文","current_content":"当前全文"}，不要 Markdown。',
        '核对历史与当前版本，并证明通过工具取回较早原文。', {}, tools,
        tool_schemas=[schema for schema in TOOL_SCHEMAS if schema['function']['name'] == 'read'], history_key='probe')
    answer = json.loads(text)
    assert answer == {'historical_content':'历史版本：蓝色', 'current_content':'当前版本：绿色'}, answer
    rows = [row for row in ToolSummaryStore(Path(task.workspace_path)).load() if row['parent_model_call_id'] not in {'seed-old-model', 'seed-current-model'}]
    assert {'get_file_change_history', 'get_model_call_summaries', 'get_tool_execution_detail', 'read'} <= {row['tool_name'] for row in rows}
    assert all(row['status'] == 'succeeded' for row in rows)
    traces = list(db.scalars(select(TraceRecord).where(TraceRecord.type == 'model_response')))
    usage = [json.loads((Path(task.workspace_path) / trace.detail_path).read_text())['payload'].get('raw_response', {}).get('usage', {}) for trace in traces]
    summary = {'status':'passed', 'calls':calls, 'shared_calls':prior_calls + calls,
               'answer':answer, 'tools':[row['tool_name'] for row in rows], 'usage':usage}
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print('SUMMARY', json.dumps(summary, ensure_ascii=False), flush=True)
