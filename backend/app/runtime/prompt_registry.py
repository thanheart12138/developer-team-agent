"""从项目提示词注册表加载并校验不可变版本。"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import ast
from contextlib import contextmanager
from contextvars import ContextVar


PROMPT_ROOT = Path(__file__).resolve().parents[3] / "prompts"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SAFE_VERSION = re.compile(r"^v[1-9][0-9]*$")
PLACEHOLDER = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")
BOUND_VERSIONS = ContextVar("prompt_bound_versions", default={})


def active_versions(prompt_root: Path | None = None) -> dict:
    """获取当前激活快照，供会话绑定而非每轮隐式切换。"""
    root = prompt_root or PROMPT_ROOT
    entries = json.loads((root / "registry.json").read_text())["prompts"]
    return {name: entry["active"] for name, entry in entries.items()}


@contextmanager
def bind_versions(versions: dict):
    """在当前调用范围绑定固定版本，不污染其他任务的加载。"""
    token = BOUND_VERSIONS.set(versions)
    try:
        yield
    finally:
        BOUND_VERSIONS.reset(token)


@dataclass(frozen=True)
class PromptContent:
    """保存一次已校验和渲染的提示词及其可审计身份。"""

    name: str
    version: str
    text: str
    template_sha256: str
    rendered_sha256: str
    components: tuple[dict, ...] = ()
    variables: dict = field(default_factory=dict, repr=False, compare=False)
    parts: tuple = field(default=(), repr=False, compare=False)
    separator: str = field(default="", repr=False, compare=False)
    source_root: Path | None = field(default=None, repr=False, compare=False)

    def __str__(self) -> str:
        """在日志和测试替身需要文本时返回渲染后的正文。"""
        return self.text

    def __contains__(self, value: str) -> bool:
        """保持既有调用测试对提示词正文的成员检查兼容。"""
        return value in self.text

    def __add__(self, other):
        """保留连续指令片段的版本身份，不改变原拼接字节。"""
        return compose_prompts([self, other], separator="")

    def __radd__(self, other):
        """支持既有字符串前缀与注册片段的等价拼接。"""
        return compose_prompts([other, self], separator="")


def compose_prompts(parts: list, separator: str = "\n\n") -> PromptContent:
    """组合模板正文与身份，嵌套片段也保留来源。"""
    text = separator.join(str(part) for part in parts)
    components = tuple(component for part in parts if isinstance(part, PromptContent)
                       for component in part.components)
    identity = json.dumps(components, ensure_ascii=False, sort_keys=True)
    return PromptContent("composition", "v1", text, sha256_text(identity), sha256_text(text), components,
                         parts=tuple(parts), separator=separator)


def rebind_prompt(prompt):
    """按会话版本重新渲染当前变量，防止加载早于绑定而误用新模板。"""
    if not isinstance(prompt, PromptContent):
        return prompt
    if prompt.parts:
        return compose_prompts([rebind_prompt(part) for part in prompt.parts], prompt.separator)
    variables = {key: rebind_prompt(value) for key, value in prompt.variables.items()}
    return load_prompt(prompt.name, variables, prompt.source_root,
                       version=BOUND_VERSIONS.get().get(prompt.name, prompt.version))


def sha256_text(value: str) -> str:
    """计算 UTF-8 文本的稳定 SHA-256。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_prompt(name: str, variables: dict[str, str] | None = None,
                prompt_root: Path | None = None, version: str | None = None) -> PromptContent:
    """按注册表激活版本加载提示词，校验模板哈希后替换显式变量。"""
    root = prompt_root or PROMPT_ROOT
    if not SAFE_NAME.fullmatch(name):
        raise ValueError(f"invalid_prompt_name:{name}")
    registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    entry = registry.get("prompts", {}).get(name)
    if not isinstance(entry, dict):
        raise KeyError(f"prompt_not_registered:{name}")
    version = version or BOUND_VERSIONS.get().get(name) or entry.get("active")
    if not isinstance(version, str) or not SAFE_VERSION.fullmatch(version):
        raise ValueError(f"invalid_prompt_version:{name}")
    template_path = root / name / f"{version}.md"
    if template_path.is_symlink() or (root / name).is_symlink() or root.resolve() not in template_path.resolve().parents:
        raise ValueError(f"prompt_path_unsafe:{name}")
    template = template_path.read_text(encoding="utf-8")
    actual_hash = sha256_text(template)
    expected = entry.get("versions", {}).get(version)
    if expected is None and version == entry.get("active"):
        expected = entry.get("sha256")
    if actual_hash != expected:
        raise ValueError(f"prompt_hash_mismatch:{name}:{version}")
    provided = variables or {}
    required = set(PLACEHOLDER.findall(template))
    if required != set(provided):
        missing = sorted(required - set(provided))
        unexpected = sorted(set(provided) - required)
        raise ValueError(f"prompt_variables_mismatch:missing={missing}:unexpected={unexpected}")
    rendered = PLACEHOLDER.sub(lambda match: str(provided[match.group(1)]), template)
    identity = {"name": name, "version": version, "template_sha256": actual_hash,
                "rendered_sha256": sha256_text(rendered)}
    nested = tuple(component for value in provided.values() if isinstance(value, PromptContent)
                   for component in value.components)
    return PromptContent(name, version, rendered, actual_hash, sha256_text(rendered), (identity, *nested),
                         variables=provided, source_root=root)


def audit(prompt_root: Path | None = None, source_root: Path | None = None) -> dict:
    """校验全部历史模板并审计模型指令入口，输出可定位的注册清单。"""
    root = prompt_root or PROMPT_ROOT
    sources = source_root or PROMPT_ROOT.parent / "backend/app/runtime"
    entries = json.loads((root / "registry.json").read_text())["prompts"]
    references = {name: [] for name in entries}
    errors, inline = [], []
    for path in sorted(sources.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name == "load_prompt" and node.args and isinstance(node.args[0], ast.Constant):
                key = node.args[0].value
                if key not in references:
                    errors.append(f"unregistered:{path.name}:{node.lineno}:{key}")
                else:
                    references[key].append(f"{path.name}:{node.lineno}")
            if name == "model_tool_loop" and len(node.args) > 3 and isinstance(node.args[3], (ast.Constant, ast.JoinedStr)):
                inline.append(f"{path.name}:{node.lineno}")
    inventory = []
    for name, entry in entries.items():
        versions = entry.get("versions", {entry["active"]: entry["sha256"]})
        for version in versions:
            try:
                text = (root / name / f"{version}.md").read_text()
                variables = {key: f"audit:{key}" for key in PLACEHOLDER.findall(text)}
                load_prompt(name, variables, root, version)
            except (OSError, ValueError, KeyError) as exc:
                errors.append(f"{name}:{version}:{exc}")
        active_file = root / name / f'{entry["active"]}.md'
        inventory.append({"name": name, "active": entry["active"], "versions": versions,
                          "variables": sorted(set(PLACEHOLDER.findall(active_file.read_text()))) if active_file.is_file() else [],
                          "purpose": entry.get("purpose", name), "call_sites": references[name],
                          "historical_only": not references[name]})
    return {"prompts": inventory, "count": len(inventory), "inline_calls": inline,
            "errors": errors, "passed": not errors and not inline}


def main() -> None:
    """执行只读注册审计，失败返回非零退出码。"""
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
