"""从正式产品需求建立内部行为标准，并核对逐切片交付覆盖。"""

import hashlib
import json
from pathlib import Path

from .prompt_registry import load_prompt
from .tracing import safe_record_trace


STANDARD_PATH = "docs/acceptance-standard.json"
MAX_STANDARD_ITEMS = 100
MAX_STANDARD_ATTEMPTS = 3


def _object(response: str) -> dict:
    """解析无工具模型返回的单个 JSON 对象。"""
    value = json.loads(response.strip().removeprefix("```json").removeprefix("```")
                       .removesuffix("```").strip())
    if not isinstance(value, dict):
        raise ValueError("acceptance_json_object_required")
    return value


def _items(value: dict, product: str) -> list[dict]:
    """只接收能逐字指回正式需求的原子行为，并由程序分配稳定编号。"""
    raw = value.get("items")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_STANDARD_ITEMS:
        raise ValueError("acceptance_items_invalid")
    items = []
    seen = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError("acceptance_item_invalid")
        quote, action, result = (item.get(key) for key in
                                 ("source_quote", "action", "observable_result"))
        if not all(isinstance(part, str) and part.strip() for part in (quote, action, result)):
            raise ValueError("acceptance_item_field_invalid")
        quote, action, result = quote.strip(), action.strip(), result.strip()
        if quote not in product:
            raise ValueError("acceptance_source_quote_missing")
        signature = (quote, action, result)
        if signature in seen:
            raise ValueError("acceptance_item_duplicate")
        seen.add(signature)
        items.append({"id": f"A{index:03d}", "source_quote": quote,
                      "action": action, "observable_result": result})
    return items


def _checked_items(items: list[dict], product: str) -> list[dict]:
    """校验局部纠错后的稳定编号和每条原文依据。"""
    if not isinstance(items, list):
        raise ValueError("acceptance_items_invalid")
    checked = _items({"items": items}, product)
    ids = [item.get("id") for item in items]
    if any(not isinstance(item_id, str) or len(item_id) != 4
           or item_id[0] != "A" or not item_id[1:].isdigit() for item_id in ids) \
            or len(ids) != len(set(ids)):
        raise ValueError("acceptance_item_id_invalid")
    if any(item != {**valid, "id": item["id"]} for item, valid in zip(items, checked)):
        raise ValueError("acceptance_item_invalid")
    return items


def _merge_patch(items: list[dict], patch: dict, product: str) -> tuple[list[dict], list[dict]]:
    """仅替换被点名条目并追加新项，其他条目和编号保持不变。"""
    adds, replacements = patch.get("add"), patch.get("replace")
    if not isinstance(adds, list) or not isinstance(replacements, list) or not adds and not replacements:
        raise ValueError("acceptance_patch_invalid")
    by_id = {item["id"]: item for item in items}
    changes = {}
    next_number = max(int(item_id[1:]) for item_id in by_id) + 1
    for replacement in replacements:
        if not isinstance(replacement, dict) or not isinstance(replacement.get("id"), str) \
                or replacement["id"] not in by_id \
                or replacement["id"] in changes or not isinstance(replacement.get("items"), list) \
                or not replacement["items"]:
            raise ValueError("acceptance_patch_replace_invalid")
        validated = _items({"items": replacement["items"]}, product)
        rewritten = []
        for index, item in enumerate(validated):
            item["id"] = replacement["id"] if index == 0 else f"A{next_number:03d}"
            if index:
                next_number += 1
            rewritten.append(item)
        changes[replacement["id"]] = rewritten
    added = _items({"items": adds}, product) if adds else []
    for item in added:
        item["id"] = f"A{next_number:03d}"
        next_number += 1
    merged = [new_item for old in items for new_item in changes.get(old["id"], [old])] + added
    _checked_items(merged, product)
    changed = [item for group in changes.values() for item in group] + added
    return merged, changed


