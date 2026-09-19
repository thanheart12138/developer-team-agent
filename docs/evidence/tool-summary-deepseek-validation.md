# 工具摘要：真实 DeepSeek 测试失败记录

日期：2026-09-17。结论：查询工具实际可用，当前上下文策略未通过真实模型任务测试；用户验收未执行。

## 范围与预算

用户授权后，以既有四模块内容管理需求执行隔离全 DeepSeek 基准，再执行历史查询探针。使用独立 SQLite、工作区和合成数据，不修改正式服务、正式业务库、密钥或生成代码。

原基准、诊断续跑、探针共用最多 200 次实际模型 HTTP 请求预算，包含传输重试。本次实际 83 次。81 个完整返回报告输入 1,923,962、输出 104,032、总计 2,027,994 Token；中断的第 18、75 次请求无完整 usage，此数为可核对下界，不是全部计费量。无严格 A／B 对照，不能据此判断成本下降。

## 一、原完整流程：文档输出截断

入口：`tests/content_workbench_baseline.py`。目录：`/private/tmp/content-workbench-summary-deepseek-20260917`。日志：`/private/tmp/tool-summary-deepseek.log`。

需求经过 Draft／Review／Candidate，测试控制核对四模块和跨模块行为，采用候选默认口径（四状态可回退，删除提示至少包含受影响选题数量）后走正式审批事件。该批准仅属于隔离测试用户，不代表用户本人验收。架构生成与评审通过。

Dev Design 的正式写入反复返回非法参数 JSON。原始响应证据表明 `finish_reason=length`、`completion_tokens=8192`，arguments 在字符串中间结束。第 18 次请求期间主动中断，避免继续重复付费。原任务停留于未完成的 dev_design，保留状态与证据，不改为 succeeded。

已读取并核对 [DeepSeek 官方 Chat Completions 参数文档](https://api-docs.deepseek.com/api/create-chat-completion/) ：非思考模式未指定 max_tokens 时默认 8K，length 表示达到输出或上下文上限；当前 DeepSeekRuntime 未显式设置 max_tokens。网页通过直连 httpx 读取，副本为 `/private/tmp/deepseek-chat-completion-doc.html`。本次直接响应中的 8,192 上限和截断事实是主证据。

## 二、隔离诊断副本：开发反复读取

入口：`tests/tool_summary_deepseek_resume.py`。目录：`/private/tmp/content-workbench-summary-deepseek-diagnostic-20260917`。日志：`/private/tmp/tool-summary-deepseek-diagnostic.log`。

复制原任务和证据，在副本中修正检查点归属，并仅为该测试进程设置 `max_tokens=16384`，继续累计预算。未改正式模型配置，未编辑生成文档或代码。这是调整参数的诊断，不算原流程无干预成功。

第 19 次请求完成 Dev Design，随后进入开发。生成 7 个代码文件后不再前进：最后一次产品写入后，连续 137 次 read，循环读取同一组 7 个文件；每个文件重复 18～21 次。第 75 次请求期间主动停止，完整产品入口、测试和浏览器验证均未生成，无法执行新软件操作验收。

发送体核对：较早工具全文已经被摘要替代，最多 20 条较早摘要，实际消息最多 14 条；文件清单随生成文件刷新。新工具 schema 已提供给模型。摘要压缩机制确实生效，但没有带来任务完成。开发期间模型未使用三个历史查询工具。

主要证据：上述目录 `context-audit.json`、`sent-requests/`、`workspace/1/evidence/develop-1-checkpoint.json`、`workspace/1/evidence/tool-summaries.jsonl` 与完整 Trace。摘要账本记录了实际读取，未伪造成功或丢弃原始证据。

## 三、强制历史查询探针：工具成功、模型闭环失败

入口：`tests/tool_summary_deepseek_probe.py`。目录：`/private/tmp/tool-summary-query-probe-20260917`。日志：`/private/tmp/tool-summary-query-probe.log`。

构造两次真实工具写入：历史版本和当前版本。初始发送上下文中历史原文已压缩为摘要，当前原文仍在最近完整批次。要求 DeepSeek 实际查询文件历史、历史模型调用批次、原始历史写入参数，再用 read 读取当前文件，最终返回两种内容。

三个查询和 read 各调用 4 次，16 次工具均成功。直接检查原始结果确认历史详情返回正确旧原文、read 返回正确当前原文，工具调用归属及 Trace 引用正确。

但模型在「历史／批次查询＋read」与「取详情」两批之间重复切换，8 次实际模型请求预算耗尽，最终没有给出答案，抛出 `model_call_limit_exceeded`。所以不能把工具返回成功等同任务成功。

证据：上述目录 `summary.json`、`combined-usage.json`、`sent-*.json`、检查点、账本和完整 Trace。

## 判断与下一步（待用户决定，未实施）

两个场景均显示模型不能持续积累跨批次所需的读取内容。当前仅保留最近一批全文，前一批读取很快变成不含内容的摘要；探针第二批获得旧内容时，第一批当前内容已被压缩。证据支持近期读取过早淘汰是主要问题，但尚未执行修改前后对照，不声称已经证明唯一原因。

建议下一步将近期成功 read 结果按文件与实际哈希保留，文件变化时失效，并设置总字符预算；历史 write 参数与 exec 结果继续摘要。仅增加查询工具不能解决本次已经观察到的循环。具体保留范围、预算与淘汰规则需要用户确认设计后再实施。文档输出上限与连续无进展停止策略属于另外两个暴露的问题，本次未修改。

## 验证与限制

115 项机制回归再次通过，新增手动脚本语法与 `git diff --check` 通过。真实模型结果说明机制回归不能代替产品能力测试。测试失败后未改服务代码，因此不重启正式服务。旧任务状态未改，未自动续跑正式失败任务，也未回滚已部署实现。

本次完整自主生成未通过，生成软件的 Node／HTTP／Chromium 验收未执行。此前已有产物的通过记录不能替代本次验证。Windows、用户本人验收及策略调整后的真实效果未验证。
