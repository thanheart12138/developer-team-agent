"""按模块／功能设计、开发与测试，复用现有 Worker 阶段和调用预算。"""

import hashlib
import json
from pathlib import Path
import re
import shlex
import uuid

from ..models import Step, StepStatus, TaskStatus
from .contracts import ToolCall, ToolResult
from .prompt_registry import load_prompt
from .tools import TOOL_SCHEMAS, ToolRuntime
from .tracing import safe_record_trace

RUN_UNIT_TESTS_SCHEMA = {'type':'function', 'function':{'name':'run_unit_tests',
    'description':'运行程序固定的当前及已完成单元自测，返回真实输出和文件版本；失败后修复并重测，通过后才能提交。',
    'parameters':{'type':'object','properties':{'description':{'type':'string','maxLength':200}},'additionalProperties':False}}}

SUBMIT_UNIT_SCHEMA = {'type':'function', 'function':{'name':'submit_unit_for_test',
    'description':'当前版本自测通过后提交后续独立测试；未测、失败或版本过期拒绝提交，必须为本批最后动作。',
    'parameters':{'type':'object','properties':{'description':{'type':'string','maxLength':200}},'additionalProperties':False}}}

UNIT_DESIGN_MAX_CANDIDATES = 5
UNIT_READ_PREVIEW_LINES = 200


