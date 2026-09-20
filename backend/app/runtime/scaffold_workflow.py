"""根据正式架构生成受限、可验证且不含业务实现的代码骨架。"""

import json
from pathlib import Path
import re
import shlex
import uuid

from .contracts import ToolCall
from .prompt_registry import load_prompt


TODO_PATTERN = re.compile(r"\b(?:test|it)\s*\.\s*(?:todo|skip)\s*\(")
MAX_SCAFFOLD_ATTEMPTS = 5


def remaining_todo_files(root: Path) -> list[str]:
    """返回仍含 todo／skip 的产品测试文件，作为未实现业务账本。"""
    return [str(path.relative_to(root)) for path in sorted((root / "product").rglob("*"))
            if path.is_file() and path.name.endswith((".test.js", ".test.cjs", ".test.mjs"))
            and TODO_PATTERN.search(path.read_text(encoding="utf-8"))]


def _parse_scaffold(text: str) -> dict:
    """解析并校验 Scaffolder 的模块清单和文件边界。"""
    value = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
    if not isinstance(value, dict) or not isinstance(value.get("modules"), list) or not value["modules"]:
        raise ValueError("scaffold_modules_required")
    files = value.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("scaffold_files_invalid")
    if len(files) > 20:
        raise ValueError(f"scaffold_file_limit_exceeded:{len(files)}")
    if sum(len(content) for content in files.values() if isinstance(content, str)) > 60_000:
        raise ValueError("scaffold_content_too_large")
    required = {"product/index.html", "product/styles.css",
                "product/verify_product.py", "product/implementation.md"}
    if not required <= set(files):
        raise ValueError("scaffold_product_entries_required")
    owners: set[str] = set()
    tests: set[str] = set()
    for path, content in files.items():
        candidate = Path(path)
        if (not isinstance(content, str) or candidate.is_absolute() or ".." in candidate.parts
                or not path.startswith("product/")):
            raise ValueError("scaffold_file_invalid")
    for module in value["modules"]:
        if not isinstance(module, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{1,48}", str(module.get("id", ""))):
            raise ValueError("scaffold_module_invalid")
        implementations = module.get("implementation_files")
        interfaces = module.get("interfaces")
        test_file = module.get("test_file")
        invalid_fields = []
        if not isinstance(implementations, list) or not implementations:
            invalid_fields.append("implementation_files")
        if not isinstance(interfaces, list) or not interfaces:
            invalid_fields.append("interfaces")
        if not isinstance(test_file, str) or not test_file.endswith((".test.js", ".test.cjs", ".test.mjs")):
            invalid_fields.append("test_file")
        if invalid_fields:
            raise ValueError(f"scaffold_module_contract_invalid:{module.get('id')}:{','.join(invalid_fields)}")
        declared = implementations + [test_file]
        if any(path not in files or path in owners for path in declared):
            raise ValueError("scaffold_module_file_invalid")
        if not TODO_PATTERN.search(files[test_file]):
            raise ValueError("scaffold_module_todo_required")
        owners.update(declared)
        tests.add(test_file)
    unowned = sorted(set(files) - owners)
    if unowned:
        raise ValueError("scaffold_unowned_files:" + ",".join(unowned))
    value["test_files"] = sorted(tests)
    return value


def _stage_and_validate_scaffold(db, task, run, tools, root: Path, scaffold: dict):
    """在证据暂存区执行骨架，成功前不写入正式 product/。"""
    from . import worker as w
    stage = root / "evidence" / f"scaffold-stage-{run.id}-{uuid.uuid4().hex[:8]}"
    for path, content in scaffold["files"].items():
        destination = stage / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    for path in sorted(path for path in scaffold["files"] if path.endswith((".js", ".mjs", ".cjs"))
                       and path not in scaffold["test_files"]):
        staged_path = Path("..") / "evidence" / stage.name / path
        result = w.execute_tool(db, task, run, tools, ToolCall(f"scaffold-check-{path}", "exec",
            {"action": "run", "command": f"node --check {shlex.quote(str(staged_path))}"}),
            history_key="architecture_scaffold_validation")
        if result.status != "succeeded" or result.output.get("exit_code") != 0:
            raise ValueError(f"scaffold_javascript_invalid:{path}")
    command = "node --test " + " ".join(shlex.quote(str(Path("..") / "evidence" / stage.name / path))
                                          for path in scaffold["test_files"])
    result = w.execute_tool(db, task, run, tools, ToolCall("scaffold-tests", "exec",
        {"action": "run", "command": command}), history_key="architecture_scaffold_validation")
    stdout = result.output.get("stdout", "")
    if result.status != "succeeded" or result.output.get("exit_code") != 0:
        raise ValueError("scaffold_test_execution_failed:" + (stdout[-2000:] or result.error or "unknown"))
    if not re.search(r"(?:ℹ|#) tests [1-9]\d*", stdout):
        raise ValueError("scaffold_test_discovery_failed")
    return stage, command


def ensure_scaffold(db, task, run, tools) -> None:
    """一次生成架构骨架并执行结构、语法和测试发现验证。"""
    from . import worker as w
    root = w.workspace_for(task)
    target = root / "docs/scaffold-contract.json"
    product_hash = w.content_hash((root / "docs/product.md").read_text(encoding="utf-8"))
    architecture_hash = w.content_hash((root / "docs/architecture.md").read_text(encoding="utf-8"))
    if target.is_file():
        saved = json.loads(target.read_text(encoding="utf-8"))
        if saved.get("product_hash") == product_hash and saved.get("architecture_hash") == architecture_hash:
            return
    context = {"approved_product": (root / "docs/product.md").read_text(encoding="utf-8"),
               "project_constraints": w.FIXED_PRODUCT_CONSTRAINTS}
    feedback = None
    for attempt in range(MAX_SCAFFOLD_ATTEMPTS):
        response = w.model_tool_loop(
            db, task, run, load_prompt("architecture-scaffolder"),
            (root / "docs/architecture.md").read_text(encoding="utf-8"),
            {**context, "validation_feedback": feedback},
            tools, tool_schemas=[], history_key=f"architecture_scaffold:{attempt + 1}")
        try:
            scaffold = _parse_scaffold(response)
            stage, command = _stage_and_validate_scaffold(db, task, run, tools, root, scaffold)
            break
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            error = str(exc)
            instruction = ("只修正结构错误并返回完整 JSON；不得向用户提问。"
                           "按业务所有权合并同域 store/view，保留公共接口和逐模块 todo 测试。")
            if error == "scaffold_product_entries_required":
                instruction += (" files 必须同时包含 product/index.html、product/styles.css、"
                                "product/verify_product.py、product/implementation.md，并全部登记到 app/ui。")
            elif error == "scaffold_module_invalid":
                instruction += " module.id 必须是至少两个字符的英文小写短横线标识，且不得重复。"
            elif error.startswith("scaffold_module_contract_invalid:"):
                instruction += (" error 已给出模块 id 与缺失字段；为该模块补齐非空 interfaces、"
                                "implementation_files 和唯一 test_file，不得删除该业务模块。")
            elif error.startswith("scaffold_file_limit_exceeded:"):
                instruction += " 文件必须不超过 20 个；继续合并同一业务域实现文件，不得删除固定入口。"
            elif error.startswith("scaffold_unowned_files:"):
                instruction += " 把错误列出的每个文件登记到唯一模块；入口、样式、说明和验证脚本归 app/ui。"
            elif error.startswith(("scaffold_javascript_invalid:", "scaffold_test_execution_failed:")):
                instruction += (" 骨架必须能被 Node 实际导入并发现 todo 测试；移除顶层循环引用访问，"
                                "跨模块只保留延迟注入的接口形状，不得在模块初始化时互相求值。")
            feedback = {"error": error, "instruction": instruction}
            try:
                invalid = json.loads(response.strip().removeprefix("```json").removeprefix("```")
                                     .removesuffix("```").strip())
                # 只回传结构轮廓，不重复大段文件内容，使模型能针对上一版修正而非从零猜测。
                feedback["candidate_outline"] = {
                    "modules": [{key: module.get(key) for key in
                                 ("id", "interfaces", "implementation_files", "test_file")}
                                for module in invalid.get("modules", []) if isinstance(module, dict)],
                    "file_paths": sorted(invalid.get("files", {}))
                    if isinstance(invalid.get("files"), dict) else [],
                }
                modules = feedback["candidate_outline"]["modules"]
                merge_candidates = [module for module in modules
                                    if module.get("id") != "app-ui"
                                    and isinstance(module.get("implementation_files"), list)
                                    and len(module["implementation_files"]) > 1]
                if error.startswith("scaffold_file_limit_exceeded:") and merge_candidates:
                    targets = [f"{module['id']}:{','.join(module['implementation_files'])}"
                               for module in merge_candidates]
                    feedback["merge_candidates"] = targets
                    feedback["instruction"] += (" 明确把这些同模块实现文件合并为每模块一个文件，并同步更新 imports："
                                                + "；".join(targets) + "。")
                declared_paths = [path for module in modules
                                  for field in ("implementation_files", "test_file")
                                  for path in ([module.get(field)] if field == "test_file"
                                               else module.get(field, []))
                                  if isinstance(path, str)]
                missing_prefix = sorted(path for path in declared_paths if not path.startswith("product/"))
                if missing_prefix:
                    feedback["paths_missing_product_prefix"] = missing_prefix
                    feedback["instruction"] += (" modules 中所有 implementation_files 与 test_file 必须逐项使用"
                                                " files 的 product/ 完整键，禁止省略 product/ 前缀。")
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
    else:
        raise RuntimeError("scaffold_validation_failed")
    # 暂存验证全部通过后才发布正式骨架。
    for path, content in scaffold["files"].items():
        destination = root / path
        if destination.exists():
            raise RuntimeError(f"scaffold_file_exists:{path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    missing = w.missing_product_files(root)
    if missing:
        raise RuntimeError("scaffold_missing_product_files:" + ",".join(missing))
    contract = {"workflow": "architecture-scaffold-v1", "product_hash": product_hash,
                "architecture_hash": architecture_hash, "modules": scaffold["modules"],
                "files": sorted(scaffold["files"]), "test_files": scaffold["test_files"],
                "initial_todo_files": remaining_todo_files(root)}
    w.write_json_atomic(target, contract)
    w.safe_record_trace(db, task, run, "validation", "succeeded", "架构代码骨架验证",
                        command, contract)
    db.commit()
