"""已有网站返修的任务文件权限、连续会话与受控决定。"""
import hashlib
import json
import re
from pathlib import Path

from ..models import Step, StepStatus, TaskStatus
from . import repair_runtime as repair
from .container_execution import product_manifest
from .contracts import ToolCall
from .tools import TOOL_SCHEMAS, ToolRuntime
from .unit_workflow import UnitTools, RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA

LEGACY_PROMPT = '''你负责同一个已有网站返修任务的调查、计划、实现和修复。原始反馈与批准需求是依据，不能弱化断言来通过测试。
在授权 product 内按修改效果选择文件，不按旧卡片所有权选文件。可先 update_plan；用 search 定位，按清单和行范围 read，再 write/replace。read 默认 200 行，片段和哈希不是全文；缺失或变更的正文可补读。
先运行固定全量 run_unit_tests，依据 output.passed 判断；完整日志留档，工具返回测试摘要、失败详情与原日志查询引用。同版本已通过时重复自测复用真实证据，reused=true 不代表再次运行。修改后必须重新自测。
原缺陷已修复、当前版本自测通过且没有未完成修改时，调用 submit_unit_for_test；浏览器验证和原始目标审查由程序在提交后执行，无需为代替程序验证而反复调查验证脚本。自测成功不强制结束，确有必要仍可读或修改，不能省略尚未完成的修复。
submit_unit_for_test 或 request_decision 必须为本批最后动作。普通完成文本不能代替提交。
独立上下文接力仍是同一任务：context_session.recent_changes列出自上一边界后的成功修改，随后已运行boundary_request_id指向的真实自测。以development_state.current_version_passed判断当前证据，不因接力重复确认修改和测试先后；它不代表所有业务目标自动完成。
更新计划不是提交前置条件；确需更新时使用update_plan的steps与reason，可与submit_unit_for_test同批，提交放最后，避免为计划状态单开请求。
改变业务、重要接口或数据规则必须 request_decision；回答不等于自动更新批准设计，正式设计未更新时不能擅自实施产品大改动。
程序负责冻结、测试、启动、浏览器与独立审查。验证失败后在原会话继续修复。禁止任意 shell、删除、安装依赖、修改正式需求／审计／预算。'''

PREVIOUS_PROMPT = LEGACY_PROMPT + '''
本尝试使用上下文契约v2，以下说明优先于上文旧字段说明：current_task_facts是程序核对的当前事实，原反馈只在input；其中self_test是唯一当前自测入口，latest_validation_failure是最新独立验证失败，不得被旧自测覆盖。
work_progress是模型通过update_plan保存的判断，不是程序验证。可选findings记录已确认原因和依据，open_questions记录未解决疑问，next_action记录剩余工作；版本适用性为needs_review时须核对，不能当作已完成证据。已有清晰进度无需为了更新计划另开调用。
累计修改只证明成功写入及最新写入版本是否仍适用，不证明每次历史修改仍有效。目标未独立审查不表示已实现或未实现。必要阅读／修改继续允许；完成业务修复且当前自测通过时仍须显式提交。历史查询、实际正文范围和权限保持。'''


PREVIOUS_PROGRESS_PROMPT = PREVIOUS_PROMPT + '''
调查推进规则：每次读取或搜索的description说明尚未解决的具体问题，以及它如何影响本次修复或验收；优先使用已提供的同版本正文与事实，不为重复确认扩大调查。
失败原因、批准接口／业务预期和可实施修改方案已有依据，且没有影响修改的未决问题时，优先完成相关修改并运行全量自测；缺少依据继续调查，自测失败再按实际失败定位。必要调查始终允许，不按读取次数强制修改。
与本次反馈无关、并非本次修改引入的已有疑点先记录；不影响本次修复或验收时继续当前任务，不把全局符合性检查当作修改前置。涉及本次设计冲突、业务风险或无法判断成功时继续针对性调查，必要时request_decision。
独立读取和参数已确定的多处修改尽量同批；需要上一结果确定下一参数、版本或状态时分批，修改结束再自测。不能无条件把修改、自测、提交同批，当前通过仍需判断业务完成并显式提交。程序负责独立浏览器与目标审查，无具体未决问题时无需预先通读验证脚本。
确有需要保存的原因、依据和剩余疑问时可用既有update_plan字段与正常动作合批；不要求每轮更新，也不为了计划另开调用。'''


