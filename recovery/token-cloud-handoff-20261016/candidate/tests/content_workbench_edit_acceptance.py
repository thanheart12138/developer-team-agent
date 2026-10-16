"""对隔离生成的内容工作台执行已有素材与选题的真实浏览器编辑验收。"""

import argparse
import re

from playwright.sync_api import sync_playwright


def verify_existing_record_edit(url: str) -> None:
    """在独立浏览器存储中创建记录，并经页面入口编辑已有记录。"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        context = browser.new_context()
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="networkidle")

        page.locator('#app-nav button[data-view="materials"]').click()
        page.locator('#materials-form input[name="title"]').fill("验收素材")
        page.locator('#materials-form input[name="note"]').fill("旧笔记")
        page.locator('#materials-form button[type="submit"]').click()
        material = page.locator('#materials-list li').filter(has_text="验收素材").first
        assert material.count() == 1, "material_create_or_display_failed"
        edit = material.get_by_role("button", name=re.compile("编辑|修改"))
        assert edit.count() == 1, "material_edit_entry_missing"
        edit.click()
        page.locator('#materials-form input[name="note"]').fill("更新后的笔记")
        page.locator('#materials-form button[type="submit"]').click()
        page.locator('#materials-search').fill("更新后的笔记")
        assert "验收素材" in page.locator('#materials-list').inner_text(), "material_edit_not_saved"
        assert page.locator('#materials-list li').count() == 1, "material_edit_created_duplicate"
        page.reload(wait_until="networkidle")
        page.locator('#app-nav button[data-view="materials"]').click()
        page.locator('#materials-search').fill("更新后的笔记")
        assert "验收素材" in page.locator('#materials-list').inner_text(), "material_edit_not_persistent"

        page.locator('#app-nav button[data-view="topics"]').click()
        page.locator('#topics-form input[name="title"]').fill("验收选题")
        page.locator('#topics-form input[name="angle"]').fill("旧角度")
        page.locator('#topics-form button[type="submit"]').click()
        topic = page.locator('#topics-list li').filter(has_text="验收选题").first
        assert topic.count() == 1, "topic_create_or_display_failed"
        edit = topic.get_by_role("button", name=re.compile("编辑|修改"))
        assert edit.count() == 1, "topic_edit_entry_missing"
        edit.click()
        page.locator('#topics-form input[name="angle"]').fill("更新后的角度")
        page.locator('#topics-form select[name="priority"]').select_option("high")
        page.locator('#topics-form button[type="submit"]').click()
        assert "更新后的角度" in page.locator('#topics-list').inner_text(), "topic_edit_not_saved"
        assert page.locator('#topics-list li').filter(has_text="验收选题").count() == 1, "topic_edit_created_duplicate"
        page.reload(wait_until="networkidle")
        page.locator('#app-nav button[data-view="topics"]').click()
        assert "更新后的角度" in page.locator('#topics-list').inner_text(), "topic_edit_not_persistent"
        assert not errors, f"browser_script_errors:{errors}"
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    verify_existing_record_edit(parser.parse_args().url)
    print("MATERIAL_AND_TOPIC_EDIT_ACCEPTANCE_PASSED")
