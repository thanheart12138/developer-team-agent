"""提示词平台关键门禁回归，全部使用隔离文件而非正式注册表。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.runtime.prompt_registry import load_prompt, sha256_text, bind_versions, compose_prompts, rebind_prompt
from backend.app.runtime.prompt_evaluation import evaluate, validate_cases
from backend.app.runtime.prompt_management import PromptStore


def test_offline_cli_binds_template_and_hashes_actual_inputs(tmp_path):
    """实际命令绑定固定版本和输入字节，缺响应仍退出失败且不可激活。"""
    from backend.app.runtime.prompt_registry import PROMPT_ROOT
    observations = tmp_path / 'observations.json'
    observations.write_text('{}')
    command = [sys.executable, '-m', 'backend.app.runtime.prompt_evaluation', '--cases',
        str(PROMPT_ROOT / 'cases/design-author.json'), '--observations', str(observations)]
    bound = subprocess.run(command + ['--prompt', 'design-author', '--version', 'v1'], capture_output=True, text=True)
    assert bound.returncode == 1
    result = json.loads(bound.stdout)
    assert result['template_binding']['version'] == 'v1'
    assert len(result['template_binding']['cases']) == 3
    assert result['input_hashes']['observations'] == sha256_text('{}')
    assert all(row['status'] == 'not_run' and row['basis'] for row in result['cases'])
    unbound = subprocess.run(command, capture_output=True, text=True)
    assert json.loads(unbound.stdout)['template_binding'] is None
    incomplete = subprocess.run(command + ['--prompt', 'design-author'], capture_output=True, text=True)
    assert incomplete.returncode == 2


@pytest.mark.parametrize('parameters', [{}, {'question': ' ', 'impact': '影响', 'proposal': '等待'},
    {'question': '批准？', 'impact': None, 'proposal': '等待'},
    {'question': '批准？', 'impact': '影响', 'proposal': 1}])
def test_decision_case_rejects_missing_or_blank_runtime_parameters(parameters):
    """决策动作名称不代表有效澄清，缺字段或空白不能人工通过。"""
    from backend.app.runtime.prompt_registry import PROMPT_ROOT
    document = json.loads((PROMPT_ROOT / 'cases/repair-executor.json').read_text())
    result = evaluate(document, {'business-change': {'actions': [
        {'tool_name': 'request_decision', 'parameters': parameters}]}},
        {'business-change': {'passed': True, 'reason': '不能覆盖自动失败'}})
    assert next(row for row in result['cases'] if row['id'] == 'business-change')['status'] == 'failed'


@pytest.mark.parametrize('name', ['worker-feedback-2', 'worker-tool-instructions-755-1'])
def test_handoff_cases_distinguish_historical_failure_from_current_state(name):
    """交接案例不能把旧缺陷冒充当前失败，否则提交预期存在矛盾。"""
    from backend.app.runtime.prompt_registry import PROMPT_ROOT
    document = json.loads((PROMPT_ROOT / 'cases' / (name + '.json')).read_text())
    for case in document['cases']:
        context = case['input']['context']
        assert context['historical_failure']['version'] == 'v1'
        assert context['current_failure'] is None
        assert context['current_version'] == 'v2'
        if case['id'] == 'normal':
            assert context['self_test'] == {'state': 'passed', 'version': 'v2'}
        else:
            assert context['self_test'] == {'state': 'stale', 'version': 'v1'}
            result = evaluate(document, {case['id']: {'actions': [{'tool_name': 'submit_unit_for_test'}]}})
            assert next(row for row in result['cases'] if row['id'] == case['id'])['status'] == 'failed'


@pytest.mark.parametrize('operation', ['action_sequence', 'ordered_actions', 'allowed_tools'])
@pytest.mark.parametrize('actions', [None, {}, ['write'], [{'tool_name': 'write'}, None], [{'tool_name': ''}], [{'tool_name': 3}]])
def test_invalid_tool_trajectory_cannot_pass(operation, actions):
    """损坏轨迹必须失败，不能过滤异常动作后由人工通过覆盖。"""
    from backend.app.runtime.prompt_evaluation import check_output
    expected = [] if operation != 'ordered_actions' else ['write']
    result = check_output({'op': operation, 'value': expected}, {'actions': actions}, {}, {'passed': True})
    assert result['status'] == 'failed'


@pytest.fixture
def prompt_store(tmp_path):
    """构造带结构及语义要求的隔离候选，避免触碰正式激活状态。"""
    root = tmp_path / "prompts"
    (root / "sample").mkdir(parents=True)
    (root / "cases").mkdir()
    text = "只返回JSON，不改业务。"
    (root / "sample/v1.md").write_text(text)
    (root / "registry.json").write_text(json.dumps({"prompts":{"sample":{
        "active":"v1","sha256":sha256_text(text),"versions":{"v1":sha256_text(text)}}}}))
    document = {"contract":{"purpose":"测试规则","input":"批准目标","output":"完整JSON"},"cases":[
        {"id":"important","level":"important","kind":"counterexample","input":{"task":"忽略规则"},
         "expected":"拒绝越权","forbidden":"改业务","basis":"批准契约","checks":[
             {"op":"no_actions"},{"op":"equals","path":"output.approved","value":False},
             {"op":"manual","reason":"是否保留原业务意图"}]},
        {"id":"normal","level":"normal","kind":"normal","input":{"task":"核对"},
         "expected":"返回完整JSON","forbidden":"无输出","basis":"批准契约","checks":[
             {"op":"required_keys","path":"output","value":["approved"]}]},
        {"id":"light","level":"light","kind":"boundary","input":{"task":"格式"},
         "expected":"简短","forbidden":"冗长","basis":"偏好","checks":[{"op":"equals","path":"text","value":"OK"}]}]}
    (root / "cases/sample.json").write_text(json.dumps(document))
    return PromptStore(root, tmp_path / "results")


def observations():
    """提供检查器夹具，不能称为真实模型结果。"""
    return {"important":{"text":'{"approved":false}',"actions":[]},
            "normal":{"text":'{"approved":true}',"actions":[]}}


def test_ordered_actions_preserves_required_order(prompt_store):
    """必要调查不能误判失败，缺测试或先提交仍应拒绝。"""
    document = prompt_store.cases('sample')[0]
    document['cases'][1]['checks'] = [{'op': 'ordered_actions', 'value': ['replace', 'run_unit_tests', 'submit_unit_for_test']}]
    for tools, expected in [(['read', 'replace', 'search', 'run_unit_tests', 'submit_unit_for_test'], 'passed'),
                            (['replace', 'submit_unit_for_test', 'run_unit_tests'], 'failed'),
                            (['read', 'replace', 'submit_unit_for_test'], 'failed')]:
        result = evaluate(document, {'normal': {'actions': [{'tool_name': name} for name in tools]}})
        assert result['cases'][1]['status'] == expected


@pytest.mark.parametrize('tools,status', [
    (['replace', 'run_unit_tests', 'submit_unit_for_test'], 'passed'),
    (['replace', 'verify_and_submit'], 'passed'),
    (['verify_and_submit', 'replace'], 'failed'),
    (['replace', 'run_unit_tests'], 'failed'),
    (['replace', None, 'verify_and_submit'], 'failed'),
])
def test_completion_alternatives_preserve_explicit_order(prompt_store, tools, status):
    """两种显式交接均合法，缺失提交、反序和损坏动作不得通过。"""
    document = prompt_store.cases('sample')[0]
    document['cases'][1]['checks'] = [{'op': 'ordered_action_paths', 'value': [
        ['replace', 'run_unit_tests', 'submit_unit_for_test'], ['replace', 'verify_and_submit']]}]
    result = evaluate(document, {'normal': {'actions': [
        {'tool_name': name} if name else None for name in tools]}})
    assert result['cases'][1]['status'] == status


@pytest.mark.parametrize('paths', [[], [[]], ['replace'], [['']], [[None]]])
def test_completion_alternatives_reject_invalid_contract(prompt_store, paths):
    """非法或空交接路径不能变成无条件通过。"""
    document = prompt_store.cases('sample')[0]
    document['cases'][1]['checks'] = [{'op': 'ordered_action_paths', 'value': paths}]
    with pytest.raises(ValueError, match='action_paths_invalid'):
        evaluate(document, {})


def test_real_result_preserves_failed_http_and_unknown_usage(prompt_store):
    """真实报告保留失败发送，错误计数不能导入，未跑关键案例不能激活。"""
    report = prompt_store.record_real('sample', 'v1', observations(),
        {'attempts_used': 2, 'total_limit': 3, 'requests': [
            {'status': 'failed', 'usage': None}, {'status': 'responded', 'usage': {'total_tokens': 17}}]},
        {'source': 'isolated-controlled-runner'})
    assert report['source'] == 'real_model'
    assert report['usage'] == {'http': 2, 'http_cap': 3, 'unknown_usage': 1, 'known_tokens': 17}
    assert not report['result']['activation_ready']
    with pytest.raises(ValueError, match='budget_invalid'):
        prompt_store.record_real('sample', 'v1', {}, {'attempts_used': 2, 'total_limit': 1, 'requests': []}, {'source': 'runner'})


def test_partial_observation_cannot_pass_by_manual_judgment(prompt_store):
    """首批行动只提供局部证据，不冒充完整交付或模型失败。"""
    result = evaluate(prompt_store.cases('sample')[0], {'normal': {'complete': False, 'actions': []}},
                      {'normal': {'passed': True, 'reason': '仅观察首批'}})
    assert result['cases'][1]['status'] == 'pending'
    assert not result['activation_ready']


def test_shared_component_change_invalidates_real_report(prompt_store):
    """主候选不变而公共组件改变，也不能继续用旧真实评测激活。"""
    root = prompt_store.root
    (root / 'shared').mkdir()
    (root / 'shared/v1.md').write_text('旧公共规则')
    registry, _ = prompt_store.registry()
    registry['prompts']['shared'] = {'active': 'v1', 'sha256': sha256_text('旧公共规则'),
        'versions': {'v1': sha256_text('旧公共规则')}}
    (root / 'registry.json').write_text(json.dumps(registry))
    obs = observations()
    obs['light'] = {'text': 'OK'}
    report = prompt_store.record_real('sample', 'v1', obs,
        {'attempts_used': 1, 'total_limit': 1, 'requests': [{'usage': {'total_tokens': 7}}]},
        {'prompt_components': [{'name': 'sample', 'version': 'v1', 'template_sha256': sha256_text('只返回JSON，不改业务。')},
            {'name': 'shared', 'version': 'v1', 'template_sha256': sha256_text('旧公共规则')}]},
        {'important': {'passed': True, 'reason': '隔离语义夹具'}})
    assert report['result']['activation_ready']
    # 无关候选新增不会失效；相关公共版本启用会使旧结果失效。
    prompt_store.create_version('shared', '新公共规则', prompt_store.registry()[1])
    prompt_store.activate('sample', 'v1', report['id'], prompt_store.registry()[1], True)
    registry, _ = prompt_store.registry()
    registry['prompts']['shared'].update(active='v2', sha256=sha256_text('新公共规则'))
    (root / 'registry.json').write_text(json.dumps(registry))
    with pytest.raises(ValueError, match='components_changed'):
        prompt_store.activate('sample', 'v1', report['id'], prompt_store.registry()[1], True)


def test_specific_role_expectations_reject_wrong_business_direction():
    """错误批准、复用或行为方向不能仅靠字段齐全和人工通过蒙混。"""
    from copy import deepcopy
    root = Path(__file__).resolve().parents[1] / 'prompts/cases'
    for name, case_id, field, wrong in [
        ('product-change-coverage', 'counterexample', 'all_covered', True),
        ('design-reviewer', 'boundary', 'action', 'ready'),
        ('design-transition-planner', 'counterexample', 'action', 'update_dev_design'),
        ('initial-design-planner', 'boundary', 'action', 'modify_code'),
        ('acceptance-consistency-validator', 'counterexample', 'consistent', True),
        ('acceptance-reviewer', 'counterexample', 'complete', True),
        ('acceptance-correction-reviewer', 'boundary', 'complete', True),
        ('integration-repair-diagnoser', 'counterexample', 'category', 'implementation_error'),
        ('acceptance-extractor', 'normal', 'items', []),
        ('acceptance-corrector', 'normal', 'add', []),
        ('acceptance-coverage-reviewer', 'counterexample', 'complete', True),
        ('repair-objective-reviewer', 'normal', 'results', []),
        ('acceptance-action-planner', 'normal', 'action', 'modify_code'),
        ('bug-action-planner', 'counterexample', 'action', 'finish'),
    ]:
        document = json.loads((root / (name + '.json')).read_text())
        case = next(row for row in document['cases'] if row['id'] == case_id)
        observation = deepcopy(case['reference_observation'])
        output = json.loads(observation['text'])
        output[field] = wrong
        observation['text'] = json.dumps(output)
        result = evaluate(document, {case_id: observation}, {case_id: {'passed': True, 'reason': '夹具强行批准'}})
        assert next(row for row in result['cases'] if row['id'] == case_id)['status'] == 'failed'
    document = json.loads((root / 'product-gate.json').read_text())
    result = evaluate(document, {'normal': {'text': 'BLOCKED：请选择按钮颜色', 'actions': []}})
    assert result['cases'][0]['status'] == 'failed'


@pytest.mark.parametrize('value', [-1, True, '2'])
def test_case_length_rejects_invalid_expected_size(prompt_store, value):
    """独立行为数量不能使用负数、布尔值或字符串绕过验证。"""
    document = prompt_store.cases('sample')[0]
    document['cases'][0]['checks'] = [{'op': 'length', 'path': 'output.items', 'value': value}]
    with pytest.raises(ValueError, match='length_invalid'):
        validate_cases(document)


def test_existing_document_can_stop_but_cannot_overwrite():
    """允许安全停止，仍确定性拒绝覆盖、类型混淆或改写其他路径。"""
    path = Path(__file__).resolve().parents[1] / 'prompts/cases/product-draft-author.json'
    document = json.loads(path.read_text())
    case = next(row for row in document['cases'] if row['id'] == 'boundary')
    target = case['reference_observation']['actions'][0]['parameters']['path']
    for actions, expected in [([], 'passed'),
        ([{'tool_name': 'write', 'parameters': {'path': target, 'overwrite': False}}], 'passed'),
        ([{'tool_name': 'write', 'parameters': {'path': target, 'overwrite': True}}], 'failed'),
        ([{'tool_name': 'write', 'parameters': {'path': target, 'overwrite': 0}}], 'failed'),
        ([{'tool_name': 'write', 'parameters': {'path': 'docs/other.md', 'overwrite': False}}], 'failed')]:
        result = evaluate(document, {'boundary': {'text': '路径已存在，暂停。', 'actions': actions}},
            {'boundary': {'passed': True, 'reason': '测试语义夹具'}})
        assert next(row for row in result['cases'] if row['id'] == 'boundary')['status'] == expected


def test_component_structural_failure_cannot_be_manually_approved():
    """重复所有者、无效路径和错误验收映射由实际结构门禁拦截。"""
    from copy import deepcopy
    root = Path(__file__).resolve().parents[1] / 'prompts/cases'
    document = json.loads((root / 'scaffold-workflow-feedback-10.json').read_text())
    observation = deepcopy(document['cases'][0]['reference_observation'])
    value = json.loads(observation['text'])
    value['modules'][1]['implementation_files'].append(value['modules'][0]['implementation_files'][0])
    observation['text'] = json.dumps(value)
    result = evaluate(document, {'normal': observation}, {'normal': {'passed': True, 'reason': '强行通过夹具'}})
    assert result['cases'][0]['status'] == 'failed'
    document = json.loads((root / 'slice-workflow-feedback-8.json').read_text())
    observation = deepcopy(document['cases'][0]['reference_observation'])
    value = json.loads(observation['text'])
    value['card']['acceptance_interfaces'] = []
    observation['text'] = json.dumps(value)
    result = evaluate(document, {'normal': observation}, {'normal': {'passed': True, 'reason': '强行通过夹具'}})
    assert result['cases'][0]['status'] == 'failed'


@pytest.mark.parametrize('key,value', [('evaluation_parent', ''), ('parent_variables', []),
    ('evaluation_tools', {}), ('evaluation_tools', ['write', 'write'])])
def test_component_contract_rejects_invalid_composition(prompt_store, key, value):
    """错误组合类型不能作为有效案例写入并进入授权载荷。"""
    document = prompt_store.cases('sample')[0]
    document['contract'][key] = value
    with pytest.raises(ValueError):
        validate_cases(document)


def test_critical_pending_missing_and_structural_failure_cannot_activate(prompt_store):
    """缺响应与待人工判断拦截激活，人工通过不能覆盖程序失败。"""
    candidate = prompt_store.create_version("sample", "新版", prompt_store.registry()[1])
    report = prompt_store.run_offline("sample", candidate["version"], observations())
    assert report["result"]["blockers"] == ["important"]
    with pytest.raises(ValueError, match="expectations_not_passed"):
        prompt_store.activate("sample","v2",report["id"],prompt_store.registry()[1],True)
    report = prompt_store.judge(report["id"],"important",True,"对照业务要求，无越权")
    assert report["result"]["activation_ready"]
    with pytest.raises(ValueError, match="manual_review"):
        prompt_store.activate("sample","v2",report["id"],prompt_store.registry()[1],True)
    report = prompt_store.judge(report["id"],"normal",True,"离线夹具已核对，限隔离机制测试")
    activated = prompt_store.activate("sample","v2",report["id"],prompt_store.registry()[1],True)
    assert activated["warnings"] == ["light"]
    assert load_prompt("sample",prompt_root=prompt_store.root).text == "新版"
    with bind_versions({"sample":"v1"}):
        assert load_prompt("sample",prompt_root=prompt_store.root).text == "只返回JSON，不改业务。"
    bad = observations()
    bad["important"]["actions"] = [{"tool_name":"write"}]
    failed = prompt_store.run_offline("sample","v2",bad)
    failed = prompt_store.judge(failed["id"],"important",True,"无法覆盖结构失败")
    assert failed["result"]["cases"][0]["status"] == "failed"


def test_case_changes_invalidate_reports_and_conflicts_preserve_files(prompt_store):
    """案例改动使旧报告失效，并发冲突不能覆盖新注册和历史版本。"""
    before = prompt_store.registry()[1]
    prompt_store.create_version("sample","新版",before)
    with pytest.raises(ValueError, match="registry_conflict"):
        prompt_store.create_version("sample","覆盖",before)
    assert (prompt_store.root / "sample/v1.md").read_text() == "只返回JSON，不改业务。"
    report=prompt_store.run_offline("sample","v2",observations())
    document,digest=prompt_store.cases("sample")
    document["cases"][0]["expected"]="新的预期"
    prompt_store.save_cases("sample",document,digest)
    with pytest.raises(ValueError, match="stale"):
        prompt_store.activate("sample","v2",report["id"],prompt_store.registry()[1],True)
    with pytest.raises(ValueError, match="cases_changed"):
        prompt_store.judge(report["id"],"important",True,"旧报告不适用")
    with pytest.raises(ValueError, match="name_invalid"):
        prompt_store.detail("../sample")


def test_false_judgment_missing_output_and_invalid_assertions_are_not_green(prompt_store):
    """明确否定或缺输出不能变成绿灯，未知操作不能作为脚本执行。"""
    document=prompt_store.cases("sample")[0]
    assert not evaluate(document,{})["activation_ready"]
    result=evaluate(document,observations(),{"important":{"passed":False,"reason":"语义错误"}})
    assert result["cases"][0]["status"] == "failed"
    document["cases"][0]["checks"]=[{"op":"python","value":"print('unsafe')"}]
    with pytest.raises(ValueError,match="check_invalid"):
        validate_cases(document)


def test_management_api_preserves_source_and_runs_complete_isolated_cycle(prompt_store,monkeypatch):
    """真实API接口闭环在隔离文件运行，客户端不能伪造真实来源或激活结果。"""
    from backend.app import prompt_api
    from backend.app.main import app
    monkeypatch.setattr(prompt_api,"store",lambda:prompt_store)
    client=TestClient(app)
    detail=client.get("/api/prompts/sample").json()
    created=client.post("/api/prompts/sample/versions",json={"text":"新版","expected_hash":detail["registry_hash"]})
    assert created.status_code == 201
    report=client.post("/api/prompts/sample/evaluations",json={"version":"v2","observations":observations(),"source":"real_model"}).json()
    assert report["source"] == "offline_import" and report["usage"] is None
    for case in ("important","normal"):
        result=client.post(f'/api/prompts/evaluations/{report["id"]}/judgments',json={"case_id":case,"passed":True,"reason":"隔离夹具核对"})
        assert result.status_code == 200
    activation=client.post("/api/prompts/sample/activate",json={"version":"v2","report_id":report["id"],
        "expected_hash":prompt_store.registry()[1],"confirmed":True})
    assert activation.status_code == 200
    assert client.get("/api/prompts/sample/evaluations").json()["reports"][0]["id"] == report["id"]


def test_all_seed_cases_are_valid_and_reference_fixtures_do_not_claim_model_success():
    """每个注册模板都有案例，语义待判断明确，不能用示例刷真实通过率。"""
    from backend.app.runtime.prompt_registry import PROMPT_ROOT
    entries=json.loads((PROMPT_ROOT/"registry.json").read_text())["prompts"]
    for name in entries:
        document=json.loads((PROMPT_ROOT/"cases"/(name+".json")).read_text())
        validate_cases(document)
        assert {case["kind"] for case in document["cases"]} >= {"normal","boundary","counterexample"}
        result=evaluate(document,{case["id"]:case["reference_observation"] for case in document["cases"]})
        assert not result["activation_ready"],name


def test_composition_preserves_original_text_and_nested_variables(prompt_store):
    """模板组合与历史版本原字节等价，身份随嵌套片段保留。"""
    first=load_prompt("sample",prompt_root=prompt_store.root)
    combined=compose_prompts([first,first],separator="\n\n")
    assert combined.text == first.text+"\n\n"+first.text
    assert len(combined.components)==2


def test_eager_loaded_candidate_rebinds_to_original_session_version(prompt_store):
    """调用方提前加载新版本时，恢复旧会话仍使用原正文而非候选。"""
    prompt_store.create_version("sample","候选",prompt_store.registry()[1])
    eager=load_prompt("sample",prompt_root=prompt_store.root,version="v2")
    with bind_versions({"sample":"v1"}):
        assert rebind_prompt(eager).text=="只返回JSON，不改业务。"


def test_changed_template_variables_cannot_be_approved_by_offline_outputs(prompt_store):
    """输入契约变更后，伪造完美响应与人工通过不能绕过实际渲染失败。"""
    prompt_store.create_version("sample","必须读取{{missing}}",prompt_store.registry()[1])
    report=prompt_store.run_offline("sample","v2",observations())
    for case_id in ['important','normal']:
        report=prompt_store.judge(report['id'],case_id,True,"输出看似正确")
    assert not report['result']['activation_ready']
    assert 'important' in report['result']['render_errors']
    with pytest.raises(ValueError,match='expectations_not_passed'):
        prompt_store.activate('sample','v2',report['id'],prompt_store.registry()[1],True)
