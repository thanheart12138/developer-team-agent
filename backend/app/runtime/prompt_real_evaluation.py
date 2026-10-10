"""受控单次真实评测：固定输入授权、持久预算、只观察工具选择。"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..database import Base
from ..models import Task, TaskStatus, Step
from ..config import settings
from .contracts import ModelRequest
from .model import DeepSeekRuntime
from .prompt_management import PromptStore, atomic_json, read_json
from .prompt_registry import load_prompt, compose_prompts
from . import repair_runtime as repair


class RealEvaluation:
    """限定登记案例的一次响应，授权文件由受控管理员在用户批准后写入。"""

    def __init__(self, store: PromptStore):
        """沿用管理平台结果目录，不接受请求指定宿主目录。"""
        self.store = store
        self.root = store.results / 'real-runs'

    def path(self, run_id: str) -> Path:
        """仅访问服务器生成的运行ID，禁止符号链接和路径穿越。"""
        if not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise ValueError('real_run_id_invalid')
        path = self.root / run_id
        if self.root.is_symlink() or path.is_symlink():
            raise ValueError('real_run_path_unsafe')
        return path

    def payload(self, name: str, version: str, case_id: str) -> dict:
        """固定登记案例与工具协议，只传送案例内已审阅输入。"""
        document, case_hash = self.store.cases(name)
        case = next((item for item in document['cases'] if item['id'] == case_id), None)
        if not case:
            raise ValueError('real_case_not_found')
        prompt = self.store.evaluation_prompt(name, version, document, case)
        tools = []
        declared_tools = document['contract'].get('evaluation_tools', [])
        if declared_tools:
            # 使用现有受控schema；声明工具仍只观察，绝不执行生成动作。
            from .tools import TOOL_SCHEMAS, QUERY_TOOL_SCHEMAS
            from .unit_workflow import RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA
            from .repair_session import PROGRESS_SCHEMA, DECISION_SCHEMA, SCOPED_SEARCH_SCHEMA, VERIFY_AND_SUBMIT_SCHEMA
            available = {schema['function']['name']: schema for schema in
                         [*TOOL_SCHEMAS, *QUERY_TOOL_SCHEMAS, RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA,
                          PROGRESS_SCHEMA, DECISION_SCHEMA, SCOPED_SEARCH_SCHEMA, VERIFY_AND_SUBMIT_SCHEMA]}
            if not isinstance(declared_tools, list) or any(not isinstance(key, str) or key not in available for key in declared_tools):
                raise ValueError('evaluation_tools_invalid')
            tools = [available[key] for key in declared_tools]
        if name == 'repair-executor':
            # 与返修v5相同的权限声明；本入口不执行生成的工具动作。
            from .repair_session import PROGRESS_SCHEMA, DECISION_SCHEMA, SCOPED_SEARCH_SCHEMA, VERIFY_AND_SUBMIT_SCHEMA
            from .tools import TOOL_SCHEMAS, QUERY_TOOL_SCHEMAS
            from .unit_workflow import RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA
            if int(version[1:]) < 5:
                raise ValueError('real_probe_tool_contract_unconfirmed')
            tools = [s for s in TOOL_SCHEMAS if s['function']['name'] in {'read', 'write', 'replace'}]
            tools += [RUN_UNIT_TESTS_SCHEMA, SUBMIT_UNIT_SCHEMA, PROGRESS_SCHEMA, DECISION_SCHEMA, SCOPED_SEARCH_SCHEMA]
            # Worker 对含read的执行阶段附加同一组只读历史查询，保持评测协议一致。
            tools += QUERY_TOOL_SCHEMAS
            if int(version[1:]) >= 6:
                tools.append(VERIFY_AND_SUBMIT_SCHEMA)
            prompt = compose_prompts([load_prompt('execution-base', prompt_root=self.store.root), prompt])
        return {'instructions': prompt.text, 'input': case['input'].get('task', ''),
                'context': case['input'].get('context', {}), 'tools': tools,
                'components': list(prompt.components), 'case_hash': case_hash,
                'model': settings.deepseek_model, 'base_url': settings.deepseek_base_url}

    def prepare(self, name: str, version: str, case_id: str, http_cap: int) -> dict:
        """只创建待审批固定输入，不创建批准文件或发送请求。"""
        if type(http_cap) is not int or not 1 <= http_cap <= 30:
            raise ValueError('real_run_budget_invalid')
        payload = self.payload(name, version, case_id)
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        run_id = uuid.uuid4().hex
        path = self.path(run_id)
        self.root.mkdir(parents=True, exist_ok=True)
        convention = self.root / 'README.md'
        if not convention.exists():
            convention.write_text('# 受控真实评测运行目录\n\n每个服务器生成ID一个目录：manifest.json与input.json固定待审批输入；'
                                  'approval.json只由受控管理员在明确用户批准后写入；test.sqlite、'
                                  'evidence/持久预算、response.json和receipt.json留存现场。'
                                  '已有现场不得重置，工具只观察不执行；页面不能创建授权。\n')
        path.mkdir(parents=True)
        manifest = {'id': run_id, 'name': name, 'version': version, 'case_id': case_id,
                    'provider': 'deepseek', 'destination': 'https://api.deepseek.com',
                    'http_cap': http_cap, 'input_hash': digest, 'mode': 'first_response_only'}
        atomic_json(path / 'manifest.json', manifest)
        atomic_json(path / 'input.json', payload)
        return manifest

    def runs(self, name: str) -> list[dict]:
        """列出本提示词运行状态，缺授权时显示待批准。"""
        self.store.entry(name)
        rows = []
        if not self.root.exists():
            return rows
        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            manifest = read_json(self.path(path.name) / 'manifest.json')
            if manifest['name'] != name:
                continue
            receipt = read_json(path / 'receipt.json') if (path / 'receipt.json').is_file() else None
            status = 'completed' if receipt else 'recovery_required' if (path / 'test.sqlite').exists() else 'prepared'
            rows.append({**manifest, 'status': status,
                         'report_id': receipt['report_id'] if receipt else None})
        return rows

    def run(self, run_id: str) -> dict:
        """校验授权及输入身份，单次执行；已有报告直接返回，异常现场不重置。"""
        path = self.path(run_id)
        if not path.is_dir():
            raise FileNotFoundError('real_run_not_found')
        if any(child.is_symlink() for child in path.iterdir()):
            raise ValueError('real_run_path_unsafe')
        with (path / '.run.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            receipt_path = path / 'receipt.json'
            if receipt_path.is_file():
                return self.store.report(read_json(receipt_path)['report_id'])
            manifest = read_json(path / 'manifest.json')
            if (manifest.get('id') != run_id or type(manifest.get('http_cap')) is not int
                    or not 1 <= manifest['http_cap'] <= 30):
                raise ValueError('real_run_manifest_invalid')
            approval_path = path / 'approval.json'
            if not approval_path.is_file() or approval_path.is_symlink():
                raise ValueError('real_model_authorization_pending')
            approval = read_json(approval_path)
            if (approval.get('approved') is not True or not approval.get('source')
                    or any(approval.get(key) != manifest[key] for key in
                           ('input_hash', 'http_cap', 'provider', 'destination'))):
                raise ValueError('real_model_authorization_mismatch')
            if manifest['provider'] != 'deepseek' or manifest['destination'] != 'https://api.deepseek.com':
                raise ValueError('real_model_destination_unconfirmed')
            payload = self.payload(manifest['name'], manifest['version'], manifest['case_id'])
            if payload['base_url'].rstrip('/') != manifest['destination']:
                raise ValueError('real_model_destination_unconfirmed')
            digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if digest != manifest['input_hash'] or read_json(path / 'input.json') != payload:
                raise ValueError('real_evaluation_input_changed')
            # 已有库或账本而无报告说明上次中断，不能重新建任务抹掉计数。
            if (path / 'test.sqlite').exists() or repair.load(path):
                raise ValueError('real_evaluation_recovery_required')
            return self.execute(path, manifest, payload, approval_path)

    def execute(self, path: Path, manifest: dict, payload: dict, approval_path: Path) -> dict:
        """复用实际Provider认证与HTTP守卫，失败保留原计数和未知用量。"""
        started = time.time()
        engine = create_engine('sqlite+pysqlite:///' + str(path / 'test.sqlite'))
        observation = {'text': '', 'actions': [], 'complete': not bool(payload['tools'])}
        error = None
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                task = Task(task_name='prompt-evaluation', workspace_path=str(path),
                            status=TaskStatus.running, cur_step=Step.develop)
                db.add(task)
                db.commit()
                repair.save(path, {'workflow': 'repair-v1', 'revision': 0, 'state': 'executing',
                    'validation_policy': 'tests_and_browser', 'authorization_ref': 'approval.json',
                    'authorization_hash': hashlib.sha256(approval_path.read_bytes()).hexdigest(),
                    'budget': {'provider': 'deepseek', 'historical_attempts': 0, 'attempts_used': 0,
                               'total_limit': manifest['http_cap'], 'review_reserve': 0, 'requests': []}})
                request = ModelRequest(payload['instructions'], payload['input'], payload['context'],
                                       payload['tools'], manifest['id'])
                response = DeepSeekRuntime(db).call(task.id, request)
                db.commit()
                observation.update(text=response.text, actions=[{'tool_name': action.tool_name,
                    'parameters': action.parameters, 'call_id': action.call_id} for action in response.actions])
                atomic_json(path / 'response.json', response.raw_response)
        except Exception as exc:
            # 凭据配置失败可能在预约前发生，仍输出未发送而非伪造成功。
            error = type(exc).__name__
            observation['complete'] = False
        finally:
            engine.dispose()
        state = repair.load(path)
        if not state:
            raise RuntimeError('real_evaluation_recovery_required')
        current = self.payload(manifest['name'], manifest['version'], manifest['case_id'])
        if hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest() != manifest['input_hash']:
            # 运行中编辑案例不能把旧响应登记为新输入的真实结果，原账本仍留存。
            raise ValueError('real_evaluation_input_changed')
        report = self.store.record_real(manifest['name'], manifest['version'],
            {manifest['case_id']: observation}, state['budget'],
            {'run_id': manifest['id'], 'input_hash': manifest['input_hash'],
             'prompt_components': payload['components'],
             'elapsed_seconds': round(time.time() - started, 2), 'error_type': error,
             'limitations': ['首批工具只记录、不执行；不能证明完整软件修复。']})
        atomic_json(path / 'receipt.json', {'report_id': report['id']})
        return report


def main() -> None:
    """离线准备明确输入供审批，或执行已批准ID；没有隐式真实调用。"""
    parser = argparse.ArgumentParser(description='受控提示词真实评测')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--name', required=True)
    prepare.add_argument('--version', required=True)
    prepare.add_argument('--case', required=True)
    prepare.add_argument('--http-cap', type=int, required=True)
    run = commands.add_parser('run')
    run.add_argument('--id', required=True)
    args = parser.parse_args()
    runtime = RealEvaluation(PromptStore())
    result = runtime.prepare(args.name, args.version, args.case, args.http_cap) if args.command == 'prepare' else runtime.run(args.id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