PREVIOUS_NO_REVIEW_PROMPT = PREVIOUS_PROGRESS_PROMPT.replace(
    '浏览器验证和原始目标审查由程序在提交后执行', '浏览器验证由程序在提交后执行').replace(
    '程序负责冻结、测试、启动、浏览器与独立审查。', '程序负责冻结、测试、启动和浏览器验证。').replace(
    '程序负责独立浏览器与目标审查', '程序负责实际浏览器验证') + '''
本次提交后的验证为全量测试、启动和实际浏览器验证，不再有独立模型目标／覆盖审查；通过后等待用户验收，原始目标由用户确认，不自动认定测试覆盖完整需求。'''

PROMPT = PREVIOUS_NO_REVIEW_PROMPT + '''
search可用path限定授权内文件或目录；已知接口或模块位置时优先限定范围，未知位置仍可全域搜索。范围搜索片段不是全文，必要正文继续按实际缺失范围read。'''


def select_prompt(state: dict) -> str:
    """新会话使用推进规则，旧会话只恢复其原哈希绑定的有效提示词。"""
    if not state.get('session'):
        return PROMPT
    candidates = (PREVIOUS_PROMPT, PREVIOUS_PROGRESS_PROMPT, PREVIOUS_NO_REVIEW_PROMPT, PROMPT) if uses_current_facts(state) else (LEGACY_PROMPT,)
    # 未知绑定仍拒绝，不将旧历史静默迁移到新的模型指令。
    for candidate in candidates:
        if hashlib.sha256(candidate.encode()).hexdigest() == state['session'].get('prompt_hash'):
            return candidate
    raise RuntimeError('repair_session_binding_changed')


def uses_current_facts(state: dict) -> bool:
    """只为明确绑定新契约的尝试启用新视图，旧会话不隐式迁移。"""
    return state.get('session', {}).get('context_contract') == 'v2'


def current_facts(context: dict, state: dict, history: list[dict], tools) -> dict:
    """从原始事实投影当前任务，保留失败与模型判断，不改检查点或权限。"""
    versions = tools.self_test_versions()
    boundary = state['session'].get('validation_boundary', 0)
    valid_boundary = isinstance(boundary, int) and not isinstance(boundary, bool) and 0 <= boundary <= len(history)
    changes = {}
    latest_test = None
    # 累计写入保留类型明确的来源，并核对最后写入实际哈希而非模型描述。
    for index, entry in enumerate(history):
        action, result = entry.get('action', {}), entry.get('result', {})
        if result.get('status') != 'succeeded':
            continue
        output = result.get('output') or {}
        ref = {'model_call_id': entry.get('model_request_id'), 'tool_call_id': action.get('call_id'),
               'query_tool': 'get_model_call_summaries'}
        if action.get('tool_name') in {'write', 'replace'}:
            path = action.get('parameters', {}).get('path')
            if path in versions:
                change = changes.setdefault(path, {'path': path, 'operations': []})
                # 明确区分原修改操作和历史查询入口，描述仅保留原调用意图。
                change['operations'].append({**ref, 'tool_name': action['tool_name'],
                                             'description': action.get('parameters', {}).get('description', '')})
                change['last_write_sha256'] = entry.get('repair_versions_after', {}).get(path)
        if action.get('tool_name') == 'run_unit_tests' and valid_boundary and index >= boundary:
            latest_test = (output, ref)
    test = {'state': 'not_tested'}
    if latest_test:
        output, ref = latest_test
        matches = (output.get('command') == tools.self_test_command()
                   and output.get('file_hashes_before') == versions
                   and output.get('file_hashes_after') == versions
                   and all(value is not None for value in versions.values()))
        passed = matches and tools.restore_self_test(output)
        test = {'state': 'current_passed' if passed else 'failed' if matches else 'stale',
                'evidence': self_test_view(output, ref), 'matches_current_files': matches}
    blockers = []
    if not valid_boundary:
        blockers.append('invalid_validation_boundary')
    if state['session'].get('pending_actions') or any(e.get('action') and not e.get('result') for e in history):
        blockers.append('unknown_side_effect')
    if state.get('state') != 'executing':
        blockers.append('not_executing')
    if any(value is None for value in versions.values()):
        blockers.append('missing_product_files')
    if test['state'] != 'current_passed':
        blockers.append('current_self_test_required')
    decisions = state['session'].get('decisions', [])
    if any(not item.get('answer') for item in decisions):
        blockers.append('unanswered_decision')
    for change in changes.values():
        change['latest_write_matches_current_files'] = bool(change['last_write_sha256']) and change['last_write_sha256'] == versions[change['path']]
    plan = state['session'].get('plan')
    progress = {'source': 'model_judgment', 'value': plan,
                'applicability': 'not_recorded' if not plan else
                    'current' if plan.get('manifest') == repair.manifest(tools.workspace) else 'needs_review'}
    # 删除默认历史状态的重复入口；协议正文和查询结果仍由原渠道实际提供。
    projected = {k: v for k, v in context.items() if k not in {
        'current_task', 'development_state', 'unit_self_test', 'latest_execution_versions',
        'tool_summaries', 'earlier_summary_count', 'original_feedback', 'plan', 'decisions', 'last_failure',
        'test_evidence_matches_current_files'}}
    projected['current_task_facts'] = {
        'contract': 'v2', 'session_id': state['session']['id'], 'phase': state['state'],
        'feedback_source': 'input', 'approved_documents': context.get('approved_documents', []),
        'changes': list(changes.values()), 'self_test': test,
        'latest_validation_failure': state.get('last_failure'),
        'latest_validation_failure_scope': 'last_independent_validation_not_inferred_for_current_files',
        'decisions': decisions,
        'submission': {'known_blockers': blockers, 'business_completion': 'model_must_judge',
                       'explicit_submission_required': True, 'automatic_submit': False},
        'after_submission': {'state': 'not_run_for_next_submission',
                             'steps': ['independent_tests', 'browser_verification'] + (
                                 [] if state.get('validation_policy') == 'tests_and_browser' else ['original_goal_review'])}}
    projected['work_progress'] = progress
    if 'context_session' in projected:
        # 接力只描述协议边界，当前修改和测试统一由任务事实提供。
        projected['context_session'] = {k: v for k, v in projected['context_session'].items()
                                        if k not in {'recent_changes', 'diagnostic'}}
    return projected


