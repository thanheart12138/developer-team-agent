"""显式任务Token账的跨渠道适配；不初始化、不授权、不改历史余额。"""
import json
from pathlib import Path
from . import task_budget


def prepare(root: Path | None, payload: dict) -> dict:
    """按已启用任务限额收窄输出cap；无预算的旧任务保持原行为。"""
    if root is None:
        return payload
    state=task_budget.load(root)
    if state is None:
        return payload
    key='max_output_tokens' if 'input' in payload else 'max_tokens'
    cap=payload.get(key,state['limits']['max_output_tokens'])
    if type(cap) is not int or cap<=0:
        raise task_budget.TaskBudgetError('task_budget_output_cap_invalid')
    return {**payload,key:min(cap,state['limits']['max_output_tokens'])}


def reserve(root: Path | None, provider: str, request_id: str, payload: dict, *, expected_budget_id: str | None = None):
    """最终发送体按UTF8字节保守预约，重试与回退共享同一任务账。"""
    if expected_budget_id is not None:
        require_bound(root, expected_budget_id)
    state = task_budget.load(root) if root is not None else None
    if state is None:
        if expected_budget_id is not None:
            raise task_budget.TaskBudgetError("experiment_token_budget_binding_mismatch")
        return None
    key='max_output_tokens' if 'input' in payload else 'max_tokens'
    size=len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))
    return task_budget.reserve(root,provider=provider,request_id=request_id,
                               input_estimate=size,max_output_tokens=payload[key],expected_budget_id=expected_budget_id)


def settle(root: Path | None, attempt, status: str, usage):
    """先保全已观察usage；未知或实际超额立即中断，不允许渠道回退。"""
    if attempt is None:
        return
    state=task_budget.finish(root,attempt,status=status,usage=usage)
    if state['attempts'][attempt['attempt']-1]['actual_tokens'] is None:
        raise task_budget.TaskBudgetError('task_budget_unresolved_attempt')
    if state['known_tokens']>state['limits']['total_tokens']:
        raise task_budget.TaskBudgetError('task_budget_actual_usage_exceeded')


def require_bound(root: Path | None, budget_id: str):
    """实验必须绑定已有明确预算身份，缺失、损坏或换账均在认证前拒绝。"""
    if root is None or not isinstance(budget_id,str) or not budget_id:
        raise task_budget.TaskBudgetError('experiment_token_budget_required')
    state=task_budget.load(root)
    if state is None or state['budget_id']!=budget_id:
        raise task_budget.TaskBudgetError('experiment_token_budget_binding_mismatch')
    if any(item['actual_tokens'] is None for item in state['attempts']):
        raise task_budget.TaskBudgetError('task_budget_unresolved_attempt')
    return state


def call_experiment(runtime, task_id: int, request, *, budget_id: str):
    """唯一实验适配入口强制预算身份，不产生新账或扩大授权。"""
    from dataclasses import replace
    from ..models import Task
    task=runtime.db.get(Task,task_id)
    root=Path(task.workspace_path) if task and task.workspace_path else None
    require_bound(root,budget_id)
    return runtime.call(task_id,replace(request,required_token_budget_id=budget_id))
