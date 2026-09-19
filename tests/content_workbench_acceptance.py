"""按原始需求独立操作界面，不调用生成产品内部业务接口。"""

import json
from pathlib import Path
import signal
import os
import subprocess
import sys
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

root = Path(sys.argv[1])
summary = json.loads((root / 'summary.json').read_text())
checks = []
errors = []

def record(name):
    # 仅在相应界面断言通过后记录通过证据。
    checks.append({'name': name, 'passed': True})

with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(summary['result_url'])
    expect(page.get_by_test_id('material-title-input')).to_be_visible()

    def nav(label):
        # 通过用户可见导航进入模块。
        page.get_by_role('button', name=label, exact=True).click()

    def material(title, note):
        # 使用界面表单创建固定验收素材。
        page.get_by_test_id('material-title-input').fill(title)
        page.get_by_test_id('material-note-input').fill(note)
        page.get_by_test_id('material-submit').click()

    page.get_by_test_id('material-note-input').fill('保留素材笔记')
    page.get_by_test_id('material-submit').click()
    expect(page.get_by_test_id('material-error')).to_be_visible()
    expect(page.get_by_test_id('material-note-input')).to_have_value('保留素材笔记')
    material('素材Alpha', '原笔记')
    material('素材Beta', '包含Needle关键词')
    material('素材Gamma', '第三条独立素材')
    expect(page.locator('[data-material-id].item')).to_have_count(3)
    record('素材空标题保留表单且修正后正常创建三条素材')
    page.get_by_test_id('material-search').fill('Alpha')
    expect(page.locator('[data-material-id].item')).to_have_count(1)
    page.locator('[data-action="material-edit"]').click()
    page.get_by_test_id('material-note-input').fill('更新后的笔记')
    page.get_by_test_id('material-submit').click()
    expect(page.locator('[data-material-id].item')).to_contain_text('更新后的笔记')
    page.get_by_test_id('material-search').fill('Needle')
    expect(page.locator('[data-material-id].item')).to_have_count(1)
    expect(page.locator('[data-material-id].item')).to_contain_text('素材Beta')
    page.get_by_test_id('material-search').fill('')
    material_id = page.locator('[data-material-id].item').filter(has_text='素材Alpha').get_attribute('data-material-id')
    record('标题与笔记检索、编辑笔记')
    nav('选题管理')
    page.get_by_test_id('topic-angle-input').fill('保留内容角度')
    page.get_by_test_id('topic-submit').click()
    expect(page.get_by_test_id('topic-error')).to_be_visible()
    expect(page.get_by_test_id('topic-angle-input')).to_have_value('保留内容角度')
    for title in ('选题One', '选题Two'):
        page.get_by_test_id('topic-title-input').fill(title)
        page.get_by_test_id('topic-angle-input').fill('测试多模块协作')
        page.get_by_test_id('topic-submit').click()
        row = page.locator('[data-topic-id].item').filter(has_text=title)
        row.locator('select').select_option(material_id)
        row.get_by_role('button', name='关联素材', exact=True).click()
        expect(row).to_contain_text('关联素材（1）')
    record('选题空标题恢复、同一素材关联两个选题')
    row = page.locator('[data-topic-id].item').filter(has_text='选题One')
    topic_id = row.get_attribute('data-topic-id')
    row.get_by_role('button', name='创建内容任务').click()
    task_id = page.get_by_test_id('task-detail').get_attribute('data-task-id')
    expect(page.get_by_test_id('task-title-input')).to_have_value('选题One')
    nav('选题管理')
    page.locator(f'[data-topic-id="{topic_id}"]').get_by_role('button', name='创建内容任务').click()
    assert page.get_by_test_id('task-detail').get_attribute('data-task-id') == task_id
    expect(page.locator('[data-task-id].item')).to_have_count(1)
    record('选题转任务复制标题、重复创建进入同一任务')
    page.get_by_test_id('task-title-input').fill('')
    page.get_by_test_id('task-draft-input').fill('保留草稿正文')
    page.get_by_test_id('task-save').click()
    expect(page.get_by_test_id('task-error')).to_be_visible()
    expect(page.get_by_test_id('task-draft-input')).to_have_value('保留草稿正文')
    page.get_by_test_id('task-title-input').fill('独立任务标题')
    page.get_by_test_id('task-due-input').fill('2000-01-01')
    page.get_by_test_id('task-save').click()
    page.get_by_test_id('task-status-写作中').click()
    expect(page.get_by_test_id('task-status-text')).to_contain_text('写作中')
    expect(page.get_by_test_id('task-source-topic')).to_contain_text('选题One')
    expect(page.get_by_test_id('task-source-materials')).to_contain_text('素材Alpha')
    record('任务空标题恢复、草稿截止日期状态保存、标题独立')
    nav('工作台')
    expect(page.get_by_test_id('dashboard-active-count')).to_have_text('1')
    expect(page.get_by_test_id('dashboard-overdue-count')).to_have_text('1')
    expect(page.get_by_test_id('dashboard-count-写作中')).to_contain_text('1')
    page.get_by_test_id(f'dashboard-open-{task_id}').click()
    expect(page.get_by_test_id('task-title-input')).to_have_value('独立任务标题')
    record('工作台统计逾期与进入任务')
    nav('选题管理')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator(f'[data-topic-id="{topic_id}"]').get_by_role('button', name='删除', exact=True).click()
    expect(page.get_by_test_id('topic-error')).to_be_visible()
    expect(page.locator('[data-topic-id].item')).to_have_count(2)
    record('已有任务来源选题删除被阻止')
    nav('素材库')
    row = page.locator(f'[data-material-id="{material_id}"].item')
    page.once('dialog', lambda dialog: dialog.dismiss())
    row.get_by_role('button', name='删除', exact=True).click()
    expect(page.locator('[data-material-id].item')).to_have_count(3)
    record('取消删除数据不变')
    prompts = []

    def confirm_delete(dialog):
        # 验证用户在确认前可见跨模块影响。
        prompts.append(dialog.message)
        dialog.accept()

    page.once('dialog', confirm_delete)
    row.get_by_role('button', name='删除', exact=True).click()
    assert '2' in prompts[0] and '选题' in prompts[0], prompts
    expect(page.locator('[data-material-id].item')).to_have_count(2)
    nav('选题管理')
    expect(page.locator('[data-topic-id].item')).to_have_count(2)
    for row in page.locator('[data-topic-id].item').all():
        expect(row).to_contain_text('关联素材（0）')
    page.locator(f'[data-topic-id="{topic_id}"]').get_by_role('button', name='创建内容任务').click()
    expect(page.get_by_test_id('task-source-materials')).not_to_contain_text('素材Alpha')
    expect(page.get_by_test_id('task-draft-input')).to_have_value('保留草稿正文')
    record('删除素材提示两个选题影响、级联解除关联且保留选题任务与其他素材')
    page.reload()
    expect(page.locator('[data-material-id].item')).to_have_count(2)
    nav('内容任务')
    page.locator(f'[data-task-id="{task_id}"].item').get_by_role('button', name='打开').click()
    expect(page.get_by_test_id('task-draft-input')).to_have_value('保留草稿正文')
    record('刷新持久化')
    stored_before = page.evaluate('JSON.stringify(localStorage)')
    # 仅重启本次隔离任务已经结束生成的预览服务，保持 origin 不变。
    os.killpg(os.getpgid(summary['process_id']), signal.SIGTERM)
    time.sleep(1)
    port = urlparse(summary['result_url']).port
    process = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'], cwd=Path(summary['workspace']) / 'product', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    (root / 'acceptance-server.json').write_text(json.dumps({'process_id': process.pid, 'url': summary['result_url']}))
    time.sleep(1)
    page.close()
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(summary['result_url'])
    expect(page.locator('[data-material-id].item')).to_have_count(2)
    assert page.evaluate('JSON.stringify(localStorage)') == stored_before
    nav('选题管理')
    expect(page.locator('[data-topic-id].item')).to_have_count(2)
    page.locator(f'[data-topic-id="{topic_id}"]').get_by_role('button', name='创建内容任务').click()
    expect(page.get_by_test_id('task-draft-input')).to_have_value('保留草稿正文')
    expect(page.get_by_test_id('task-status-text')).to_contain_text('写作中')
    record('关闭重启同端口服务并重新打开页面后数据关系状态保留')
    page.get_by_test_id('task-status-已发布').click()
    nav('工作台')
    expect(page.get_by_test_id('dashboard-active-count')).to_have_text('0')
    expect(page.get_by_test_id('dashboard-overdue-count')).to_have_text('0')
    expect(page.get_by_test_id('dashboard-count-已发布')).to_contain_text('1')
    record('已发布移除待办逾期并更新各状态数量')
    assert not errors, errors
    record('真实浏览器无页面脚本错误')
    page.screenshot(path=str(root / 'independent-acceptance.png'), full_page=True)
    (root / 'independent-acceptance.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, ensure_ascii=False, indent=2))
    browser.close()
print('INDEPENDENT_ACCEPTANCE', len(checks), 'passed')
