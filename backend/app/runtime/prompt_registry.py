"""从项目提示词注册表加载并校验不可变版本。"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


PROMPT_ROOT = Path(__file__).resolve().parents[3] / "prompts"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SAFE_VERSION = re.compile(r"^v[1-9][0-9]*$")
PLACEHOLDER = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


@dataclass(frozen=True)
class PromptContent:
    """保存一次已校验和渲染的提示词及其可审计身份。"""

    name: str
    version: str
    text: str
    template_sha256: str
    rendered_sha256: str

    def __str__(self) -> str:
        """在日志和测试替身需要文本时返回渲染后的正文。"""
        return self.text

    def __contains__(self, value: str) -> bool:
        """保持既有调用测试对提示词正文的成员检查兼容。"""
        return value in self.text


def sha256_text(value: str) -> str:
    """计算 UTF-8 文本的稳定 SHA-256。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_prompt(name: str, variables: dict[str, str] | None = None,
                prompt_root: Path | None = None) -> PromptContent:
    """按注册表激活版本加载提示词，校验模板哈希后替换显式变量。"""
    root = prompt_root or PROMPT_ROOT
    if not SAFE_NAME.fullmatch(name):
        raise ValueError(f"invalid_prompt_name:{name}")
    registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    entry = registry.get("prompts", {}).get(name)
    if not isinstance(entry, dict):
        raise KeyError(f"prompt_not_registered:{name}")
    version = entry.get("active")
    if not isinstance(version, str) or not SAFE_VERSION.fullmatch(version):
        raise ValueError(f"invalid_prompt_version:{name}")
    template = (root / name / f"{version}.md").read_text(encoding="utf-8")
    actual_hash = sha256_text(template)
    if actual_hash != entry.get("sha256"):
        raise ValueError(f"prompt_hash_mismatch:{name}:{version}")
    provided = variables or {}
    required = set(PLACEHOLDER.findall(template))
    if required != set(provided):
        missing = sorted(required - set(provided))
        unexpected = sorted(set(provided) - required)
        raise ValueError(f"prompt_variables_mismatch:missing={missing}:unexpected={unexpected}")
    rendered = PLACEHOLDER.sub(lambda match: str(provided[match.group(1)]), template)
    return PromptContent(name, version, rendered, actual_hash, sha256_text(rendered))
