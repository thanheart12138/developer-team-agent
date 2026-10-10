"""受控提示词预期判定器：离线证据和真实输出使用相同检查协议。"""
import argparse
import hashlib
import json
from pathlib import Path

LEVELS = {"important", "normal", "light"}
KINDS = {"normal", "boundary", "counterexample"}
OPS = {"equals", "contains", "not_contains", "type", "required_keys", "no_actions",
       "action_sequence", "ordered_actions", "ordered_action_paths", "allowed_tools", "manual", "source_quote", "length", "action_parameters",
       "scaffold_shape", "slice_card_shape", "nonempty_string"}


def value_at(value, path: str):
    """按规范点路径读取已保存输出，缺失字段返回空值。"""
    for key in path.split(".") if path else []:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def validate_cases(document: dict) -> None:
    """拒绝不完整契约、重复ID和可执行断言，保证预期可追溯。"""
    if not isinstance(document, dict) or not isinstance(document.get("contract"), dict):
        raise ValueError("case_contract_required")
    contract = document["contract"]
    if any(not isinstance(contract.get(key), str) or not contract[key].strip()
           for key in ("input", "output", "purpose")):
        raise ValueError("case_contract_incomplete")
    if ('evaluation_parent' in contract and (not isinstance(contract['evaluation_parent'], str)
            or not contract['evaluation_parent'])):
        raise ValueError('evaluation_parent_invalid')
    if 'parent_variables' in contract and not isinstance(contract['parent_variables'], dict):
        raise ValueError('evaluation_parent_variables_invalid')
    if 'evaluation_tools' in contract and (not isinstance(contract['evaluation_tools'], list)
            or any(not isinstance(tool, str) or not tool for tool in contract['evaluation_tools'])
            or len(set(contract['evaluation_tools'])) != len(contract['evaluation_tools'])):
        raise ValueError('evaluation_tools_invalid')
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases_required")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise ValueError("case_id_required")
        if case["id"] in seen:
            raise ValueError("case_id_duplicate")
        seen.add(case["id"])
        if case.get("level") not in LEVELS or case.get("kind") not in KINDS:
            raise ValueError("case_classification_invalid")
        if not isinstance(case.get("input"), dict):
            raise ValueError("case_input_required")
        if any(not isinstance(case.get(key), str) or not case[key].strip()
               for key in ("expected", "forbidden", "basis")):
            raise ValueError("case_expectation_incomplete")
        checks = case.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError("case_checks_required")
        for check in checks:
            if not isinstance(check, dict) or check.get("op") not in OPS:
                raise ValueError("case_check_invalid")
            if not isinstance(check.get("path", ""), str):
                raise ValueError("case_path_invalid")
            if check["op"] == "manual" and not check.get("reason"):
                raise ValueError("manual_reason_required")
            if check["op"] in {"required_keys", "action_sequence", "ordered_actions", "allowed_tools"} and (
                    not isinstance(check.get("value"), list) or any(not isinstance(item, str) for item in check["value"])):
                raise ValueError("case_check_list_required")
            if check["op"] in {"type", "contains", "not_contains"} and not isinstance(check.get("value"), str):
                raise ValueError("case_check_string_required")
            if check['op'] == 'ordered_action_paths' and (
                    not isinstance(check.get('value'), list) or not check['value']
                    or any(not isinstance(path, list) or not path
                           or any(not isinstance(item, str) or not item.strip() for item in path)
                           for path in check['value'])):
                raise ValueError('case_check_action_paths_invalid')
            if check["op"] == "equals" and "value" not in check:
                raise ValueError("case_check_value_required")
            if check['op'] == 'length' and (type(check.get('value')) is not int or check['value'] < 0):
                raise ValueError('case_check_length_invalid')
            if check['op'] == 'action_parameters' and (not isinstance(check.get('tool'), str)
                    or not check['tool'] or not isinstance(check.get('value'), dict)):
                raise ValueError('case_check_parameters_invalid')


