# 2026-10-03 计算器舍入缺陷返修准备，真实调用被审批阻止

## 当前结论

后续更新：用户明确回复「授权」后，审批阻塞解除，沿同一持久断点实际六次 DeepSeek thinking／230,075 Token，旧流程进入待验收，固定独立复验通过。详见 [真实返修结果](calculator-rounding-repair-real-20261003.md) 。以下保留拒绝时的范围、零调用事实和准备记录，不倒写为连续无审批干预。

现存失败 Task 26 有可复现的业务缺陷：`1.245 + 0` 显示 `1.24`，批准需求 5.3 明确四舍五入，应为 `1.25`；`1.225` 和 `1.005` 也分别错误显示为 `1.22`、`1.00`。原生成的 Node 23 项测试全部通过，未覆盖这些边界。独立 Node 三项失败，真实 Chrome 三项舍入检查失败、除零和错误后恢复两项通过，无页面异常。

用户「可以」批准从现存失败任务选择问题、复制持久隔离副本并按原流程最多六次模型 HTTP 返修。执行命令被自动审批拒绝，理由为「这组具体 Task 26 私有文档、代码和证据向 DeepSeek 的外发缺少可信用户内容中的明确授权」。整个真实调用命令未执行；零模型 HTTP／Token，六次预算未消耗，未绕过或改用其他外发途径。

## 已完成的准备

- 持久目录：`workspace/experiments/calculator-rounding-repair-20261003-nbuuvlks/`，先保存目录约定，再复制原工作区与 Task 26 对应的五表记录。
- `source-workspace/26/` 保留原文件；`workspace/26/` 为可修改副本；`test.db` 沿用既有模型定义的新测试 SQLite。原 Run 计数、Trace 与检查点保留，调用次数单独存 `call-count.json`，恢复不得缺省零。
- 本轮是新的自然缺陷实验，不是旧素材平台或原 transport failure 续跑。仅在实验副本重映射绝对路径、清除过时产品进程字段，以新的 test 起点／返修轮数开始；原历史 Run 计数保持，正式 MySQL 不变。
- 给隔离产品增加三项需求回归；外置独立回归 `independent-rounding.test.cjs` 保留同一期望，模型修改测试不能替代独立复验。业务实现未经开发助手修改。
- 本机 Playwright 默认 Chromium 缺失、系统 Chrome 可用。准备阶段仅在副本 `verify_product.py` 将 `launch()` 改为 `launch(channel="chrome")`，保留原脚本、前后哈希和适配记录，未改断言或安装依赖。这不计作模型业务修复或零人工准备。
- 原 Worker 实际执行程序测试，三项需求回归失败后自然进入隔离 `running / develop / repair_round 1`，已保存完整失败报告；未启动该 SQLite 的后台 Worker，未调用模型。
- 控制脚本使用原模型路由、DeepSeek thinking 和 Worker 流程，仅旁路保存脱敏请求／实际 SSE 用量，所有模型 HTTP 与重试共用六次硬上限；模型调用前原子保存计数，终态或澄清停止，不自动答复或验收。
- 正式数据库核对字段、schema、文件状态、产品哈希及 Task 26 原工作区前后不变；隔离 SQLite 只读完整性、原 Run 计数及三个控制脚本语法核对通过。

## 范围与限制

Task 26 走兼容的旧单模块开发入口，没有新切片的 `self_test`／显式提交门禁。因此即便本轮旧流程到待验收，也只能证明该范围的真实返修和程序交付，不能证明新切片交接、最新 Planner 跨阶段调查恢复或任意任务稳定完成。独立回归和真实 Chrome 的修复后检查尚未执行，真实 Token 和模型修复能力没有新增证据。

请求批准的具体外发范围为：Task 26 的批准产品／架构与跳过设计决定、产品源代码和测试脚本、相关失败报告／文件版本／工具历史，发送给 DeepSeek 用于修复上述舍入缺陷。模型认证使用已有受控密钥文件，密钥及认证头不进入模型上下文或保存的请求正文。上限仍是六次实际模型 HTTP，包含重试；不修改正式任务、不重建素材平台、不重置旧预算。

## 证据

[机器可读摘要](calculator-rounding-repair-blocked-20261003.json) 保存当前零调用与审批阻塞。持久目录包含 `prepare.py`、`run.py`、`independent_browser.py`、基线截图／Node 输出、原工作区、SQLite、检查点与 Trace、`program-reproduction.json`、`environment-adaptation.json`、`approval-blocked.json`、`outbound-scope.json`、正式前后快照及原计数。

首次终端复现使用了错误的模块相对路径而报 MODULE_NOT_FOUND；改为产品目录内 `require('./app.js')` 后输出三个实际错误值，独立用例与 Chrome 再次确认。该脚本路径错误不是软件故障或模型失败。真实调用的自动审批拒绝同样不能归因于模型能力。