def self_test_view(output: dict, result_ref: dict | None = None) -> dict:
    """向模型返回确定性自测摘要，原结果仍由审计和检查点完整保存。"""
    result = output.get('result', {})
    command_output = result.get('output') or {}
    stdout = command_output.get('stdout', '')
    view = {k: v for k, v in output.items() if k != 'result'}
    counts = {name: int(value) for name, value in re.findall(
        r'^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$', stdout, re.MULTILINE)}
    view['result'] = {'status': result.get('status'), 'error': result.get('error'),
                      'exit_code': command_output.get('exit_code'),
                      'timed_out': command_output.get('timed_out', False), 'counts': counts}
    view['result_ref'] = result_ref or {'content_source': 'checkpoint_audit'}
    if output.get('passed') is not True:
        # 提取真实失败用例及其 YAML 诊断，非 TAP 错误保留原输出末尾供定位。
        blocks = []
        current = None
        for line in stdout.splitlines():
            if re.match(r'^\s*not ok \d+', line):
                if current:
                    blocks.append('\n'.join(current))
                current = [line]
            elif current is not None:
                if re.match(r'^\s*(?:# Subtest:|ok \d+|1\.\.\d+)', line):
                    blocks.append('\n'.join(current))
                    current = None
                else:
                    current.append(line)
        if current:
            blocks.append('\n'.join(current))
        details = '\n\n'.join(blocks) if blocks else stdout
        stderr = command_output.get('stderr', '')
        view['failure_details'] = {'stdout': details[-16000:], 'stderr': stderr[-6000:],
                                   'truncated': len(details) > 16000 or len(stderr) > 6000
                                   or bool(command_output.get('truncated'))}
    return view


def project_test_history(history: list[dict]) -> list[dict]:
    """只投影自测和提交结果，保持原思考、调用 ID、工具配对及原始历史不变。"""
    projected = []
    for entry in history:
        action = entry.get('action', {})
        result = entry.get('result', {})
        output = result.get('output')
        ref = {'content_source': 'checkpoint_audit', 'query_tool': 'get_model_call_summaries',
               'model_call_id': entry.get('model_request_id'), 'tool_call_id': action.get('call_id')}
        if result.get('status') == 'succeeded' and isinstance(output, dict):
            if action.get('tool_name') == 'run_unit_tests':
                output = self_test_view(output, ref)
            elif action.get('tool_name') == 'submit_unit_for_test' and output.get('self_test'):
                output = {**output, 'self_test': self_test_view(output['self_test'], ref)}
            else:
                projected.append(entry)
                continue
            entry = {**entry, 'result': {**result, 'output': output}}
        projected.append(entry)
    return projected


