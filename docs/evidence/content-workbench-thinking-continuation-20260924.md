# 素材管理 DeepSeek thinking 断点续测

日期：2026-09-24。范围：继续隔离目录 `/private/tmp/deepseek-thinking-checkpoint-probe-20260924-40b86j4c` 的素材管理任务；它由此前失败工作区复制，并在已修复的 `topics-core` 断点开始。本次不修改正式 MySQL 任务，不能视为从空工作区自主生成的验证。

## 输入、预算与过程

- 原始需求与测试约束沿用 `tests/content_workbench_baseline.py`；真实 Provider 为 DeepSeek `deepseek-flash`，thinking 开启。整条隔离任务累计最多 300 次实际模型 HTTP，单阶段最多 100 次逻辑调用。
- 续跑前 `materials-core`、`topics-core` 两张切片已通过，Node 为 23 pass／0 fail／26 todo。继续后 `tasks-core`、`dashboard-summary`、`app-shell-integration` 依次通过，独立 `node --test js/*.test.js` 为 54 pass／0 fail／0 todo。
- 第一次续跑在 Planner 返回 `complete` 时失败：三次完整 JSON 的 `coverage_summary` 使用 `covered_by` 列表，最后一次以 `acceptance` 标注验收项；Runtime 仅接受 `requirement` 字符串与 `covered_by` 字符串，返回 `slice_coverage_summary_invalid` 后又只提示「修正结构错误」，最终 `slice_plan_validation_failed`。提示词只要求逐项说明覆盖来源，Dev Design 未限定这一字段形状；这是完成报告结构校验与模型输出不一致。
- 修复 Runtime：完成报告同时接受非空 `requirement`／`acceptance` 和非空字符串／字符串数组形式的 `covered_by`；校验失败时明确返回所需结构。新增实际输出形式的回归，先复现失败；修复后后端全量 215 项通过。未放宽切片测试、固定入口和 TODO 清零的门禁。
- 从保留的失败 StepRun 恢复后又发生 2 次真实 HTTP，Planner 返回有效完成报告。任务依次通过 `test`、`start_product`、`verify_product`，当前为 `waiting_acceptance`，结果 URL 为 `http://127.0.0.1:55760` 。

## 验证与用量

- 程序全量 Node 与独立复跑均为 54 pass／0 fail／0 todo。生成的 `verify_product.py` 在真实 Chromium 中完成 13 步操作：素材和选题增删关联、删除确认／取消、任务幂等创建、选题删除守卫、任务状态与逾期计数、刷新后 localStorage 数据保留；退出码 0。验证 Trace 为 `workspace/1/traces/verify_product/1/000272-validation.json`。
- 独立 Playwright 探针 `/private/tmp/verify_content_workbench_independent_20260924.py` 对运行中的页面复核：HTTP 200、工作台默认入口、空素材标题报错、已填写笔记保留、修正标题后成功保存、刷新后仍存在；页面脚本错误 0。探针在独立 browser context 内操作，不改生成产品源码。
- 隔离任务保存 48 份模型响应的 Provider usage：输入 2,308,596、输出 159,753、合计 2,468,349 Token。48 次实际 HTTP 为此前失败来源 19 次、thinking 断点修复 3 次、本次首次续跑 24 次、结构校验修复后恢复 2 次的累计值；本次新增 26 次、2,099,254 Token。DeepSeek 响应没有美元费用字段。完整摘要在隔离目录 `summary.json`，Trace 共 274 条。

## 结论边界

这条经人工选择断点、隔离复制并在结构校验失败后修正 Runtime 的链路已到达可操作的 `waiting_acceptance`，不是首次从零无干预完成。生成软件已实际启动并通过真实浏览器操作；用户本人尚未验收。此结果证明当前断点之后可完成剩余开发与验证，不证明任意新任务的稳定性，也不证明 Token 消耗已下降。