def parse_json(text: str) -> dict:
    # 接受模型 JSON 对象，拒绝非结构化计划或评审结果。
    value = json.loads(text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
    if not isinstance(value, dict):
        raise ValueError('unit_workflow_json_object_required')
    return value


def strings(value, field: str, empty: bool = False) -> list[str]:
    # 校验必要文本列表，防止空职责、空验收或缺失依赖清单。
    if not isinstance(value, list) or (not empty and not value) or any(not isinstance(s, str) or not s.strip() for s in value):
        raise ValueError(f'unit_plan_invalid_{field}')
    return value


def normalize_unit_kinds(plan: dict) -> list[dict]:
    # 多单元模块统一使用 feature；只修正调度标签，不改变职责、文件、依赖或验收。
    units = plan.get('units')
    if not isinstance(units, list):
        return []
    grouped: dict[str, list[dict]] = {}
    for unit in units:
        if isinstance(unit, dict) and isinstance(unit.get('module_id'), str):
            grouped.setdefault(unit['module_id'], []).append(unit)
    normalizations = []
    for module_id, entries in grouped.items():
        if len(entries) <= 1:
            continue
        changed = [unit['id'] for unit in entries if unit.get('kind') == 'module']
        if not changed:
            continue
        for unit in entries:
            if unit.get('kind') == 'module':
                unit['kind'] = 'feature'
        normalizations.append({'module_id':module_id, 'unit_ids':changed,
                               'change':'module_to_feature_for_multi_unit_module'})
    if normalizations:
        plan.setdefault('normalizations', []).extend(normalizations)
    return normalizations


def ordered_units(plan: dict, root: Path) -> list[dict]:
    # 校验模块与功能、文件归属和依赖图，返回确定性的拓扑顺序。
    normalize_unit_kinds(plan)
    modules = plan.get('modules')
    units = plan.get('units')
    if not isinstance(modules, list) or not modules or not isinstance(units, list) or not units:
        raise ValueError('unit_plan_modules_and_units_required')
    identifiers = set()
    for module in modules:
        if not isinstance(module, dict) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', str(module.get('id', ''))):
            raise ValueError('unit_plan_invalid_module')
        if module['id'] in identifiers or not isinstance(module.get('responsibility'), str) or not module['responsibility'].strip():
            raise ValueError('unit_plan_invalid_module')
        strings(module.get('public_interfaces'), 'public_interfaces')
        identifiers.add(module['id'])
    by_id = {}
    owners = set()
    kinds = {}
    product = (root / 'product').resolve()
    for unit in units:
        if not isinstance(unit, dict) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', str(unit.get('id', ''))):
            raise ValueError('unit_plan_invalid_unit')
        if unit['id'] in by_id or unit.get('module_id') not in identifiers or unit.get('kind') not in {'module', 'feature'}:
            raise ValueError('unit_plan_invalid_unit')
        if unit['id'] == 'shared-contract':
            raise ValueError('unit_plan_reserved_unit_id')
        for field in ('name', 'scope'):
            if not isinstance(unit.get(field), str) or not unit[field].strip():
                raise ValueError(f'unit_plan_invalid_{field}')
        strings(unit.get('depends_on'), 'depends_on', empty=True)
        strings(unit.get('acceptance_criteria'), 'acceptance_criteria')
        kinds.setdefault(unit['module_id'], []).append(unit['kind'])
        for field in ('implementation_files', 'test_files'):
            paths = strings(unit.get(field), field)
            for value in paths:
                path = (root / value).resolve()
                if Path(value).is_absolute() or product not in path.parents or str(path.relative_to(root.resolve())) != value:
                    raise ValueError('unit_plan_path_outside_product')
                if path in owners:
                    raise ValueError('unit_plan_duplicate_file_owner')
                if field == 'test_files' and not path.name.endswith(('.test.js', '.test.cjs', '.test.mjs')):
                    raise ValueError('unit_plan_invalid_test_file')
                owners.add(path)
        by_id[unit['id']] = unit
    if set(kinds) != identifiers or any('module' in entries and len(entries) != 1 for entries in kinds.values()):
        raise ValueError('unit_plan_module_feature_overlap')
    public_operations = {module['id']:{match for interface in module['public_interfaces']
        for match in re.findall(r'\b([A-Za-z_$][\w$]*)\s*\(', interface)} for module in modules}
    operation_owners: dict[tuple[str, str], list[str]] = {}
    for unit in units:
        operations = {operation for operation in public_operations[unit['module_id']]
                      if any(re.search(rf'\b{re.escape(operation)}(?:\s*\([^)]*\))?\s*返回', criterion)
                             for criterion in unit['acceptance_criteria'])}
        for operation in operations:
            operation_owners.setdefault((unit['module_id'], operation), []).append(unit['id'])
    if any(len(set(owners)) > 1 for owners in operation_owners.values()):
        raise ValueError('unit_plan_duplicate_operation_owner')
    if not {(product / name) for name in ('index.html', 'verify_product.py', 'implementation.md')} <= owners:
        raise ValueError('unit_plan_product_entries_required')
    ordered = []
    remaining = list(units)
    completed = set()
    while remaining:
        ready = next((u for u in remaining if set(u['depends_on']) <= completed), None)
        if ready is None:
            raise ValueError('unit_plan_unknown_dependency_or_cycle')
        ordered.append(ready)
        completed.add(ready['id'])
        remaining.remove(ready)
    return ordered


def plan_validation_feedback(error: Exception, plan: dict | None) -> dict:
    # 返回可直接修正的短反馈，避免把整份无效计划再次塞回模型上下文。
    code = str(error)
    hints = {
        'unit_plan_modules_and_units_required':'modules 和 units 必须都是非空数组。',
        'unit_plan_invalid_module':'检查模块 id 唯一且为英文小写标识，并补齐 responsibility 与 public_interfaces。',
        'unit_plan_invalid_unit':'检查单元 id、module_id 和 kind；kind 只能是 module 或 feature。',
        'unit_plan_reserved_unit_id':'shared-contract 是保留 id，请更改单元 id。',
        'unit_plan_duplicate_file_owner':'同一文件只能属于一个单元，请保留一个所有者。',
        'unit_plan_path_outside_product':'所有实现与测试路径必须是 product/ 下的规范相对路径。',
        'unit_plan_invalid_test_file':'测试文件必须以 .test.js、.test.cjs 或 .test.mjs 结尾。',
        'unit_plan_product_entries_required':'为明确的装配单元分配 index.html、verify_product.py 和 implementation.md。',
        'unit_plan_unknown_dependency_or_cycle':'depends_on 只能引用已有单元，并且依赖必须无环。',
        'unit_plan_duplicate_operation_owner':'同一模块内显式出现的同一公共操作只能由一个单元负责；合并重复行为，或让附加单元只提供名称不同的内部能力。',
    }
    units = plan.get('units', []) if isinstance(plan, dict) else []
    summary = [{'id':unit.get('id'), 'module_id':unit.get('module_id'), 'kind':unit.get('kind')}
               for unit in units if isinstance(unit, dict)]
    details: dict[str, object] = {}
    if code == 'unit_plan_duplicate_file_owner':
        owners: dict[str, list[str]] = {}
        for unit in units:
            if not isinstance(unit, dict):
                continue
            for path in unit.get('implementation_files', []) + unit.get('test_files', []):
                if isinstance(path, str):
                    owners.setdefault(path, []).append(str(unit.get('id')))
        details['conflicts'] = {path:ids for path, ids in owners.items() if len(ids) > 1}
    elif code == 'unit_plan_product_entries_required':
        owned = {path for unit in units if isinstance(unit, dict)
                 for field in ('implementation_files', 'test_files')
                 for path in unit.get(field, []) if isinstance(path, str)}
        details['missing_entries'] = [path for path in
            ('product/index.html', 'product/verify_product.py', 'product/implementation.md') if path not in owned]
    elif code == 'unit_plan_unknown_dependency_or_cycle':
        identifiers = {unit.get('id') for unit in units if isinstance(unit, dict)}
        details['unknown_dependencies'] = {str(unit.get('id')):[dependency for dependency in unit.get('depends_on', [])
            if dependency not in identifiers] for unit in units if isinstance(unit, dict)
            and any(dependency not in identifiers for dependency in unit.get('depends_on', []))}
    elif code == 'unit_plan_duplicate_operation_owner':
        owners: dict[str, list[str]] = {}
        module_operations = {module.get('id'):{match for interface in module.get('public_interfaces', [])
            if isinstance(interface, str) for match in re.findall(r'\b([A-Za-z_$][\w$]*)\s*\(', interface)}
            for module in plan.get('modules', []) if isinstance(module, dict)}
        for unit in units:
            if not isinstance(unit, dict):
                continue
            for criterion in unit.get('acceptance_criteria', []):
                if isinstance(criterion, str):
                    for operation in module_operations.get(unit.get('module_id'), set()):
                        if re.search(rf'\b{re.escape(operation)}(?:\s*\([^)]*\))?\s*返回', criterion):
                            owners.setdefault(f'{unit.get("module_id")}:{operation}', []).append(str(unit.get('id')))
        details['conflicts'] = {operation:ids for operation, ids in owners.items() if len(set(ids)) > 1}
    return {'error':code, 'correction':hints.get(code, '只修正错误字段，保留其他已经正确的模块、单元、文件和依赖。'),
            'unit_summary':summary, **details}


def load_plan(root: Path) -> dict:
    # 读取当前计划，并拒绝已经偏离正式需求或架构的旧计划。
    from . import worker as w
    plan = json.loads((root / 'docs/development-plan.json').read_text(encoding='utf-8'))
    if type(plan.get('version')) is not int or plan['version'] <= 0:
        raise ValueError('unit_plan_invalid_version')
    ordered_units(plan, root)
    for field, name in [('product_hash', 'product.md'), ('architecture_hash', 'architecture.md')]:
        if plan.get(field) != w.content_hash((root / 'docs' / name).read_text(encoding='utf-8')):
            raise ValueError('unit_plan_upstream_changed_requires_design')
    return plan


def ensure_plan(db, task, run, tools) -> None:
    # 在架构结束前生成并校验开发单元清单，保留每个正式版本。
    from . import worker as w
    root = w.workspace_for(task)
    product = (root / 'docs/product.md').read_text(encoding='utf-8')
    architecture = (root / 'docs/architecture.md').read_text(encoding='utf-8')
    hashes = {'product_hash':w.content_hash(product), 'architecture_hash':w.content_hash(architecture)}
    current = root / 'docs/development-plan.json'
    feedback = None
    if current.is_file():
        old = json.loads(current.read_text(encoding='utf-8'))
        if all(old.get(key) == value for key, value in hashes.items()):
            try:
                ordered_units(old, root)
                return
            except (ValueError, TypeError, KeyError) as exc:
                feedback = plan_validation_feedback(exc, old)
    versions = [int(p.stem.rsplit('-v', 1)[1]) for p in (root / 'docs').glob('development-plan-v*.json')]
    version = max(versions, default=0) + 1
    for attempt in range(1, w.MAX_NO_CHANGE_CORRECTIONS + 2):
        plan = None
        response = w.model_tool_loop(db, task, run, load_prompt('unit-planner'),
            architecture, {'approved_product':product, 'project_constraints':w.FIXED_PRODUCT_CONSTRAINTS,
                'validation_feedback':feedback}, tools, tool_schemas=[], history_key=f'architecture_unit_plan_v{version}:{attempt}')
        try:
            plan = {**parse_json(response), **hashes, 'version':version}
            ordered_units(plan, root)
            break
        except (ValueError, TypeError, KeyError) as exc:
            # 无效计划返回字段级短反馈，不重复携带整份旧响应。
            feedback = plan_validation_feedback(exc, plan)
            safe_record_trace(db, task, run, 'validation', 'failed', '开发计划校验失败', str(exc), feedback)
            db.commit()
    else:
        raise RuntimeError('unit_plan_validation_failed')
    w.write_json_atomic(root / f'docs/development-plan-v{version}.json', plan)
    w.write_json_atomic(current, plan)
    safe_record_trace(db, task, run, 'transition_decision', 'succeeded', '模块／功能开发计划',
                      f'{len(plan["units"])} 个串行单元', {'plan':plan})
    db.commit()


class UnitTools(ToolRuntime):
    def __init__(self, workspace: Path, writable: list[str], readable: list[str], submission_files: list[str] | None = None,
                 self_test_files: list[str] | None = None, test_files: list[str] | None = None):
        # 限制单元文件所有权，防止开发模型修改依赖或自行跳过程序测试。
        super().__init__(workspace)
        self.writable = {self._safe_path(path) for path in writable}
        self.readable = self.writable | {self._safe_path(path) for path in readable}
        self.submission_files = submission_files
        self.submitted_hashes = None
        self.self_test_files = self_test_files or submission_files or []
        self.test_files = test_files or []
        self.self_test = None

    def self_test_versions(self) -> dict:
        # 测试与版本检查只访问程序配置的单元及依赖文件。
        for path in self.self_test_files:
            if self._safe_path(path) not in self.readable:
                raise ValueError('unit_self_test_outside_scope')
        return file_hashes(self.workspace, self.self_test_files)

    def self_test_command(self) -> str:
        # 命令和测试清单由程序固定，模型无法传入任意命令或缩减范围。
        if not self.submission_files or not self.test_files:
            raise ValueError('unit_self_test_not_allowed')
        for path in self.test_files:
            if path not in self.self_test_files or not path.endswith(('.test.js', '.test.cjs', '.test.mjs')):
                raise ValueError('unit_self_test_invalid_test_file')
            self._safe_path(path)
        return 'node --test ' + ' '.join(shlex.quote(str(Path(path).relative_to('product'))) for path in self.test_files)

    def restore_self_test(self, output: dict) -> bool:
        # 只接受固定范围、固定命令及当前版本的真实通过证据。
        if not self.submission_files or not self.test_files or not isinstance(output, dict):
            return False
        if (output.get('command') == self.self_test_command()
                and output.get('file_hashes_after') == self.self_test_versions()
                and all(value is not None for value in output['file_hashes_after'].values())
                and output.get('passed') is True
                and test_passed(ToolResult(**output['result']), output.get('file_hashes_before'), output['file_hashes_after'])):
            self.self_test = output
            return True
        return False

    def _run_unit_tests(self) -> dict:
        # 开发主动请求受控自测；保留失败输出，不把工具执行成功等同测试通过。
        command = self.self_test_command()
        before = self.self_test_versions()
        missing = [path for path, value in before.items() if value is None]
        result = (ToolResult(str(uuid.uuid4()), 'exec', 'failed', error='unit_files_missing:' + ','.join(missing)) if missing else
                  ToolRuntime(self.workspace).execute(ToolCall(str(uuid.uuid4()), 'exec', {'action':'run', 'command':command})))
        after = self.self_test_versions()
        self.self_test = {'command':command, 'result':result.__dict__, 'file_hashes_before':before,
                          'file_hashes_after':after, 'passed':test_passed(result, before, after)}
        return self.self_test

    def restore_submission(self, output: dict) -> bool:
        # 仅恢复该单元全部文件版本一致的提交，避免中断后重复执行已完成交接。
        hashes = output.get('file_hashes')
        if (self.submission_files and hashes == self.submission_versions() and all(value is not None for value in hashes.values())
                and output.get('self_test') and self.restore_self_test(output['self_test'])):
            self.submitted_hashes = hashes
            return True
        return False

    def submission_versions(self) -> dict:
        # 每次提交／恢复重新验证真实路径所有权，再绑定交付文件字节版本。
        for path in self.submission_files or []:
            if self._safe_path(path) not in self.writable:
                raise ValueError('unit_submission_outside_scope')
        return file_hashes(self.workspace, self.submission_files or [])

    def _submit_unit_for_test(self) -> dict:
        # 交接必须有当前版本的通过自测，后续独立验证仍不能省略。
        if not self.submission_files:
            raise ValueError('unit_submission_not_allowed')
        hashes = self.submission_versions()
        missing = [path for path, value in hashes.items() if value is None]
        if missing:
            raise ValueError('unit_files_missing:' + ','.join(missing))
        if not self.self_test:
            raise ValueError('unit_self_test_required')
        if not self.self_test['passed']:
            raise ValueError('unit_self_test_failed')
        if not self.restore_self_test(self.self_test):
            raise ValueError('unit_self_test_stale')
        self.submitted_hashes = hashes
        return {'file_hashes':hashes, 'self_test':self.self_test, 'test_state':'pending'}

    def execute(self, call: ToolCall) -> ToolResult:
        # 开发只开放受限文件、自测和交接，不开放任意命令执行。
        if call.tool_name in {'submit_unit_for_test', 'run_unit_tests'}:
            return super().execute(call)
        if call.tool_name not in {'read', 'write', 'replace', 'get_file_change_history', 'get_model_call_summaries', 'get_tool_execution_detail'}:
            return ToolResult(call.call_id, call.tool_name, 'failed', error='unit_tool_not_allowed')
        return super().execute(call)

    def _write(self, path: str, content: str, overwrite: bool) -> dict:
        # 写入前按实际解析路径检查当前单元所有权。
        from .repair_runtime import load as load_repair
        repair = load_repair(self.workspace)
        if repair and repair["state"] != "executing":
            raise ValueError('repair_submission_frozen')
        if self._safe_path(path) not in self.writable:
            raise ValueError('unit_write_outside_owned_files')
        return super()._write(path, content, overwrite)

    def _replace(self, path: str, old: str, new: str) -> dict:
        # 精确替换与整文件写入使用相同的单元所有权边界。
        from .repair_runtime import load as load_repair
        repair = load_repair(self.workspace)
        if repair and repair["state"] != "executing":
            raise ValueError('repair_submission_frozen')
        if self._safe_path(path) not in self.writable:
            raise ValueError('unit_write_outside_owned_files')
        return super()._replace(path, old, new)

    def _read(self, path: str, start_line: int | None = None, end_line: int | None = None) -> dict:
        # 读取仅限当前单元、依赖文件和明确提供的设计资料；大文件默认只返回预览。
        if self._safe_path(path) not in self.readable:
            raise ValueError('unit_read_outside_scope')
        if start_line is None and end_line is None:
            total_lines = len(self._safe_path(path).read_text(encoding='utf-8').splitlines())
            if total_lines > UNIT_READ_PREVIEW_LINES:
                output = super()._read(path, 1, UNIT_READ_PREVIEW_LINES)
                output['truncated'] = True
                output['hint'] = 'large_file_preview_use_start_line_and_end_line'
                return output
        return super()._read(path, start_line, end_line)


def dependency_units(unit: dict, ordered: list[dict]) -> list[dict]:
    # 收集当前单元的完整前置依赖，供读取范围和测试版本绑定使用。
    needed = set(unit['depends_on'])
    for candidate in reversed(ordered):
        if candidate['id'] in needed:
            needed.update(candidate['depends_on'])
    return [candidate for candidate in ordered if candidate['id'] in needed]


def design_path(plan: dict, identifier: str) -> str:
    # 由程序生成设计路径，不允许模型指定任意目录。
    return f'docs/dev-design/v{plan["version"]}/{identifier}.md'


def normalize_internal_clarification(review: dict, context: dict) -> dict:
    # 上游契约与当前单元描述的冲突属于内部设计修正，不能要求用户裁决实现细节。
    question = review.get('question')
    if (review.get('action') == 'clarify' and context.get('shared_contract')
            and isinstance(question, str) and '共享契约' in question
            and any(marker in question for marker in ('为准', '修订共享契约', '改为'))):
        return {'action':'revise', 'issues':[
            '按已批准需求、共享契约、已正式化依赖设计、当前单元描述的优先级修正当前单元；不得要求用户裁决内部接口冲突。'],
            'question':''}
    return review


def reviewed_design(db, task, run, target: str, label: str, input_text: str, context: dict) -> bool:
    # 有界生成与独立评审，通过才正式化；设计缺口交还用户。
    from . import worker as w
    root = w.workspace_for(task)
    path = root / target
    if path.is_file():
        return True
    feedback = []
    answer_key = w.content_hash(json.dumps(context.get('user_answers', []), ensure_ascii=False))[:12]
    for attempt in range(1, UNIT_DESIGN_MAX_CANDIDATES + 1):
        draft = target.removesuffix('.md') + f'-answers-{answer_key}-draft-{attempt}.md'
        review_path = target.removesuffix('.md') + f'-answers-{answer_key}-review-{attempt}.json'
        scoped = UnitTools(root, [draft], [])
        if not (root / draft).is_file():
            w.model_tool_loop(db, task, run,
                load_prompt('design-author', {'label':label, 'draft':draft}),
                input_text, {**context, 'review_feedback':feedback}, scoped,
                tool_schemas=[schema for schema in TOOL_SCHEMAS if schema['function']['name'] == 'write'],
                stop_when=lambda: (root / draft).is_file(), history_key=f'{target}:draft:{attempt}')
        text = (root / draft).read_text(encoding='utf-8')
        if (root / review_path).is_file():
            review = json.loads((root / review_path).read_text(encoding='utf-8'))
        else:
            protocol_error = None
            for protocol_attempt in range(2):
                response = w.model_tool_loop(db, task, run,
                    load_prompt('design-reviewer'),
                    text, {**context, 'design_source':input_text, 'protocol_error':protocol_error}, scoped,
                    tool_schemas=[], history_key=f'{target}:review:{attempt}:protocol:{protocol_attempt + 1}')
                try:
                    review = parse_json(response)
                    strings(review.get('issues'), 'review_issues', empty=True)
                    if review.get('action') not in {'ready', 'revise', 'clarify'}:
                        raise ValueError('unit_design_invalid_review')
                    break
                except (ValueError, TypeError, KeyError) as exc:
                    protocol_error = {'error':str(exc), 'instruction':load_prompt('unit-workflow-feedback-1').text}
            else:
                raise RuntimeError('unit_design_review_protocol_failed')
            w.write_json_atomic(root / review_path, review)
        review = normalize_internal_clarification(review, context)
        if review['action'] == 'ready':
            if review['issues']:
                raise ValueError('unit_design_ready_with_issues')
            w.atomic_copy(root / draft, path)
            safe_record_trace(db, task, run, 'artifact', 'succeeded', f'{label}正式化', target,
                              {'path':target, 'sha256':w.content_hash(text), 'review':review})
            db.commit()
            return True
        if review['action'] == 'clarify':
            question = review.get('question')
            if not isinstance(question, str) or not question.strip():
                raise ValueError('unit_design_question_missing')
            run.status = StepStatus.waiting_user
            task.status = TaskStatus.waiting_user
            w.add_message(db, task, 'assistant', question)
            db.commit()
            return False
        feedback = review['issues']
    raise RuntimeError('unit_design_review_failed')


def handle_design(db, task, run, tools) -> None:
    # 先共享契约，再逐单元生成设计，根级文件仅保存版本化索引。
    from . import worker as w
    root = w.workspace_for(task)
    plan = load_plan(root)
    gap_path = root / 'evidence/unit-design-gap.json'
    gap = json.loads(gap_path.read_text(encoding='utf-8')) if gap_path.is_file() else {}
    revision_path = root / 'evidence/unit-design-revision.json'
    revision = json.loads(revision_path.read_text(encoding='utf-8')) if revision_path.is_file() else {}
    confirmed_defect = w.active_bug_triage(task).get('classification') == 'dev_design_defect'
    must_revise = confirmed_defect and revision.get('step_run_id') != run.id
    if (gap.get('active') and gap.get('design_version') != plan['version']) or must_revise:
        # 开发发现设计缺口后，保存旧设计并开启新版本，不能在开发中猜补规则。
        plan = {**plan, 'version':plan['version'] + 1}
        w.write_json_atomic(root / f'docs/development-plan-v{plan["version"]}.json', plan)
        w.write_json_atomic(root / 'docs/development-plan.json', plan)
        gap['design_version'] = plan['version']
        w.write_json_atomic(gap_path, gap)
        w.write_json_atomic(revision_path, {'step_run_id':run.id, 'plan_version':plan['version']})
    ordered = ordered_units(plan, root)
    product = (root / 'docs/product.md').read_text(encoding='utf-8')
    shared_path = design_path(plan, 'shared-contract')
    previous_shared = root / f'docs/dev-design/v{plan["version"] - 1}/shared-contract.md'
    answers = [m.content for m in db.scalars(w.select(w.Message).where(w.Message.task_id == task.id, w.Message.role == 'user').order_by(w.Message.id))]
    if not reviewed_design(db, task, run, shared_path, '共享交互契约',
        (root / 'docs/architecture.md').read_text(encoding='utf-8'),
        {'approved_product':product, 'modules':plan['modules'], 'units':ordered, 'user_answers':answers,
         'project_constraints':w.FIXED_PRODUCT_CONSTRAINTS, 'development_design_gap':gap,
         'previous_design':previous_shared.read_text(encoding='utf-8') if previous_shared.is_file() else ''}):
        return
    shared = (root / shared_path).read_text(encoding='utf-8')
    for unit in ordered:
        dependencies = [module for module in plan['modules'] if module['id'] in {u['module_id'] for u in dependency_units(unit, ordered)}]
        previous_unit = root / f'docs/dev-design/v{plan["version"] - 1}/{unit["id"]}.md'
        dependency_designs = {u['id']:(root / design_path(plan, u['id'])).read_text(encoding='utf-8')
                              for u in ordered if u['id'] in unit['depends_on']}
        if not reviewed_design(db, task, run, design_path(plan, unit['id']), f'{unit["name"]} Dev Design',
            json.dumps(unit, ensure_ascii=False), {'approved_product':product, 'shared_contract':shared,
                'dependency_interfaces':dependencies, 'unit':unit, 'user_answers':answers,
                'dependency_designs':dependency_designs,
                'project_constraints':w.FIXED_PRODUCT_CONSTRAINTS, 'development_design_gap':gap,
                'previous_design':previous_unit.read_text(encoding='utf-8') if previous_unit.is_file() else ''}):
            return
    index = '# Dev Design 索引\n\n详细设计按模块／功能保存，禁止以索引代替详细设计。\n\n'
    for name, path in [('开发计划', 'docs/development-plan.json'), ('共享契约', shared_path)] + [(u['name'], design_path(plan, u['id'])) for u in ordered]:
        index += f'- {name}：{path}；SHA-256：{hashlib.sha256((root / path).read_bytes()).hexdigest()}\n'
    version = plan['version']
    (root / f'docs/dev-design-v{version}.md').write_text(index, encoding='utf-8')
    (root / 'docs/dev-design.md').write_text(index, encoding='utf-8')
    if gap.get('active'):
        w.write_json_atomic(gap_path, {**gap, 'active':False})
    run.output_path = 'docs/dev-design.md'
    w.finish_step(db, task, run, Step.develop)


def file_hashes(root: Path, paths: list[str]) -> dict:
    # 绑定实际字节版本，缺失文件明确为 None，不能借旧测试通过恢复。
    return {value:hashlib.sha256((root / value).read_bytes()).hexdigest() if (root / value).is_file() else None for value in paths}


def test_passed(result, before: dict, after: dict) -> bool:
    # 退出零且至少一条真实测试、无跳过且执行期间版本稳定才算通过。
    output = result.output
    stdout = output.get('stdout', '')
    counts = re.search(r'(?:ℹ|#) tests (\d+)', stdout)
    skipped = re.search(r'(?:ℹ|#) (?:skipped|todo) [1-9]\d*', stdout)
    return bool(result.status == 'succeeded' and output.get('exit_code') == 0
                and not output.get('timed_out') and counts and int(counts[1]) > 0
                and not skipped and '[SKIP]' not in stdout and before == after)


def integration_repair_decision(db, task, run, tools, plan: dict, global_failure: dict) -> dict:
    # 只读诊断全局失败的责任归属，以版本绑定缓存防止恢复时重复定位。
    from . import worker as w
    root = w.workspace_for(task)
    paths = [str(path.relative_to(root)) for path in (root / 'product').rglob('*') if path.is_file()
             and path.suffix in {'.html', '.css', '.js', '.cjs', '.mjs', '.py', '.md'}]
    design_paths = [design_path(plan, 'shared-contract')] + [design_path(plan, u['id']) for u in plan['units']]
    basis = {'failure':global_failure, 'plan':plan, 'versions':file_hashes(root, paths + design_paths + ['docs/product.md'])}
    target = root / f'evidence/integration-repair-run-{run.id}.json'
    if target.is_file():
        saved = json.loads(target.read_text(encoding='utf-8'))
        if saved.get('basis') == basis:
            return saved['decision']
    response = w.model_tool_loop(db, task, run, load_prompt('integration-repair-diagnoser'),
        json.dumps(global_failure, ensure_ascii=False),
        {'approved_product':(root / 'docs/product.md').read_text(encoding='utf-8'),
         'ownership':plan['units'], 'shared_contract':(root / design_path(plan, 'shared-contract')).read_text(encoding='utf-8'),
         'unit_designs':{u['id']:(root / design_path(plan, u['id'])).read_text(encoding='utf-8') for u in plan['units']},
         'current_files':{path:(root / path).read_text(encoding='utf-8', errors='replace') for path in paths}},
        tools, tool_schemas=[], history_key=f'integration_repair:{w.content_hash(json.dumps(basis, sort_keys=True))}')
    try:
        decision = parse_json(response)
        category = decision.get('category')
        identifiers = decision.get('unit_ids')
        confidence = decision.get('confidence')
        if (category not in {'implementation_error', 'test_script_error', 'cross_unit_error', 'design_conflict', 'unclear'}
                or not isinstance(identifiers, list) or any(not isinstance(value, str) for value in identifiers)
                or len(set(identifiers)) != len(identifiers) or not set(identifiers) <= {u['id'] for u in plan['units']}
                or type(confidence) not in {int, float} or not 0 <= confidence <= 1
                or not isinstance(decision.get('reason'), str) or not decision['reason'].strip()):
            raise ValueError('invalid_integration_diagnosis')
        if category in {'implementation_error', 'test_script_error', 'cross_unit_error'}:
            if (confidence < 0.8 or not identifiers or (category != 'cross_unit_error' and len(identifiers) != 1)
                    or (category == 'cross_unit_error' and len(identifiers) < 2)
                    or not isinstance(decision.get('repair_target'), str) or not decision['repair_target'].strip()):
                raise ValueError('uncertain_integration_diagnosis')
    except (ValueError, TypeError, KeyError) as exc:
        # 非法或低置信定位不授权任何单元写入，保留原响应与明确澄清原因。
        decision = {'category':'unclear', 'unit_ids':[], 'confidence':0,
                    'reason':f'{exc}，集成失败责任未明确，请确认责任单元或契约。', 'repair_target':''}
    w.write_json_atomic(target, {'basis':basis, 'decision':decision})
    safe_record_trace(db, task, run, 'transition_decision', 'succeeded', '集成失败责任诊断', decision['reason'],
                      {'basis':basis, 'decision':decision})
    db.commit()
    return decision


def handle_develop(db, task, run, tools) -> None:
    # 按依赖完成每个单元的真实测试修复闭环，再交给全量集成阶段。
    from . import worker as w
    root = w.workspace_for(task)
    plan = load_plan(root)
    ordered = ordered_units(plan, root)
    shared_path = design_path(plan, 'shared-contract')
    shared = (root / shared_path).read_text(encoding='utf-8')
    plan_hash = w.content_hash(json.dumps(plan, sort_keys=True, ensure_ascii=False))
    design_hashes = {u['id']:w.content_hash((root / design_path(plan, u['id'])).read_text(encoding='utf-8')) for u in ordered}
    evidence = root / 'evidence/development-progress.json'
    signature = {'plan_hash':plan_hash, 'shared_hash':w.content_hash(shared), 'design_hashes':design_hashes}
    progress = json.loads(evidence.read_text(encoding='utf-8')) if evidence.is_file() else {}
    if any(progress.get(key) != value for key, value in signature.items()):
        progress = {**signature, 'units':{}}
    completed = []
    prior_failed = db.scalar(w.select(w.StepRun).where(w.StepRun.task_id == task.id, w.StepRun.id < run.id,
        w.StepRun.step.in_([Step.test, Step.start_product, Step.verify_product]),
        w.StepRun.status == StepStatus.failed).order_by(w.StepRun.id.desc()).limit(1)) if task.repair_round else None
    report = root / ('evidence/verification-report.md' if prior_failed and prior_failed.step == Step.verify_product else 'evidence/test-report.md')
    global_feedback = {'step':prior_failed.step.value, 'failed_run_id':prior_failed.id, 'error':prior_failed.error,
                       'report':report.read_text(encoding='utf-8') if prior_failed.step in {Step.test, Step.verify_product} and report.is_file() else ''} if prior_failed else None
    repair_ids = set()
    if global_feedback:
        try:
            decision = integration_repair_decision(db, task, run, tools, plan, global_feedback)
        except RuntimeError as exc:
            # 无工具诊断违反输出权限时只进入澄清；真实传输／预算失败仍正常终止。
            if str(exc) != 'model_tool_call_not_allowed':
                raise
            decision = {'category':'unclear', 'unit_ids':[], 'confidence':0,
                        'reason':'责任诊断提出了非法工具调用，请确认集成失败责任。', 'repair_target':''}
        if decision['category'] in {'design_conflict', 'unclear'}:
            # 不确定责任或确有契约冲突时交用户澄清，不放开模块文件权限。
            question = decision['reason']
            run.status, task.status, task.cur_step = StepStatus.waiting_user, TaskStatus.waiting_user, Step.dev_design
            w.write_json_atomic(root / 'evidence/unit-design-gap.json', {'active':True,
                'unit_id':decision['unit_ids'][0] if decision['unit_ids'] else 'shared-contract',
                'question':question, 'plan_hash':plan_hash, 'integration_diagnosis':decision})
            w.add_message(db, task, 'assistant', question)
            db.commit()
            return
        repair_ids = set(decision['unit_ids'])
        global_feedback = {**global_feedback, 'diagnosis':decision,
                           'file_hashes':file_hashes(root, [p for u in ordered for p in u['implementation_files'] + u['test_files']])}
    for unit in ordered:
        dependencies = dependency_units(unit, ordered)
        scope = list(dict.fromkeys([p for u in dependencies + [unit] for p in u['implementation_files'] + u['test_files']]))
        context_scope = list(dict.fromkeys(unit['implementation_files'] + unit['test_files']
            + [p for u in dependencies if u['id'] in unit['depends_on'] for p in u['implementation_files']]))
        hashes = file_hashes(root, scope)
        state = progress['units'].get(unit['id'], {})
        unit_failure = global_feedback if unit['id'] in repair_ids else None
        if state.get('status') == 'passed' and state.get('file_hashes') == hashes and not unit_failure:
            completed.append(unit)
            continue
        design = (root / design_path(plan, unit['id'])).read_text(encoding='utf-8')
        owned = unit['implementation_files'] + unit['test_files']
        tested_scope = [p for u in completed + [unit] for p in u['implementation_files'] + u['test_files']]
        scoped = UnitTools(root, owned, tested_scope + scope + [shared_path, design_path(plan, unit['id'])], submission_files=owned,
                           self_test_files=tested_scope, test_files=[p for u in completed + [unit] for p in u['test_files']])
        test_files = [p for u in completed + [unit] for p in u['test_files']]
        command = 'node --test ' + ' '.join(shlex.quote(str(Path(p).relative_to('product'))) for p in test_files)
        feedback = None
        if state.get('status') == 'failed' and state.get('report'):
            # 即使恢复时文件不齐，也要把上次失败结果交给开发，不能退回空反馈。
            saved_report = tools._safe_path(state['report'])
            if (root / 'evidence/units').resolve() not in saved_report.parents:
                raise ValueError('unit_test_report_outside_scope')
            feedback = json.loads(saved_report.read_text(encoding='utf-8'))
        start_attempt = state.get('attempt', 1) if state.get('status') in {'developing', 'failed', 'submitted'} else 1
        if state.get('status') == 'failed':
            start_attempt += 1
        for attempt in range(start_attempt, w.MAX_NO_CHANGE_CORRECTIONS + 2):
            # 恢复已有中断单元先重测，不把旧成功或模型声明当证据。
            resume_test = state.get('status') == 'submitted' and attempt == start_attempt and scoped.restore_submission(
                {'file_hashes':state.get('submitted_file_hashes'), 'self_test':state.get('self_test')})
            if not resume_test:
                scoped.submitted_hashes = None
                progress['units'][unit['id']] = {'status':'developing', 'attempt':attempt}
                w.write_json_atomic(evidence, progress)
                response = w.model_tool_loop(db, task, run, load_prompt('unit-developer'),
                    design, {'unit':unit, 'shared_contract':shared, 'owned_files':unit['implementation_files'] + unit['test_files'],
                        'unit_file_scope':context_scope, 'development_attempt':attempt, 'require_unit_submission':True, 'unit_test_feedback':feedback, 'global_failure':unit_failure,
                        'completed_unit_tests':[{'unit_id':u['id'], 'status':progress['units'][u['id']]['status'],
                            'matches_current_files':progress['units'][u['id']]['file_hashes'] == file_hashes(root, [p for dependency in dependency_units(u, ordered) + [u] for p in dependency['implementation_files'] + dependency['test_files']])}
                            for u in completed],
                        'dependency_interfaces':[m for m in plan['modules'] if m['id'] in {u['module_id'] for u in dependencies}]},
                    scoped, tool_schemas=[s for s in TOOL_SCHEMAS if s['function']['name'] in {'read', 'write', 'replace'}] + [RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA],
                    stop_when=lambda: scoped.submitted_hashes is not None,
                    history_key=f'unit:{plan_hash}:{unit["id"]}:{attempt}')
                if response.strip().startswith('BLOCKED:'):
                    # 设计缺口交还用户，不能靠修改依赖或降低测试预期绕过。
                    run.status = StepStatus.waiting_user
                    task.status = TaskStatus.waiting_user
                    question = response.strip().removeprefix('BLOCKED:').strip()
                    if not question:
                        raise ValueError('unit_development_question_missing')
                    task.cur_step = Step.dev_design
                    w.write_json_atomic(root / 'evidence/unit-design-gap.json',
                        {'active':True, 'unit_id':unit['id'], 'question':question, 'plan_hash':plan_hash})
                    safe_record_trace(db, task, run, 'transition_decision', 'waiting', '开发返回设计', question,
                                      {'unit_id':unit['id'], 'target_step':'dev_design'})
                    w.add_message(db, task, 'assistant', question)
                    db.commit()
                    return
                if scoped.submitted_hashes is None:
                    raise RuntimeError('unit_submission_required')
                # 先持久化显式提交版本，测试前中断可以恢复该交接。
                progress['units'][unit['id']].update(status='submitted', submitted_file_hashes=scoped.submitted_hashes, self_test=scoped.self_test)
                w.write_json_atomic(evidence, progress)
            missing = [p for p in unit['implementation_files'] + unit['test_files'] if not (root / p).is_file()]
            if scoped.submitted_hashes != file_hashes(root, owned) or not scoped.restore_self_test(scoped.self_test):
                # 提交后文件版本变化必须重新交接，不能测试未经本次提交的版本。
                raise RuntimeError('unit_submission_stale')
            tested_scope = [p for u in completed + [unit] for p in u['implementation_files'] + u['test_files']]
            before = file_hashes(root, tested_scope)
            result = (ToolResult(str(uuid.uuid4()), 'exec', 'failed', error='unit_files_missing:' + ','.join(missing)) if missing else
                      w.execute_tool(db, task, run, tools, ToolCall(str(uuid.uuid4()), 'exec', {'action':'run', 'command':command}), history_key=f'unit_test:{unit["id"]}'))
            after = file_hashes(root, tested_scope)
            passed = test_passed(result, before, after)
            feedback = {'unit_id':unit['id'], 'attempt':attempt, 'command':command, 'expectations':unit['acceptance_criteria'],
                        'result':result.__dict__, 'file_hashes_before':before, 'file_hashes_after':after, 'passed':passed}
            test_report = f'evidence/units/{unit["id"]}-run-{run.id}-attempt-{attempt}.json'
            w.write_json_atomic(root / test_report, feedback)
            progress['units'][unit['id']] = {'status':'passed' if passed else 'failed', 'attempt':attempt,
                                             'file_hashes':file_hashes(root, scope), 'report':test_report}
            w.write_json_atomic(evidence, progress)
            safe_record_trace(db, task, run, 'validation', 'succeeded' if passed else 'failed',
                              f'{unit["name"]}测试', command, feedback)
            db.commit()
            if passed:
                completed.append(unit)
                break
            state = {}
        else:
            raise RuntimeError(f'unit_tests_failed:{unit["id"]}')
    if w.missing_product_files(root):
        raise RuntimeError('unit_product_entries_missing')
    index = (root / 'docs/dev-design.md').read_text(encoding='utf-8')
    w.write_json_atomic(root / 'evidence/implementation-lineage.json', {'dev_design_hash':w.content_hash(index),
        'design_source':'docs/dev-design.md', 'develop_attempt':run.attempt, 'product_hash':plan['product_hash'], 'plan_hash':plan_hash})
    run.output_path = 'product/implementation.md'
    w.finish_step(db, task, run, Step.test)