def schema(name, description, properties, required):
    """声明最小受控状态工具，拒绝额外模型参数。"""
    return {'type': 'function', 'function': {'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}}}


PLAN_SCHEMA = schema('update_plan', '保存本任务局部计划及修订原因，不改变需求或权限。',
                     {'steps': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 20},
                      'reason': {'type': 'string'}}, ['steps', 'reason'])
PROGRESS_SCHEMA = schema('update_plan', '保存计划与模型工作判断，不替代真实验证或审批。',
    {**PLAN_SCHEMA['function']['parameters']['properties'],
     'findings': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 20},
     'open_questions': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 20},
     'next_action': {'type': 'string'}}, ['steps', 'reason'])
DECISION_SCHEMA = schema('request_decision', '保存待确认问题并暂停，不自行批准产品改变。',
                         {k: {'type': 'string'} for k in ['question', 'impact', 'proposal']},
                         ['question', 'impact', 'proposal'])
SEARCH_SCHEMA = schema('search', '在任务授权文件内搜索字面文本，每页最多 50 条；续查携带返回的 version 和 next_cursor。',
                       {'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                        'cursor': {'type': 'integer', 'minimum': 0}, 'version': {'type': 'string'}}, ['query'])

SCOPED_SEARCH_SCHEMA = schema('search', '搜索授权内字面文本，可用path限定文件或目录；默认全域，每页最多50条，续查保持范围并携带version和next_cursor。',
    {**SEARCH_SCHEMA['function']['parameters']['properties'], 'path': {'type': 'string', 'minLength': 1}}, ['query'])


class RepairTools(UnitTools):
    """按完整产品边界授权，不继承旧卡片文件所有权。"""

    default_read_lines = 200

    def __init__(self, root: Path):
        """核对安全产品快照并仅开放当前任务文档和失败引用。"""
        files = ['product/' + p for p in product_manifest(root / 'product')]
        readable = ['docs/' + name for name in ['product.md', 'architecture.md', 'dev-design.md']
                    if (root / 'docs' / name).is_file() and not (root / 'docs' / name).is_symlink()]
        state = repair.load(root)
        if (root / 'evidence/repair-objectives.json').is_file():
            readable.append('evidence/repair-objectives.json')
        if state and state.get('last_failure'):
            readable.append(state['last_failure']['evidence'])
        super().__init__(root, files, readable, files, files,
                         [p for p in files if p.endswith(('.test.js', '.test.cjs', '.test.mjs'))])

    def _product_path(self, value: str) -> Path:
        """拒绝产品外路径及受保护名字，校验已有父目录无链接。"""
        raw = Path(value)
        if raw.is_absolute() or '..' in raw.parts or not raw.parts or raw.parts[0] != 'product':
            raise ValueError('repair_write_outside_product')
        forbidden = {'.git', '.aws', '.codex', '.agents', 'secrets', 'AGENTS.md', 'ROADMAP.md'}
        if any(p in forbidden or p.startswith('.env') for p in raw.parts):
            raise ValueError('repair_protected_path')
        target = self.workspace / raw
        for part in [target, *target.parents]:
            if part == self.workspace:
                break
            if part.is_symlink():
                raise ValueError('repair_symlink_forbidden')
        product_manifest(self.product)
        return self._safe_path(value)

    def _refresh_files(self) -> None:
        """每次版本核对包含当前新增文件，避免固定旧清单漏算。"""
        files = ['product/' + p for p in product_manifest(self.product)]
        self.submission_files = self.self_test_files = files
        self.test_files = [p for p in files if p.endswith(('.test.js', '.test.cjs', '.test.mjs'))]
        self.writable = {self._safe_path(p) for p in files}
        self.readable |= self.writable

    def self_test_versions(self) -> dict:
        """以当前全产品字节与集合检查自测适用性。"""
        self._refresh_files()
        return super().self_test_versions()

    def submission_versions(self) -> dict:
        """提交包含所有新增实现和测试，不允许只交绿灯子集。"""
        self._refresh_files()
        return super().submission_versions()

    def self_test_command(self) -> str:
        """固定全量 Node 测试发现命令，不接受模型传参选子集。"""
        return 'node --test'

    def _run_unit_tests(self) -> dict:
        """当前完整产品已有通过证据则复用，任何版本变化或失败都实际重测。"""
        if self.self_test and self.restore_self_test(self.self_test):
            return {**self.self_test, 'reused': True,
                    'guidance': '当前完整产品版本自测已通过，未再次运行；若修复已完成，请显式提交，程序负责后续验证。'}
        return {**super()._run_unit_tests(), 'reused': False}

    def _write(self, path: str, content: str, overwrite: bool) -> dict:
        """允许相关新增普通产品文件，写入后旧自测版本自然失效。"""
        target = self._product_path(path)
        self.writable.add(target)
        self.readable.add(target)
        return super()._write(path, content, overwrite)

    def _replace(self, path: str, old: str, new: str) -> dict:
        """精确替换使用相同产品边界与冻结门禁。"""
        self._product_path(path)
        return super()._replace(path, old, new)

    def execute(self, call: ToolCall):
        """仅调度受控计划、决定和原文件／自测／提交工具。"""
        if call.tool_name in {'update_plan', 'request_decision', 'search'}:
            return ToolRuntime.execute(self, call)
        if call.tool_name == 'read':
            self._refresh_files()
        return super().execute(call)

    def _search(self, query: str, cursor: int = 0, version: str | None = None, path: str | None = None) -> dict:
        """使用任务读取清单进行字面搜索，不开放模型 shell。"""
        from .repair_search import search
        return search(self, query, cursor, version, path)

    def _read(self, path: str, start_line: int | None = None, end_line: int | None = None) -> dict:
        """默认返回 200 行，显式请求继续范围，登记实际正文与字节截断。"""
        if self._safe_path(path) not in self.readable:
            raise ValueError('unit_read_outside_scope')
        default_range = start_line is None and end_line is None
        output = ToolRuntime._read(self, path, 1 if default_range else start_line,
                                  self.default_read_lines if default_range else end_line)
        if default_range and output['end_line'] < output['total_lines']:
            output.update(truncated=True, hint='more_lines_available_use_explicit_range')
        return output

    def _update_plan(self, steps: list[str], reason: str, findings: list[str] | None = None,
                     open_questions: list[str] | None = None, next_action: str | None = None) -> dict:
        """保存局部计划及理由，不更新业务文档或扩大权限。"""
        if (not isinstance(steps, list) or not 1 <= len(steps) <= 20
                or any(not isinstance(s, str) or not s.strip() for s in steps)
                or not isinstance(reason, str) or not reason.strip()):
            raise ValueError('repair_plan_invalid')
        state = repair.load(self.workspace)
        if state['state'] != 'executing':
            raise ValueError('repair_submission_frozen')
        progress = {'findings': findings, 'open_questions': open_questions, 'next_action': next_action}
        if any(value is not None for value in progress.values()):
            if not uses_current_facts(state):
                raise ValueError('repair_progress_contract_required')
            if (any(value is not None and (not isinstance(value, list) or len(value) > 20
                    or any(not isinstance(item, str) or not item.strip() for item in value))
                    for value in (findings, open_questions))
                    or next_action is not None and (not isinstance(next_action, str) or not next_action.strip())):
                raise ValueError('repair_progress_invalid')
        state['session']['plan'] = {'steps': steps, 'reason': reason}
        if uses_current_facts(state):
            # 判断绑定记录时的产品及设计版本，后续变更只标记需复核，不自动批准。
            state['session']['plan'].update({k: v for k, v in progress.items() if v is not None})
            state['session']['plan']['manifest'] = repair.manifest(self.workspace)
        repair.save(self.workspace, state)
        return state['session']['plan']

    def _request_decision(self, question: str, impact: str, proposal: str) -> dict:
        """持久保存具体待决定事项后暂停同一会话。"""
        if any(not isinstance(s, str) or not s.strip() for s in [question, impact, proposal]):
            raise ValueError('repair_decision_invalid')
        state = repair.load(self.workspace)
        if state['state'] != 'executing':
            raise ValueError('repair_submission_frozen')
        decisions = state['session'].setdefault('decisions', [])
        decision = {'id': f"{state['session']['id']}-{len(decisions)+1}", 'question': question,
                    'impact': impact, 'proposal': proposal, 'manifest': repair.manifest(self.workspace)}
        decisions.append(decision)
        state.update(state='waiting_decision', decision_id=decision['id'])
        repair.save(self.workspace, state)
        return decision


def answer(task, data: dict) -> bool:
    """仅匹配当前明确问题的非空回答恢复，不自动修改设计或预算。"""
    from .worker import workspace_for
    root = workspace_for(task)
    state = repair.load(root)
    if state and state.get('session', {}).get('pending_actions'):
        raise RuntimeError('unknown_side_effect')
    if not state or state['state'] != 'waiting_decision':
        return False
    if (data.get('decision_id') != state['decision_id'] or not isinstance(data.get('content'), str)
            or not data['content'].strip()):
        raise ValueError('repair_decision_answer_mismatch')
    decision = state['session']['decisions'][-1]
    if decision['manifest'] != repair.manifest(root):
        raise ValueError('repair_decision_version_changed')
    decision['answer'] = data['content']
    state.update(state='executing', decision_id=None)
    repair.save(root, state)
    task.status, task.cur_step = TaskStatus.running, Step.develop
    return True


def execute(db, task, run) -> None:
    """恢复任务级协议检查点，显式提交后交给程序固定流水线。"""
    from . import worker as w
    root = w.workspace_for(task)
    state = repair.load(root)
    if state.get('session', {}).get('pending_actions'):
        raise RuntimeError('unknown_side_effect')
    if not repair.isolation_ready():
        raise RuntimeError('repair_execution_isolation_pending')
    session_id = f'{task.id}-{state["event_id"]}'
    selected_prompt = select_prompt(state)
    binding = {'id': session_id, 'provider': 'deepseek',
               'prompt_hash': hashlib.sha256(selected_prompt.encode()).hexdigest()}
    if state.get('session'):
        if any(state['session'].get(k) != v for k, v in binding.items()):
            raise RuntimeError('repair_session_binding_changed')
    else:
        # 原测试正文作为受保护基线，提交时保留修改依据与差异。
        files = product_manifest(root / 'product')
        tests = {p: (root / 'product' / p).read_text() for p in files
                 if p.endswith(('.test.js', '.test.cjs', '.test.mjs')) or p == 'verify_product.py'}
        state['session'] = {**binding, 'context_contract': 'v2', 'plan': None, 'decisions': [], 'original_tests': tests}
        repair.save(root, state)
    checkpoint = root / f'evidence/repair-session-{session_id}-checkpoint.json'
    if checkpoint.is_file():
        entries = json.loads(checkpoint.read_text())
        if not isinstance(entries, list) or any(e.get('action') and not e.get('result') for e in entries):
            raise RuntimeError('unknown_side_effect')
    run.checkpoint_path = str(checkpoint)
    db.commit()
    tools = RepairTools(root)
    # 只复用当前版本的真实自测／提交，历史失败仍保留原协议。
    if checkpoint.is_file():
        entries = json.loads(checkpoint.read_text())
        for entry in reversed(entries[state['session'].get('validation_boundary', 0):]):
            action = entry.get('action', {}).get('tool_name')
            output = entry.get('result', {}).get('output', {})
            if action == 'submit_unit_for_test' and tools.restore_submission(output):
                break
            if action == 'run_unit_tests':
                tools.restore_self_test(output)
                break
    schemas = [s for s in TOOL_SCHEMAS if s['function']['name'] in {'read', 'write', 'replace'}]
    schemas += [RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA,
                PROGRESS_SCHEMA if uses_current_facts(state) else PLAN_SCHEMA, DECISION_SCHEMA,
                SCOPED_SEARCH_SCHEMA if selected_prompt == PROMPT else SEARCH_SCHEMA]
    if tools.submitted_hashes is None:
        from .repair_objectives import pending
        w.model_tool_loop(db, task, run, selected_prompt, state['feedback'],
            {'repair_session': True, 'session_id': session_id, 'unit_file_scope': tools.self_test_files,
             'approved_documents': [p for p in sorted(str(p.relative_to(root)) for p in tools.readable) if p.startswith('docs/')],
             'plan': state['session']['plan'], 'decisions': state['session']['decisions'],
             'unresolved_acceptance_objectives': w.compact_repair_objectives(pending(task)),
             'last_failure': state.get('last_failure'), 'original_feedback': state['feedback']}, tools,
            tool_schemas=schemas, history_key='repair-session:' + session_id,
            stop_when=lambda: tools.submitted_hashes is not None or repair.load(root)['state'] == 'waiting_decision')
    state = repair.load(root)
    if state['state'] == 'waiting_decision':
        run.status, task.status = StepStatus.waiting_user, TaskStatus.waiting_user
        w.add_message(db, task, 'assistant', state['session']['decisions'][-1]['question'])
        db.commit()
        return
    if tools.submitted_hashes is None:
        raise RuntimeError('repair_submission_required')
    repair.persist_submission(task, tools)
    w.finish_step(db, task, run, Step.test)
