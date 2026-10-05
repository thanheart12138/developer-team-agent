# 返修诊断、接力报告与调用预算修复

日期：2026-10-02。用户在真实失败分析后授权「修复吧」。范围为反馈与上下文机制，不追加真实模型调用、不续跑正式任务，不修改产品产物或验收要求。

## 原因与复现

- 上一真实样本的长浏览器错误中，应用步骤占据前 1,400 字符，断言栈约在第 2,000 字符后。摘要缺少 product.test.js 第 982／1003 行及 actual／expected，模型只能读取报告再推算行号。
- 第二次模型请求的两个 read 只填写 end_line，后端要求 start_line／end_line 成对提供；修正消耗了下一轮请求。工具定义没有说明这个配对约束。
- 第 8、11 次请求接力携带已读旧报告正文，分别为 15,926、28,809 字符；文件本身未变不代表报告仍适用于当前产品版本。模型实际区分了旧失败与当前失败，不能将旧报告当作当前代码知识。
- 模型请求未提供 Step 调用计数或剩余额度；提示还在返修模式下引用从零开发字段及未开放的重规划工具。无证据表明模型真的调用过那个未开放工具。

修复前新增的三个回归均失败，分别复现长日志丢失实际／期望值、旧报告正文被接力、请求不存在预算字段。

## 已实施

1. `_repair_failure_excerpt` 优先取 Node spec 末尾详细失败区或 TAP 失败块，保留测试名、位置、错误、应用栈、断言及实际／期望值；过滤成功和应用步骤流水。单行及整体截断明确指向原始报告，不增加默认日志上限。完整报告未改。
2. 上下文接力将已读 `evidence/slice-repair-diagnostic-*.json` 改为 `diagnostic_report_refs`，区分边界诊断和历史报告；正文不进入 `carried_file_context`。当前结果仍来自 `unit_diagnostic`，旧报告保留原读取权限、查询入口和完整审计，原工具协议未删改。
3. `read` 的函数及参数说明明确起止行同时填写，结束行不得小于开始行；后端规则及省略两个参数时的读取行为保持。
4. 每次实际请求提供 `model_call_budget`：逻辑调用上限、包含本次的已用数、本次之后剩余数，以及重试不计入的明确标记。预算来自真实 StepRun 和现有上限，接力／恢复不重置。生产仍是最多 100 次逻辑调用；该字段不是 HTTP 次数预算，未新增 HTTP 持久计数或改变外部实验的 HTTP 硬上限。
5. 激活不可变 Developer v13，明确从零开发／返修条件，返修使用实际存在的任务和只读依据引用。重规划仅在相应模式且工具开放时使用；原目标、写权限、实际自测、显式提交及独立验证门禁保留。

有效设计先更新于 `docs/DEV_DESIGN.md` 与 `docs/ARCHITECTURE.md`，未调整 thinking、模型路由、数据库或密钥。

## 验证结果

### 本地机制

相关回归命令：

```text
.venv/bin/python -m pytest -q tests/test_context_relay.py tests/test_model_runtime.py tests/test_slice_workflow.py tests/test_worker_events.py tests/test_unit_workflow.py tests/test_tool_summaries.py tests/test_tools.py tests/test_prompt_registry.py --disable-warnings --tb=short
```

首次为 226 passed／1 failed，28.10 秒：新增 TAP 用例发现失败块末尾混入下一成功测试的 `# Subtest` 标题。过滤后继续补充长单行错误边界，最终执行 16 项定向回归，16 passed，2.47 秒。该批覆盖：

- 真实 Node spec／TAP，80 行应用步骤及 8,000 字符单行错误，仍保留失败行号和 actual／expected，成功标题不混入，完整报告仍含原正文。
- 真实返修入口诊断、当前目标保持和原卡只读权限。
- 实际 Worker＋Fake 动作＋真实 Node：诊断通过后允许继续修改、提前提交被拒绝、主动自测后才能显式提交。
- 旧报告不携带正文但仍可按原权限读取；普通证据和代码范围仍接力，历史未改。
- Worker 恢复不重复写入，预算保持已用次数；第 100 次请求明确剩余为零，仍允许本次完成。
- 原工具无效范围拒绝及激活提示版本哈希校验。

以上次数有交集，不相加；修正后未再重跑整个相关集合。Fake 仅验证机制，不代表真实 DeepSeek 完成任务。差异检查通过。

### 旧真实证据离线核对

| 原报告版本 | 新失败摘要字符数 | 定位与断言 |
|---|---:|---|
| 28c6fbc90aae07fd | 1,617 | 第 982 行、actual false／expected true 保留 |
| f015e06e0fd6f8f9 | 1,101 | 失败定位及实际／期望值保留 |
| 4f16114c6c54efc0 | 427 | 第 1003 行、actual false／expected true 保留 |

三个摘要均无 `[step]` 流水。旧请求中的 15,926／28,809 字符是可移除的报告正文数量，不是实际 Token 收益；本轮没有真实请求可用于成本比较。

### 本地服务

重启前正式库 0 pending event／0 running task，仅一个 Worker。Worker 50890→2573，单实例存活，启动日志 0 字节；24 条任务的 ID／状态／阶段／版本及 Trace 数量在重启前后完全一致。没有重启产品服务、自动续跑失败任务或改变正式数据库状态。

## 结论与未验证项

反馈与上下文修复已实现并通过上述本地验证，尚未用户验收。真实模型交接、原目标 E4-1 闭合、完整软件交付及稳定 Token 收益仍未验证。

上一样本所有 12 次输入诊断均为失败；最后一次修改后程序才转绿，随后预算停止，没有第 13 次请求。零自测／提交不能解释为模型「看见通过后拒绝交接」，通过后的模型行为并未观察到。没有扩大预算或替模型自测／提交。

临时证据（后续可能失效）：

- 旧真实请求与报告：`/private/tmp/context-relay-deepseek-20261002-_6ip7z8p`。
- 离线核对：`/private/tmp/repair-feedback-offline-audit-20261002.json`。
- 正式库只读快照：`/private/tmp/repair-feedback-worker-before-20261002.json`。
- 重启核对：`/private/tmp/repair-feedback-worker-restart-20261002.json`。
- Worker 日志：`/private/tmp/ai-agent-worker-repair-feedback-20261002.log`。