def load_standard(root: Path) -> dict | None:
    """读取与当前正式需求版本一致的内部标准；旧任务没有标准时保持原路径。"""
    path = root / STANDARD_PATH
    if not path.is_file():
        return None
    product = (root / "docs/product.md").read_text(encoding="utf-8")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("product_hash") != hashlib.sha256(product.encode("utf-8")).hexdigest():
        raise ValueError("acceptance_standard_product_changed")
    if value.get("review") != {"complete": True, "issues": []}:
        raise ValueError("acceptance_standard_review_missing")
    if value.get("items") != _checked_items(value.get("items"), product):
        raise ValueError("acceptance_standard_invalid")
    return value


def ensure_standard(db, task, run, tools) -> dict:
    """首次审查全文，之后仅局部纠错和复查，成功才保存标准。"""
    from . import worker as w
    root = w.workspace_for(task)
    existing = load_standard(root)
    if existing:
        return existing
    product = (root / "docs/product.md").read_text(encoding="utf-8")
    product_hash = hashlib.sha256(product.encode("utf-8")).hexdigest()
    progress_path = root / "evidence/acceptance-standard-progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.is_file() else {}
    if progress.get("product_hash") != product_hash or progress.get("workflow_version") != 2:
        progress = {"workflow_version": 2, "product_hash": product_hash,
                    "next_attempt": 0, "candidate_items": None, "issues": [],
                    "review_pending": False, "patch": None, "changed_items": []}
    for attempt in range(progress["next_attempt"], MAX_STANDARD_ATTEMPTS):
        if not progress["review_pending"]:
            # 首轮读取完整需求；后续只让模型提交针对具体审查问题的增补或替换。
            if progress["candidate_items"] is None:
                response = w.model_tool_loop(db, task, run, load_prompt("acceptance-extractor"), product,
                                             {}, tools, tool_schemas=[],
                                             history_key=f"acceptance_extract:{product_hash[:12]}:{attempt}")
                try:
                    items = _items(_object(response), product)
                except (ValueError, json.JSONDecodeError):
                    progress["next_attempt"] = attempt + 1
                    w.write_json_atomic(progress_path, progress)
                    continue
                patch, changed = None, []
            else:
                response = w.model_tool_loop(db, task, run, load_prompt("acceptance-corrector"), product,
                                             {"candidate_items": progress["candidate_items"],
                                              "issues": progress["issues"]}, tools, tool_schemas=[],
                                             history_key=f"acceptance_correct:{product_hash[:12]}:{attempt}")
                try:
                    patch = _object(response)
                    items, changed = _merge_patch(progress["candidate_items"], patch, product)
                except (ValueError, json.JSONDecodeError):
                    progress["next_attempt"] = attempt + 1
                    w.write_json_atomic(progress_path, progress)
                    continue
            # 在独立复查前持久化候选，进程中断时不重复已完成的模型调用。
            progress.update(candidate_items=items, patch=patch, changed_items=changed,
                            review_pending=True)
            w.write_json_atomic(progress_path, progress)
        items = progress["candidate_items"]
        if progress["patch"] is None:
            prompt = load_prompt("acceptance-reviewer")
            context = {"candidate_items": items}
        else:
            prompt = load_prompt("acceptance-correction-reviewer")
            context = {"previous_issues": progress["issues"], "patch": progress["patch"],
                       "changed_items": progress["changed_items"]}
        review_text = w.model_tool_loop(db, task, run, prompt, product, context, tools,
                                        tool_schemas=[], history_key=f"acceptance_review:{product_hash[:12]}:{attempt}")
        try:
            review = _object(review_text)
            issues = review.get("issues")
            if not isinstance(review.get("complete"), bool) or not isinstance(issues, list):
                raise ValueError("acceptance_review_invalid")
            if any(not isinstance(issue, dict) or not isinstance(issue.get("source_quote"), str)
                   or issue["source_quote"] not in product
                   or not isinstance(issue.get("problem"), str) or not issue["problem"].strip()
                   for issue in issues):
                raise ValueError("acceptance_review_issue_invalid")
            if review["complete"] == bool(issues):
                raise ValueError("acceptance_review_inconsistent")
        except (ValueError, json.JSONDecodeError):
            progress["next_attempt"] = attempt + 1
            w.write_json_atomic(progress_path, progress)
            continue
        if not review["complete"]:
            progress.update(next_attempt=attempt + 1, issues=issues,
                            review_pending=False, patch=None, changed_items=[])
            w.write_json_atomic(progress_path, progress)
            continue
        standard = {"product_hash": product_hash, "items": items,
                    "review": {"complete": True, "issues": []}}
        w.write_json_atomic(root / STANDARD_PATH, standard)
        safe_record_trace(db, task, run, "acceptance_standard", "succeeded", "内部行为标准已核对",
                          f"{len(items)} 条行为", {"path": STANDARD_PATH, "product_hash": product_hash,
                                             "items": items})
        db.commit()
        return standard
    raise RuntimeError("acceptance_standard_review_failed")


