# 当前流程素材管理真实 DeepSeek 复测

日期：2026-09-24。结论：从空任务工作区真实调用至第一张业务切片开发，最终 `failed / develop / unit_development_no_progress`；未完成软件交付。

## 输入与执行边界

- 输入：`docs/CONTENT_WORKBENCH_REQUIREMENTS_V1_AI_DRAFT.md`。使用当前未提交的 Runtime 和激活提示词，其中 `architecture-scaffolder/v4`、`slice-planner/v4`、`slice-developer/v6`。
- 入口：`tests/content_workbench_baseline.py`，临时 SQLite 和独立任务工作区 `/private/tmp/content-workbench-current-network-20260924`；全阶段 DeepSeek，单 Step 最多 100 次逻辑调用，整轮最多 300 次实际 HTTP 请求。测试进程沿用该脚本的多模块／localStorage 约束适配，不改变正式服务或数据库。
- 初次沙箱运行在 `/private/tmp/content-workbench-current-20260924` 发生 3 次 `ConnectError`，无模型响应或用量；随后经联网授权重新从空任务开始。以下用量只计联网任务。
- 产品候选 v1 擅自把内容角度和草稿设为必填，测试控制依据原始需求提交拒绝事件；v2 去掉该限制后，由测试控制提交正式产品审批事件。没有人工修改生成代码或设计文档。因存在测试控制审批，本轮不称完全无人干预。

## 实际结果

- 产品 v2 正式化，架构与代码骨架生成，第一张结构化执行卡为 `materials-core`，拥有 storage 和 materials 的实现及测试文件。
- Developer 写入 `product/js/storage.js` 和 `product/js/materials.js`，调用一次 `run_unit_tests`；Node 返回退出码 0，但当前切片的 11 项测试全为 `test.todo`，实际通过数为 0，程序正确判定 `passed=false`。
- 随后 Developer 连续多轮重复读取 `storage.test.js` 和 `materials.test.js`，响应声称将把占位测试改为真实断言，却没有写入测试文件，最终由无进展门禁终止。`slice-progress.json` 中首片仍为 `developing`，`complete=false`。
- 独立只读执行生成产品的全部 Node 测试：47 项均为 todo，`pass 0 / fail 0 / todo 47`。未进入全量测试、HTTP 启动、真实浏览器验证或人工验收。Node 退出码 0 不代表生成产品通过验收。
- 联网任务实际 25 次 DeepSeek HTTP，25 份响应均有用量：输入 192,913、输出 34,296、合计 227,209 Token，其中输入缓存命中 55,424。该数是 Provider 报告的 Token，不等于实际费用。任务有 153 条 Trace；最终错误为 `unit_development_no_progress`。300 次总预算未耗尽。

## 证据与局限

- 临时目录包含 `summary.json`、`test.db`、25 份脱敏发送体、完整 Trace、产品与架构文档、骨架、切片卡和生成代码。关键 Trace：`000115-tool_result.json` 记录 11 项 todo 和 `passed=false`；`000147-model_response.json` 记录再次承诺替换 todo 但实际只调用 read；`000152-step.json` 记录无进展停止。
- 本轮直接证明真实模型未完成首片测试转换；重复读取和停止条件可从 Trace 核对。不能据此归因到单一提示词或证明修复方案有效；未继续续跑，也未修改 Runtime 或生成软件。