def check_output(check: dict, observation: dict, case: dict, judgment: dict | None) -> dict:
    """逐项执行受控检查，人工结论只影响人工项，不能覆盖程序失败。"""
    op = check["op"]
    value = value_at(observation, check.get("path", ""))
    expected = check.get("value")
    if op == "manual":
        if not judgment or type(judgment.get("passed")) is not bool or not judgment.get("reason"):
            return {"status": "pending", "reason": check["reason"]}
        passed = judgment["passed"]
    elif op == "equals":
        passed = type(value) is type(expected) and value == expected
    elif op == 'nonempty_string':
        # 与决策工具运行时契约一致，空白问题不能代表已请求有效产品决定。
        passed = isinstance(value, str) and bool(value.strip())
    elif op == 'length':
        passed = isinstance(value, (str, list, dict)) and len(value) == expected
    elif op == 'scaffold_shape':
        # 复用真实结构门禁，不执行模型生成代码；语义与实际导入仍需其他证据。
        from .scaffold_workflow import _parse_scaffold
        try:
            scaffold = _parse_scaffold(json.dumps(value, ensure_ascii=False))
            identifiers = [module['id'] for module in scaffold['modules']]
            passed = len(identifiers) <= 8 and len(set(identifiers)) == len(identifiers)
        except (ValueError, KeyError, TypeError):
            passed = False
    elif op == 'slice_card_shape':
        # 校验卡片自身结构；跨模块依赖与用户行为是否交付仍须逐项核对。
        from .slice_workflow import validate_card
        try:
            validate_card(value, set(case['input'].get('context', {}).get('completed_ids', [])))
            passed = True
        except (ValueError, KeyError, TypeError):
            passed = False
    elif op == 'action_parameters':
        # 安全停止时允许无动作；若调用指定工具，字段必须严格匹配授权。
        actions = observation.get('actions', [])
        passed = isinstance(actions, list)
        for action in actions if passed else []:
            if not isinstance(action, dict):
                passed = False
            elif action.get('tool_name') == check['tool']:
                parameters = action.get('parameters', {})
                if not isinstance(parameters, dict) or any(type(parameters.get(key)) is not type(wanted)
                        or parameters.get(key) != wanted for key, wanted in expected.items()):
                    passed = False
    elif op == "contains":
        passed = isinstance(value, (str, list, dict)) and expected in value
    elif op == "not_contains":
        passed = isinstance(value, (str, list, dict)) and expected not in value
    elif op == "type":
        passed = type(value).__name__ == expected
    elif op == "required_keys":
        passed = isinstance(value, dict) and isinstance(expected, list) and set(expected) <= set(value)
    elif op == "no_actions":
        passed = observation.get("actions") == []
    elif op in {"action_sequence", "ordered_actions", "ordered_action_paths", "allowed_tools"}:
        actions = observation.get("trajectory", observation.get("actions", []))
        # 损坏的动作不得静默丢弃，否则空白名单或子序列可能误判通过。
        valid = isinstance(actions, list) and all(isinstance(action, dict)
            and isinstance(action.get('tool_name'), str) and bool(action['tool_name']) for action in actions)
        names = [action['tool_name'] for action in actions] if valid else []
        if op in {"ordered_actions", "ordered_action_paths"}:
            # 允许必要调查穿插，但不能调换关键交付动作的先后次序。
            passed = False
            for path in expected if op == 'ordered_action_paths' else [expected]:
                cursor = 0
                for name in names:
                    if cursor < len(path) and name == path[cursor]:
                        cursor += 1
                passed = passed or cursor == len(path)
        else:
            passed = names == expected if op == "action_sequence" else isinstance(expected, list) and all(name in expected for name in names)
        passed = valid and passed
    elif op == "source_quote":
        source = value_at(case["input"], check.get("source", ""))
        passed = isinstance(source, str) and isinstance(value, str) and bool(value) and value in source
    return {"status": "passed" if passed else "failed", "op": op, "path": check.get("path", ""),
            "reason": (judgment or {}).get("reason", "") if op == "manual" else f"{op}:{check.get('path', '')}"}


