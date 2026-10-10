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
            raise ValueError(f"scaffold_file_invalid:{path}")
    for module in value["modules"]:
        if not isinstance(module, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{1,48}", str(module.get("id", ""))):
            raise ValueError("scaffold_module_invalid")
        implementations = module.get("implementation_files")
        interfaces = module.get("interfaces")
        test_file = module.get("test_file")
        if (not isinstance(implementations, list) or not implementations
                or not isinstance(interfaces, list) or not interfaces
                or not isinstance(test_file, str) or not test_file.endswith((".test.js", ".test.cjs", ".test.mjs"))):
            raise ValueError("scaffold_module_contract_invalid")
        declared = implementations + [test_file]
        # 模块声明必须逐字匹配文件清单，错误中保留具体模块和路径供模型纠正。
        for path in declared:
            if path not in files:
                raise ValueError(f"scaffold_module_file_missing:{module['id']}:{path}")
            if path in owners:
                raise ValueError(f"scaffold_module_file_duplicate:{path}")
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
            instruction = (load_prompt('scaffold-workflow-feedback-1').text)
            if error == "scaffold_product_entries_required":
                instruction += (load_prompt('scaffold-workflow-feedback-2').text)
            elif error.startswith("scaffold_file_invalid:"):
                instruction += (load_prompt('scaffold-workflow-feedback-3').text + error.split(":", 1)[1]
                                + load_prompt('scaffold-workflow-feedback-4').text)
            elif error.startswith("scaffold_module_file_missing:"):
                _, module_id, path = error.split(":", 2)
                expected = path if path.startswith("product/") else "product/" + path
                instruction += (load_prompt('scaffold-workflow-feedback-5').text + module_id + load_prompt('scaffold-workflow-feedback-6').text + path
                                + load_prompt('scaffold-workflow-feedback-7').text + expected
                                + load_prompt('scaffold-workflow-feedback-8').text)
            elif error.startswith("scaffold_module_file_duplicate:"):
                instruction += (load_prompt('scaffold-workflow-feedback-9').text + error.split(":", 1)[1] + load_prompt('scaffold-workflow-feedback-10').text)
            elif error == "scaffold_module_invalid":
                instruction += load_prompt('scaffold-workflow-feedback-11').text
            elif error.startswith("scaffold_file_limit_exceeded:"):
                instruction += load_prompt('scaffold-workflow-feedback-12').text
            elif error.startswith("scaffold_unowned_files:"):
                instruction += load_prompt('scaffold-workflow-feedback-13').text
            elif error.startswith(("scaffold_javascript_invalid:", "scaffold_test_execution_failed:")):
                instruction += (load_prompt('scaffold-workflow-feedback-14').text)
            feedback = {"error": error, "instruction": instruction}
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
