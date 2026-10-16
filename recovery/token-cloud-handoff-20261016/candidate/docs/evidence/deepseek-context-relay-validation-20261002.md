# DeepSeek 上下文接力与结果去重验证

日期：2026-10-02。范围：用户「继续」授权的已有产物切片返修机制。本轮没有付费模型调用、正式任务续跑或生成产品代修。

## 结论

已实现并验证：已发送到协议工具消息的结果不重复放入 `current_requested_data`；完整修改批次和新版本诊断之后，可以从当前任务状态开始新消息上下文。原始检查点、完整思考、工具结果、进展和调用计数保留。当前会话仍完整续传思考与成对工具消息，未选择性删除某轮的 `reasoning_content`。

相关 215 项本地回归通过；随后复现并修复历史截断范围误拦截，4 项定向回归通过。实际 Worker＋Fake 模型动作＋真实 Node 闭环通过，不能作为真实 DeepSeek 自主交付证据。

## 当前设计与实现

- 仅 DeepSeek 的 `repair_task` 切片返修启用接力。读取阶段不重建，其他开发阶段保持原流程。
- 同批全部工具返回、固定测试范围的文件实际变化、诊断前后版本与当前完整版本一致，才记录边界。诊断通过或失败均可提供当前反馈，但不代替主动自测及显式提交。
- 边界记录保存至任务工作区 `evidence/deepseek-context-session-{run_id}-{history_key_hash}.json`，包含整批调用 ID、诊断引用、版本和最近修改摘要。恢复核对完整批次，缺结果或边界无效时不切开历史。
- 原始目标、返修依据引用、所有权、执行契约、当前版本及自测／交接状态持续提供。新会话不拼接边界前的 assistant／tool 消息，不新增模型摘要调用。
- 历史中实际读取或完整写过的范围合并后，通过受控读取刷新为当前版本的 `carried_file_context`。未读文件不自动附带全文；缺失、权限撤销或范围消失不能作为正文。仍遵守原有 100 KiB 单次输出限制，字节截断的半行不计为完整范围。
- 同 Run、同责任卡与同原始失败恢复原返修循环 ID，不因已完成动作数增长而丢失历史。不同 Run／责任卡／失败仍隔离。
- 去重只影响发送消息，原始请求对象、历史检查点及 Trace 不修改。

代码：`backend/app/runtime/context_relay.py`、`model.py`、`worker.py`、`slice_workflow.py`。当前 Developer 仍为 v12，thinking 与预算设置没有改变。

## 验证输入、步骤与结果

### 1．协议及只读证据

`tests/test_model_runtime.py` 构造同一结果同时位于协议历史和按需数据的请求。期望正文仅出现一次，按需数据保留调用 ID 引用，其他数据保留，完整思考和原对象不变；实际通过。显式空的新会话历史能覆盖旧投影，不发送旧 assistant／tool 轮次。既有多工具批次及无工具思考续传回归通过。

### 2．范围与恢复

`tests/test_context_relay.py` 使用真实文件读写验证重叠范围合并、修改后正文刷新、依赖只读文件保留、未提供范围继续可读、同批缺结果不建立边界、截断／缺失／权限撤销不作完整证明。

实际 Worker 在完整读写批次后模拟退出，再恢复同 Run。新请求携带当前文件正文和原目标，不续传旧协议消息；写入只执行一次，已消耗逻辑调用不重置，原检查点内容不变。

### 3．修改、反馈、自测和交接

`tests/test_slice_workflow.py::test_repair_batch_diagnostic_allows_more_edits_and_reuses_explicit_self_test` 使用真实 Worker、Fake 模型及真实 Node，六次模型逻辑调用完成：

1．同批改两文件，使固定测试通过，仅运行一次批次诊断并建立新上下文。
2．读取一个此前未提供的文件，不重建或重复诊断。
3．提前提交仍被拒绝，当前会话完整保留读取思考和工具结果。
4．模型继续修改，诊断取得新失败，再建立新上下文。
5．修复并主动自测，同版本诊断复用自测，不再重复执行。
6．当前自测通过后显式提交，再执行独立测试。

实际保留八条原始工具检查点、六次调用计数及三次完整边界。新会话的文件正文随版本更新；权限、目标与提交门禁保留。

### 4．截断误拦截复现与修复

构造 110 KiB 单行文件，历史 read 请求范围为第 1 至 2 行但输出在第一行被字节截断。原重复读取判断使用工具声明的 `end_line`，错误拒绝重新获取第 1 行。复现失败后改为按实际完整返回行计算覆盖范围，定向回归通过。此修正同时用于当前协议正文和接力正文，不把半行当作已完整提供。

## 命令与结果

```bash
.venv/bin/python -m pytest -q tests/test_context_relay.py tests/test_model_runtime.py tests/test_slice_workflow.py tests/test_worker_events.py tests/test_unit_workflow.py tests/test_tool_summaries.py tests/test_prompt_registry.py --disable-warnings --tb=short
```

结果：215 passed，28.20 秒。随后截断修复的定向命令：

```bash
.venv/bin/python -m pytest -q tests/test_context_relay.py tests/test_worker_events.py -k 'relay or repeat or duplicate or preview or range' --disable-warnings --tb=short
```

结果：4 passed，0.24 秒。`git diff --check` 通过。

## 旧真实请求的离线去重

输入来自 `/private/tmp/repair-diagnostic-deepseek-20261002-r94q4iem/sent-requests/`，仅重新组装已有请求，不发送网络调用、不改原文件。

| 请求 | 去重前 user 正文字符 | 去重后 user 正文字符 | 结果 |
|---|---:|---:|---|
| 第 9 次 | 49,982 | 40,914 | 一份重复结果改为引用，减少 9,068 字符 |
| 第 12 次 | 42,498 | 42,498 | 无重复结果，不删其他内容 |

两份请求的历史 assistant／tool 消息均与原发送内容完全一致。元数据：`/private/tmp/deepseek-context-dedup-offline-20261002.json`。这不是实际 Token 测量，也未模拟未经新诊断确认的重建边界，不能将其数字与前一轮聚焦返修的降幅相加。

## 正式服务与限制

重启前沿用当前 Worker 的实际数据库连接，只读确认待处理事件为 0、运行任务为 0。Worker PID 30210→50890，新进程存活，启动日志无输出；没有自动续跑旧失败任务或改数据库状态。

日志：`/private/tmp/ai-agent-worker-context-relay-20261002.log`。无凭据元数据：`/private/tmp/deepseek-context-worker-restart-20261002.json`。临时目录证据可能随系统清理失效，必要摘要和可重现测试保留在本仓库。

未验证：实际 DeepSeek 在新机制下的成功率、Token 消耗、原目标闭合和完整产品交付。纯读取阶段不会触发重建，不能单独解决先前九轮通读、较晚修改或不提交的问题；已读范围也可能很大。没有取消 thinking、增加预算、自动提交或放宽验收。
