import hashlib
import json
from pathlib import Path

import pytest

from backend.app.runtime.prompt_registry import PROMPT_ROOT, load_prompt


def test_registered_prompt_versions_match_immutable_files():
    """注册表中每个激活版本都必须存在且匹配声明哈希。"""
    registry = json.loads((PROMPT_ROOT / "registry.json").read_text(encoding="utf-8"))
    assert registry["prompts"]
    for name, entry in registry["prompts"].items():
        prompt_path = PROMPT_ROOT / name / f'{entry["active"]}.md'
        assert prompt_path.is_file()
        assert hashlib.sha256(prompt_path.read_bytes()).hexdigest() == entry["sha256"]


def test_failed_ownership_boundary_candidate_keeps_both_versions_and_v1_active():
    """失败候选必须保留证据，但正式入口继续使用已知基线。"""
    registry = json.loads((PROMPT_ROOT / "registry.json").read_text(encoding="utf-8"))["prompts"]
    for name in ("unit-planner", "design-author", "design-reviewer"):
        assert registry[name]["active"] == "v1"
        assert (PROMPT_ROOT / name / "v1.md").is_file()
        assert (PROMPT_ROOT / name / "v2.md").is_file()
    assert registry["unit-developer"]["active"] == "v1"
    assert registry["integration-repair-diagnoser"]["active"] == "v1"


def test_load_prompt_renders_only_declared_variables():
    """渲染结果保留版本身份，并拒绝缺失或多余变量。"""
    prompt = load_prompt("design-author", {"label": "模块设计", "draft": "docs/a.md"})
    assert prompt.name == "design-author"
    assert prompt.version == "v1"
    assert "模块设计" in prompt.text
    assert "docs/a.md" in prompt.text
    assert prompt.template_sha256 != prompt.rendered_sha256
    with pytest.raises(ValueError, match="prompt_variables_mismatch"):
        load_prompt("design-author", {"label": "模块设计"})


def test_load_prompt_rejects_modified_registered_version(tmp_path: Path):
    """已登记版本正文发生变化时必须在模型调用前失败。"""
    (tmp_path / "unit-planner").mkdir()
    (tmp_path / "unit-planner" / "v1.md").write_text("changed", encoding="utf-8")
    (tmp_path / "registry.json").write_text(json.dumps({"prompts": {"unit-planner": {
        "active": "v1", "sha256": "0" * 64,
    }}}), encoding="utf-8")
    with pytest.raises(ValueError, match="prompt_hash_mismatch"):
        load_prompt("unit-planner", prompt_root=tmp_path)