def evaluate(document: dict, observations: dict, judgments: dict | None = None) -> dict:
    """生成逐例报告，缺响应不算通过，关键案例不完整时阻止激活。"""
    validate_cases(document)
    if not isinstance(observations, dict):
        raise ValueError("observations_invalid")
    rows = []
    for case in document["cases"]:
        observation = observations.get(case["id"])
        checks = []
        if observation is None:
            status = "not_run"
        elif not isinstance(observation, dict):
            status = "failed"
            checks = [{"status": "failed", "reason": "observation_invalid"}]
        elif observation.get('complete') is False:
            # 首批行为不能代替完整业务预期，人工通过也不能补出未执行证据。
            status = 'pending'
            checks = [{'status': 'pending', 'reason': 'observation_incomplete'}]
        else:
            observation = dict(observation)
            if "output" not in observation and isinstance(observation.get("text"), str):
                try:
                    observation["output"] = json.loads(observation["text"])
                except json.JSONDecodeError:
                    pass
            checks = [check_output(check, observation, case, (judgments or {}).get(case["id"])) for check in case["checks"]]
            status = "failed" if any(item["status"] == "failed" for item in checks) else (
                "pending" if any(item["status"] == "pending" for item in checks) else "passed")
            if (judgments or {}).get(case["id"], {}).get("passed") is False:
                status = "failed"
        rows.append({"id": case["id"], "level": case["level"], "kind": case["kind"],
                     "expected": case["expected"], "basis": case["basis"],
                     "forbidden": case["forbidden"], "status": status, "checks": checks})
    blockers = [row["id"] for row in rows if row["level"] != "light" and row["status"] != "passed"]
    return {"cases": rows, "activation_ready": not blockers, "blockers": blockers,
            "warnings": [row["id"] for row in rows if row["level"] == "light" and row["status"] != "passed"]}


def main() -> None:
    """离线评测命令只读输入，打印结果并返回可检查退出码。"""
    parser = argparse.ArgumentParser(description="提示词离线预期评测")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--judgments", type=Path)
    parser.add_argument("--prompt", help="显式绑定已注册模板名称")
    parser.add_argument("--version", help="与模板名称一起指定固定版本")
    args = parser.parse_args()
    if bool(args.prompt) != bool(args.version):
        parser.error('--prompt and --version must be provided together')
    # 先固定实际输入字节，再解析；无显式模板绑定时不得宣称版本已验证。
    inputs = {key: path.read_bytes() for key, path in
              [('cases', args.cases), ('observations', args.observations), ('judgments', args.judgments)] if path}
    document = json.loads(inputs['cases'])
    observations = json.loads(inputs['observations'])
    judgments = json.loads(inputs['judgments']) if 'judgments' in inputs else {}
    binding = None
    if args.prompt:
        # 复用平台的渲染门禁，但不创建报告、版本或执行工具。
        from .prompt_management import PromptStore
        store = PromptStore()
        result = store.evaluate_version(args.prompt, args.version, document, observations, judgments)
        binding = {'name': args.prompt, 'version': args.version, 'cases': [
            {'id': case['id'], 'components': list(store.evaluation_prompt(
                args.prompt, args.version, document, case).components)} for case in document['cases']]
            } if not result['render_errors'] else {'name': args.prompt, 'version': args.version, 'render_valid': False}
    else:
        result = evaluate(document, observations, judgments)
    print(json.dumps({"source": "offline", "template_binding": binding,
        "input_hashes": {key: hashlib.sha256(value).hexdigest() for key, value in inputs.items()},
        **result}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["activation_ready"] else 1)


if __name__ == "__main__":
    main()
