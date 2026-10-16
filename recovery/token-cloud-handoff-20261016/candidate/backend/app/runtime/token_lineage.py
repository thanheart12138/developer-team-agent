"""离线实验的连续账合同：历史未知单列，原子账消费不重复累计。"""
import hashlib
import json
from pathlib import Path
from . import task_budget


class LineageError(task_budget.TaskBudgetError):
    """来源或累计账不可信时停止，不可作为网络重试理由。"""


def _read(path):
    """只读普通文件，拒绝符号链接及来源替换。"""
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise LineageError('lineage_source_invalid')
    return path.read_bytes()


def _hash(raw):
    """对原字节求身份，不将重新序列化结果冒充来源。"""
    return hashlib.sha256(raw).hexdigest()


def _integer(value):
    """拒绝布尔、负值和浮点预算。"""
    return type(value) is int and value>=0


def _prefix(report):
    """从已有真实报告提取明确历史前缀，reasoning已含输出。"""
    value={'http':report['cumulative_http'],'known':report['cumulative_known_tokens'],
           'input':report['cumulative_known_input_tokens'],'output':report['cumulative_known_output_tokens'],
           'unknown':report['historical_unknown'],'holds':report['historical_nonactual_holds']}
    if not all(_integer(v) for v in value.values()) or value['input']+value['output']!=value['known'] or value['unknown']>value['http']:
        raise LineageError('lineage_prefix_invalid')
    return value


def _isolated_sources(root, sources):
    """来源须位于可写执行树外，且不得与执行账硬链接。"""
    root=Path(root).resolve()
    identities={}
    targets=[root/name for name in (task_budget.STATE_PATH, task_budget.MARKER_PATH,
                                  task_budget.LOCK_PATH, task_budget.REJECTIONS_PATH)]
    for source in sources:
        source=Path(source).absolute()
        _read(source)  # 任何写入前拒绝符号链接及父目录别名。
        if source.resolve().is_relative_to(root):
            raise LineageError('lineage_source_not_isolated')
        stat=source.stat()
        identity=[stat.st_dev,stat.st_ino]
        for target in targets:
            if target.exists() and source.samefile(target):
                raise LineageError('lineage_source_not_isolated')
        identities[str(source)]=identity
    return identities


def create_contract(path, *, execution_root, source_budget, source_report, research_limit):
    """只绑定已恢复的同一子账和历史报告，不初始化预算或授权真实运行。"""
    path=Path(path).absolute();root=task_budget._root(execution_root)
    identities=_isolated_sources(root,[source_budget,source_report])
    baseline_raw=_read(source_budget);report_raw=_read(source_report)
    baseline=json.loads(baseline_raw);report=json.loads(report_raw);prefix=_prefix(report)
    if report.get('child_budget')!=baseline or prefix['known']<baseline['known_tokens'] or prefix['http']<baseline['http_attempts']:
        raise LineageError('lineage_report_child_mismatch')
    current=task_budget.load(root)
    if current is None or current!=baseline:
        raise LineageError('lineage_baseline_mismatch')
    if any(a['actual_tokens'] is None for a in baseline['attempts']):
        raise LineageError('lineage_new_unknown')
    if not _integer(research_limit) or research_limit<prefix['known']+prefix['holds']:
        raise LineageError('lineage_research_limit_invalid')
    child_remaining=baseline['limits']['total_tokens']-baseline['known_tokens']
    research_remaining=research_limit-prefix['known']-prefix['holds']
    if child_remaining<0 or child_remaining>research_remaining:
        raise LineageError('lineage_child_exceeds_research_remainder')
    contract={'schema':'token-offline-lineage-v1','mode':'offline_only','live_authorized':False,
              'execution_root':str(root),'source_identities':identities,'baseline':baseline,'research_prefix':prefix,'research_limit':research_limit,
              'sources':{str(Path(source_budget).absolute()):_hash(baseline_raw),str(Path(source_report).absolute()):_hash(report_raw)}}
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise LineageError('lineage_contract_path_invalid')
    raw=json.dumps(contract,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
    # 排他创建，不覆盖先前合同；调用方须保存返回hash作为下一步绑定。
    with path.open('xb') as out:
        out.write(raw);out.flush()
        import os
        os.fsync(out.fileno())
    return {'path':str(path),'sha256':_hash(raw),'mode':'offline_only'}


def verify(path, expected_sha256):
    """重新核来源、旧attempt前缀和预算身份；允许已知新消费单调增加。"""
    raw=_read(path)
    if _hash(raw)!=expected_sha256:
        raise LineageError('lineage_contract_changed')
    contract=json.loads(raw)
    if contract.get('schema')!='token-offline-lineage-v1' or contract.get('mode')!='offline_only' or contract.get('live_authorized') is not False:
        raise LineageError('lineage_mode_invalid')
    identities=_isolated_sources(contract['execution_root'],contract['sources'])
    if identities!=contract.get('source_identities'):
        raise LineageError('lineage_source_identity_changed')
    for source,sha in contract['sources'].items():
        if _hash(_read(source))!=sha:
            raise LineageError('lineage_source_changed')
    baseline=contract['baseline'];current=task_budget.load(Path(contract['execution_root']))
    if (current is None or any(current[k]!=baseline[k] for k in ('schema','budget_id','limits'))
            or current['attempts'][:len(baseline['attempts'])]!=baseline['attempts']
            or current['http_attempts']<baseline['http_attempts']
            or current['known_tokens']<baseline['known_tokens']
            or current['revision']<baseline['revision']):
        raise LineageError('lineage_history_changed')
    new=current['attempts'][len(baseline['attempts']):]
    if any(a['actual_tokens'] is None for a in new):
        raise LineageError('lineage_new_unknown')
    delta_known=current['known_tokens']-baseline['known_tokens'];prefix=contract['research_prefix']
    total=prefix['known']+delta_known
    if total+prefix['holds']>contract['research_limit']:
        raise LineageError('lineage_research_limit_exceeded')
    return {'contract':contract,'budget_id':current['budget_id'],'new_http':len(new),'new_known':delta_known,
            'research_http':prefix['http']+len(new),'research_known':total,
            'historical_unknown':prefix['unknown'],'new_unknown':0,'historical_nonactual_holds':prefix['holds'],
            'research_remaining_after_known_and_holds':contract['research_limit']-total-prefix['holds'],
            'child_http_remaining':current['limits']['http_limit']-current['http_attempts'],
            'child_known_remaining':current['limits']['total_tokens']-current['known_tokens'],
            'live_authorized':False,'actual_total_exact':prefix['unknown']==0}
