import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(sys.argv[1])
summary=json.loads((root/'summary.json').read_text())
checks=[]; errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(summary['result_url'])
    def click(sequence):
        # 独立按界面按钮文字执行原始需求，不导入生成的软件测试逻辑。
        for char in sequence:
            page.get_by_role('button',name=char,exact=True).click()
    def check(name,expected):
        # 每项期望来自测试前固定的需求。
        actual=page.locator('#display').inner_text()
        assert actual==expected, (name,expected,actual)
        checks.append(dict(name=name,expected=expected,actual=actual))
    check('initial','0')
    for expr,expected in [('2+3=','5.00'),('7-2=','5.00'),('3*4=','12.00'),('9/4=','2.25'),('1.235+0=','1.24')]:
        click('C'+expr);check(expr,expected)
    click('C5/0=');check('division zero','Error')
    click('+=');check('error operators ignored','Error')
    click('6+4=');check('error recovery','10.00')
    click('=');check('repeated equals ignored','10.00')
    click('+');check('no continuous calculation','10.00')
    click('7');check('new calculation after result','7')
    click('C5/0=C');check('clear recovers error','0')
    click('1..2');check('duplicate decimal ignored','1.2')
    click('C.5+1=');check('leading decimal','1.50')
    click('C5=');check('equals without operator','5')
    click('+=');check('equals without right operand','5')
    click('C');check('clear pending state','0')
    page.keyboard.type('2+3=');check('keyboard unsupported','0')
    click('999999999*999999999=');check('long result','999999998000000000.00')
    assert page.locator('#display').evaluate('(e)=>e.scrollWidth<=e.clientWidth'), 'long display clipped'
    checks.append(dict(name='long result fits display',passed=True))
    assert not errors, errors
    checks.append(dict(name='page errors',actual=errors,passed=True))
    page.screenshot(path=str(root/'acceptance.png'),full_page=True)
    browser.close()
(root/'independent-acceptance.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
print('independent_browser_checks',len(checks),'passed')
