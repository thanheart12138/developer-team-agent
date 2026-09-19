# 工具执行摘要与历史查询验证

日期：2026-09-17。状态：已实现、机制与真实工具已验证，用户验收待执行。

## 实现范围

- 每个逻辑模型请求沿用 request_id 作为 model_call_id，同一响应的多个工具共享父调用 ID；传输重试和 Provider 降级不另建父 ID。程序调用的父 ID 为空。
- 真实工具执行后在当前任务 `evidence/tool-summaries.jsonl` 原子保存短摘要。记录操作目的、实际结果、调用归属和 Trace 引用；文件写入记录实际前后 SHA-256、是否改变及字节数。摘要 ID 幂等，不增加模型调用和数据库 schema。
- 新增 `get_file_change_history`、`get_model_call_summaries`、`get_tool_execution_detail`。摘要每页最多 20 条，详情默认结果、每页最多 8,000 字符，使用 next_cursor 续查。详情仅取当前任务 Trace，不重新执行工具。
- 模型仅获取同一 StepRun／history_key 最近一批完整交互，以及最近 20 条较早摘要、更早条数和未解决失败证据。原始 Trace 和检查点保持完整；缺摘要或缺原始证据的交互保留全文。旧任务不批量回填。
- 当前产品清单、哈希及已有返修快照逐调用刷新，近期原始交互已完整携带同版本文件时去除重复快照。历史执行记录核对当前代码版本，不把旧版本执行成功作为当前验证通过。
- 返修允许 read 和三个历史查询工具；仅 write 的文档阶段及无工具 Planner 不增加权限。正式预算与产品约束不变。

## 机制验证

执行 `.venv/bin/python -m pytest -q`，115 项通过。日志：`/private/tmp/tool-summary-regression.log`。

新增 13 项测试覆盖真实文件版本、批次归属、最近批次完整配对、20 条窗口与子循环隔离、快照刷新去重、失败命令不被无关成功清除、执行结果过期、摘要／详情分页还原、跨任务及越界拒绝、查询自身不复制大结果、旧检查点兼容、缺证据保留全文、被阻止操作留摘要、账本故障不丢工具结果，以及摘要已落盘但检查点未提交结果时恢复而不重复执行。模型由 Fake 返回，不替代真实 Provider 能力证据。既有 datetime 弃用警告仍存在。

## 真实工具和生成软件回归

没有人工修改生成的软件，没有新增模型调用。

- Task25 产物隔离副本：Node 22 项通过；实际启动 HTTP，生成的 Chromium 验证通过，包括错误输入后的恢复。证据目录：`/var/folders/h7/z81qmxk16ks2kn3jzr21_k7m0000gn/T/calculator-entry-regression-7f57eywt`，执行日志：`/private/tmp/tool-summary-calculator.log`。首次启动临时脚本缺少 PYTHONPATH，修正启动命令后通过，不是产品缺陷。
- 多模块已有产物：隔离 SQLite 与工作区，Worker 执行 Node 20 项、HTTP 启动及生成 Chromium 验证，进入 waiting_acceptance，调用数 0。目录：`/private/tmp/content-workbench-tool-summary-regression-20260917`；日志：`/private/tmp/tool-summary-workbench.log`。真实系统工具的摘要同步落盘。
- 独立 Chromium 13 组业务操作通过，包含同端口 HTTP 服务真实关闭重启后的关系、状态及正文持久化。结果：上述目录 `independent-acceptance.json`、截图 `independent-acceptance.png`；日志：`/private/tmp/tool-summary-independent.log`。

## 服务加载与限制

确认正式运行任务 0、待处理 Event 0 后重启单 Worker，旧 PID 73874、新 PID 82885，启动存活检查通过。Task25 保持 waiting_acceptance、Task26 保持 failed，未自动续跑。日志：`/private/tmp/tool-summary-worker-restart.log`。API 未修改。

`git diff --check` 通过。真实 DeepSeek 对新查询工具的使用、新摘要上下文下的完整自主开发及 Token／返修收益未验证，不能据此声称成本下降。账本只覆盖工具执行，不覆盖 exec 或人工产生的逐文件修改，也不提供历史版本回滚；临时证据目录不是永久归档。Windows 与用户本人验收未执行。
