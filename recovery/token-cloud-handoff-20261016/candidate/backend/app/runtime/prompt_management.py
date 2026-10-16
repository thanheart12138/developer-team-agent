"""文件驱动的提示词管理：版本、案例、评测证据和受控激活。"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import uuid

from .prompt_registry import PROMPT_ROOT, SAFE_NAME, SAFE_VERSION, PLACEHOLDER, sha256_text, load_prompt, compose_prompts
from .prompt_evaluation import evaluate, validate_cases
from ..config import settings


def read_json(path: Path) -> dict:
    """读取受控文件中的对象，缺失明确反馈而非造空成功结果。"""
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: dict) -> None:
    """先完成临时正文，再原子替换受控文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class PromptStore:
    """约束操作路径并协调文件写入，数据库不保存第二套模板状态。"""

    def __init__(self, root: Path | None = None, results: Path | None = None):
        """默认使用项目注册表与被忽略的工作区，可显式注入隔离测试目录。"""
        self.root = root or PROMPT_ROOT
        self.results = results or settings.workspace_root / "prompt-evaluations"

    @contextmanager
    def locked(self):
        """在当前本地POSIX环境串行更新注册及案例文件，防止并发丢失。"""
        with (self.root / ".management.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def registry(self) -> tuple[dict, str]:
        """返回注册内容及乐观并发校验身份。"""
        path = self.root / "registry.json"
        return read_json(path), sha256_text(path.read_text())

    def entry(self, name: str) -> dict:
        """仅允许已经登记的规范名称，拒绝路径穿越和未知提示词。"""
        if not SAFE_NAME.fullmatch(name):
            raise ValueError("prompt_name_invalid")
        entry = self.registry()[0]["prompts"].get(name)
        if not entry:
            raise KeyError("prompt_not_found")
        if (self.root / name).is_symlink():
            raise ValueError("prompt_path_unsafe")
        return entry

    def case_file(self, name: str) -> Path:
        """案例路径由注册身份决定，不接受用户文件路径。"""
        self.entry(name)
        path = self.root / "cases" / f"{name}.json"
        if path.is_symlink() or (self.root / 'cases').is_symlink():
            raise ValueError("case_path_unsafe")
        return path

    def cases(self, name: str) -> tuple[dict, str]:
        """返回案例文档和内容哈希，供编辑与结果适用性检查。"""
        path = self.case_file(name)
        return read_json(path), sha256_text(path.read_text())

    def detail(self, name: str) -> dict:
        """返回全部版本正文、变量与案例，历史文件仍校验哈希。"""
        entry = self.entry(name)
        versions = []
        for version in entry.get("versions", {entry["active"]: entry["sha256"]}):
            text = (self.root / name / f"{version}.md").read_text()
            variables = sorted(set(PLACEHOLDER.findall(text)))
            loaded = load_prompt(name, {key: f"preview:{key}" for key in variables}, self.root, version)
            versions.append({"version": version, "text": text, "sha256": loaded.template_sha256, "variables": variables})
        document, digest = self.cases(name)
        return {"name": name, "entry": entry, "versions": versions, "cases": document,
                "case_hash": digest, "registry_hash": self.registry()[1]}

    def create_version(self, name: str, text: str, expected_hash: str) -> dict:
        """创建不可覆盖的新版本，明确冲突时不改变激活版本。"""
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 100_000:
            raise ValueError("prompt_text_invalid")
        with self.locked():
            entry = self.entry(name)
            registry, digest = self.registry()
            if digest != expected_hash:
                raise ValueError("registry_conflict")
            version = "v" + str(max(int(v[1:]) for v in entry.get("versions", {entry["active"]:entry["sha256"]})) + 1)
            target = self.root / name / f"{version}.md"
            # 独占创建避免版本被覆写；异常遗留文件需核对，不能静默覆盖。
            with target.open("x", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            entry.setdefault("versions", {})[version] = sha256_text(text)
            registry["prompts"][name] = entry
            atomic_json(self.root / "registry.json", registry)
            return {"name": name, "version": version, "sha256": sha256_text(text)}

    def save_cases(self, name: str, document: dict, expected_hash: str) -> dict:
        """更新案例必须通过结构和哈希校验，旧评测自动失效。"""
        validate_cases(document)
        with self.locked():
            if self.cases(name)[1] != expected_hash:
                raise ValueError("cases_conflict")
            atomic_json(self.case_file(name), document)
            return {"case_hash": self.cases(name)[1]}

    def run_offline(self, name: str, version: str, observations: dict) -> dict:
        """评测导入输出，明确标离线，不能伪造为真实模型执行。"""
        if not SAFE_VERSION.fullmatch(version):
            raise ValueError("prompt_version_invalid")
        detail = self.detail(name)
        candidate = next((item for item in detail["versions"] if item["version"] == version), None)
        if not candidate:
            raise KeyError("prompt_version_not_found")
        report = {"id": uuid.uuid4().hex, "name": name, "version": version, "source": "offline_import",
                  "template_hash": candidate["sha256"], "case_hash": detail["case_hash"],
                  "component_bindings": self.component_bindings(name, version),
                  "observations": observations, "judgments": {}, "usage": None,
                  "result": self.evaluate_version(name, version, detail["cases"], observations, {})}
        atomic_json(self.results / (report["id"] + ".json"), report)
        return report

    def component_bindings(self, name: str, version: str, components: list | None = None) -> dict:
        """保存本次模板与公共规则身份，不因无关提示词变化使报告失效。"""
        registry = self.registry()[0]['prompts']
        if components is None:
            names = [name]
            parent = self.cases(name)[0]['contract'].get('evaluation_parent')
            if parent:
                self.entry(parent)
                if parent == name:
                    raise ValueError('evaluation_parent_invalid')
                names.append(parent)
            if name == 'repair-executor':
                names += ['execution-base', 'worker-tool-instructions-835-1']
            components = [{'name': key, 'version': version if key == name else registry[key]['active'],
                           'template_sha256': registry[key]['versions'][version if key == name else registry[key]['active']]}
                          for key in names]
        bindings = {}
        for component in components:
            key, selected = component.get('name'), component.get('version')
            expected = registry.get(key, {}).get('versions', {}).get(selected)
            if not expected or component.get('template_sha256') != expected:
                raise ValueError('evaluation_component_invalid')
            identity = {'version': selected, 'sha256': expected}
            if key in bindings and bindings[key] != identity:
                raise ValueError('evaluation_component_conflict')
            bindings[key] = identity
        if bindings.get(name, {}).get('version') != version:
            raise ValueError('evaluation_main_component_required')
        return bindings

    def evaluation_prompt(self, name: str, version: str, document: dict, case: dict):
        """公共片段在实际消费角色下渲染，不能独立扮演完整任务角色。"""
        variables = case['input'].get('variables', document['contract'].get('variables', {}))
        if not isinstance(variables, dict):
            raise ValueError('case_variables_invalid')
        prompt = load_prompt(name, variables, self.root, version)
        parent = document['contract'].get('evaluation_parent')
        if not parent:
            return prompt
        if parent == name or not isinstance(parent, str):
            raise ValueError('evaluation_parent_invalid')
        parent_variables = case['input'].get('parent_variables', document['contract'].get('parent_variables', {}))
        if not isinstance(parent_variables, dict):
            raise ValueError('evaluation_parent_variables_invalid')
        return compose_prompts([load_prompt(parent, parent_variables, self.root), prompt])

    def record_real(self, name: str, version: str, observations: dict, budget: dict,
                    evidence: dict, judgments: dict | None = None) -> dict:
        """由受控运行器登记真实结果，HTTP接口不提供修改来源的入口。"""
        requests = budget.get('requests', [])
        used, limit = budget.get('attempts_used'), budget.get('total_limit')
        if (type(used) is not int or type(limit) is not int or used < 0 or used > limit
                or used != len(requests) or not evidence):
            raise ValueError('real_evaluation_budget_invalid')
        detail = self.detail(name)
        candidate = next((item for item in detail['versions'] if item['version'] == version), None)
        if not candidate:
            raise KeyError('prompt_version_not_found')
        unknown = sum(not isinstance(row.get('usage'), dict) or
                      type(row['usage'].get('total_tokens')) is not int for row in requests)
        # 未返回用量的真实请求保持未知，不把失败请求从统计中移除。
        report = {'id': uuid.uuid4().hex, 'name': name, 'version': version, 'source': 'real_model',
                  'template_hash': candidate['sha256'], 'case_hash': detail['case_hash'],
                  'observations': observations, 'judgments': judgments or {}, 'evidence': evidence,
                  'component_bindings': self.component_bindings(name, version, evidence.get('prompt_components'))
                      if evidence.get('prompt_components') else None,
                  'usage': {'http': used, 'http_cap': limit, 'unknown_usage': unknown,
                            'known_tokens': sum(row['usage']['total_tokens'] for row in requests
                                if isinstance(row.get('usage'), dict) and type(row['usage'].get('total_tokens')) is int)}}
        report['result'] = self.evaluate_version(name, version, detail['cases'], observations, report['judgments'])
        atomic_json(self.results / (report['id'] + '.json'), report)
        return report

    def evaluate_version(self, name: str, version: str, document: dict, observations: dict, judgments: dict) -> dict:
        """核对实际模板输入契约，人工判断不能绕过模板无法渲染。"""
        render_errors = {}
        normalized = dict(observations)
        for case in document['cases']:
            variables = case['input'].get('variables', document['contract'].get('variables', {}))
            if not isinstance(variables, dict):
                raise ValueError('case_variables_invalid')
            try:
                self.evaluation_prompt(name, version, document, case)
            except ValueError as exc:
                render_errors[case['id']] = str(exc)
                if any(check.get('path') == 'template_error' for check in case['checks']):
                    normalized[case['id']] = {'template_error': str(exc), 'text': '', 'actions': []}
        result = evaluate(document, normalized, judgments)
        for row in result['cases']:
            if row['id'] in render_errors and not any(check.get('path') == 'template_error'
                    for case in document['cases'] if case['id'] == row['id'] for check in case['checks']):
                row['status'] = 'failed'
                row['checks'].append({'status':'failed','reason':render_errors[row['id']]})
        result['blockers'] = [row['id'] for row in result['cases'] if row['level'] != 'light' and row['status'] != 'passed']
        result['activation_ready'] = not result['blockers']
        result['render_errors'] = render_errors
        return result

    def report(self, report_id: str) -> dict:
        """报告只按服务器生成的ID读取，禁止任意路径或符号链接。"""
        if not re.fullmatch(r"[a-f0-9]{32}", report_id):
            raise ValueError("evaluation_id_invalid")
        path = self.results / (report_id + ".json")
        if path.is_symlink():
            raise ValueError("evaluation_path_unsafe")
        return read_json(path)

    def list_reports(self, name: str) -> list[dict]:
        """列出本提示词的持久运行摘要，不自动展开输入和响应正文。"""
        self.entry(name)
        reports = []
        for path in sorted(self.results.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.is_symlink():
                continue
            report = read_json(path)
            if report.get("name") == name:
                reports.append({key: report.get(key) for key in ("id", "name", "version", "source", "result", "usage")})
        return reports

    def judge(self, report_id: str, case_id: str, passed: bool, reason: str) -> dict:
        """保存明确人工语义判断，不能掩盖自动检查失败。"""
        if type(passed) is not bool or not isinstance(reason, str) or not reason.strip():
            raise ValueError("judgment_invalid")
        with self.locked():
            report = self.report(report_id)
            document, digest = self.cases(report["name"])
            if digest != report["case_hash"]:
                raise ValueError("evaluation_cases_changed")
            case = next((case for case in document["cases"] if case["id"] == case_id), None)
            if not case or case_id not in report["observations"]:
                raise ValueError("observed_case_required")
            report["judgments"][case_id] = {"passed": passed, "reason": reason}
            report["result"] = self.evaluate_version(report['name'], report['version'], document, report["observations"], report["judgments"])
            atomic_json(self.results / (report_id + ".json"), report)
            return report

    def activate(self, name: str, version: str, report_id: str, expected_hash: str, confirmed: bool) -> dict:
        """用户确认且全部关键预期通过才能激活，旧会话固定绑定不变。"""
        if confirmed is not True:
            raise ValueError("activation_confirmation_required")
        with self.locked():
            report = self.report(report_id)
            document, case_hash = self.cases(name)
            entry = self.entry(name)
            registry, registry_hash = self.registry()
            if expected_hash != registry_hash:
                raise ValueError("registry_conflict")
            expected_template = entry.get("versions", {}).get(version)
            if (not expected_template or report["name"] != name or report["version"] != version
                    or report["template_hash"] != expected_template or report["case_hash"] != case_hash):
                raise ValueError("evaluation_stale")
            bindings = report.get('component_bindings')
            if not isinstance(bindings, dict) or name not in bindings:
                raise ValueError('evaluation_component_evidence_missing')
            # 主候选可以尚未激活；其公共依赖必须仍为评测时的激活身份。
            for key, identity in bindings.items():
                dependency = registry['prompts'].get(key, {})
                selected = version if key == name else dependency.get('active')
                if (identity.get('version') != selected or
                        dependency.get('versions', {}).get(selected) != identity.get('sha256')):
                    raise ValueError('evaluation_components_changed')
                self.entry(key)
                if not isinstance(selected, str) or not SAFE_VERSION.fullmatch(selected):
                    raise ValueError('evaluation_component_invalid')
                component_path = self.root / key / (selected + '.md')
                if (component_path.is_symlink() or component_path.parent.is_symlink()
                        or sha256_text(component_path.read_text()) != identity['sha256']):
                    raise ValueError('evaluation_components_changed')
            result = self.evaluate_version(name, version, document, report["observations"], report["judgments"])
            if not result["activation_ready"]:
                raise ValueError("activation_expectations_not_passed")
            # 离线导入不自动冒充真实证据，须逐项人工核对关键案例来源与语义。
            if report["source"] != "real_model" and any(case["level"] != "light" and
                    case["id"] not in report["judgments"] for case in document["cases"]):
                raise ValueError("offline_evidence_requires_manual_review")
            text = (self.root / name / f"{version}.md").read_text()
            if sha256_text(text) != expected_template:
                raise ValueError("prompt_hash_mismatch")
            entry.update(active=version, sha256=expected_template, activation_report=report_id)
            registry["prompts"][name] = entry
            atomic_json(self.root / "registry.json", registry)
            return {"name": name, "active": version, "warnings": result["warnings"]}