def validate_card_ids(card: dict, standard: dict) -> None:
    """保证新执行卡仅引用当前正式需求提取出的行为编号。"""
    ids = card.get("acceptance_ids")
    valid = {item["id"] for item in standard["items"]}
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids) \
            or len(ids) != len(set(ids)) or not set(ids) <= valid:
        raise ValueError("slice_acceptance_ids_invalid")


def coverage_gap(standard: dict, completed: list[dict]) -> list[str]:
    """比较已通过切片声明的编号，找出完全没有交付归属的行为。"""
    claimed = {item for entry in completed for item in entry["card"].get("acceptance_ids", [])}
    return [item["id"] for item in standard["items"] if item["id"] not in claimed]


def review_coverage(db, task, run, tools, standard: dict, completed: list[dict]) -> dict:
    """独立核对每项行为的切片验收与浏览器脚本，保留审查原始依据。"""
    from . import worker as w
    root = w.workspace_for(task)
    missing = coverage_gap(standard, completed)
    if missing:
        return {"complete": False, "issues": [{"acceptance_id": item,
                "problem": "没有已通过切片引用该行为"} for item in missing]}
    script = root / "product/verify_product.py"
    context = {"acceptance_standard": standard["items"],
               "passed_slices": [{"id": entry["card"]["id"],
                                  "acceptance_ids": entry["card"].get("acceptance_ids", []),
                                  "acceptance": entry["card"]["acceptance"],
                                  "test": entry.get("test")} for entry in completed],
               "browser_script": script.read_text(encoding="utf-8") if script.is_file() else "",
               "latest_verification_report": (root / "evidence/verification-report.md").read_text(encoding="utf-8")
               if (root / "evidence/verification-report.md").is_file() else ""}
    response = w.model_tool_loop(db, task, run, load_prompt("acceptance-coverage-reviewer"),
                                 "核对所有内部行为是否有相应的真实验证安排。", context,
                                 tools, tool_schemas=[], history_key="acceptance_coverage_review")
    try:
        review = _object(response)
        issues = review.get("issues")
        valid_ids = {item["id"] for item in standard["items"]}
        if not isinstance(review.get("complete"), bool) or not isinstance(issues, list) \
                or any(not isinstance(issue, dict) or issue.get("acceptance_id") not in valid_ids
                       or not isinstance(issue.get("problem"), str) or not issue["problem"].strip()
                       for issue in issues) or review["complete"] == bool(issues):
            raise ValueError("acceptance_coverage_review_invalid")
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("acceptance_coverage_review_invalid") from exc
    coverage_by_id = {item["id"]: [
        {"slice_id": entry["card"]["id"], "test_report": entry.get("report"),
         "acceptance": entry["card"]["acceptance"]}
        for entry in completed if item["id"] in entry["card"].get("acceptance_ids", [])]
        for item in standard["items"]}
    report = {"product_hash": standard["product_hash"], "review": review,
              "coverage_by_id": coverage_by_id,
              "product_code_hashes": w.product_code_hashes(task),
              "browser_script_sha256": hashlib.sha256(context["browser_script"].encode("utf-8")).hexdigest()}
    w.write_json_atomic(root / "evidence/acceptance-coverage-review.json", report)
    safe_record_trace(db, task, run, "acceptance_coverage", "succeeded" if review["complete"] else "failed",
                      "切片行为覆盖核对", "通过" if review["complete"] else "存在缺口", report)
    db.commit()
    return review
