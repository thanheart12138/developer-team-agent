# 只提供当前必要上下文：真实 DeepSeek 对照

## 授权与试验边界

用户授权尝试「不携带最近的内容，只携带当前需要的内容」并重新测试。手动入口 `tests/unit_workflow_deepseek_validation.py --current-only`，只在隔离进程替换投影和提示，正式服务未切换。共用此前累计 300 次 HTTP 上限，已有 40 次计入，重试同样计入。

变体不自动携带历史 assistant/tool 消息、历史执行摘要或最近写入的完整参数／成功确认。保留当前正式需求与单元／依赖设计、当前单元及直接依赖文件快照、最新全产品文件清单、测试失败反馈和未解决工具失败。模型明确提出的最近 read／历史查询结果作为 current_requested_data 返回，保障按需获取数据；它们不作为完整历史多轮累积。执行账本、原始 Trace、检查点照常保存。不是删除所有信息，也不是修改正式工具权限。

## 同一固定设计开发对照

新目录 `/private/tmp/unit-workflow-current-only-probe-20260917`，日志 `/private/tmp/unit-workflow-current-only-probe.log`。预置与旧探针相同的需求、三单元计划、共享契约及单元设计，从空产品文件开始，由真实 DeepSeek 开发。

实际 65 次 HTTP（全局编号 41—105），输入 433,538、输出 14,329、总量 447,867 Token。最终 waiting_acceptance，无失败原因，系统 test、start、verify 均运行，生成 Node 18 项通过。产品 URL `http://127.0.0.1:51567`，产品 PID 90674。

65 份实际发送体逐一核对：messages 只有 system／user，没有历史 assistant/tool 消息，自动工具摘要 0，文件快照未因近期完整交互去重省略。审核 `payload-history-audit.json`。模型多次重复读取已存在的文件，文件齐备后仍继续读取，最终自行结束；没有人工修改生成代码或替模型强制完成。

独立 Node 18 项、独立 Chromium 18 组确认需求操作通过，浏览器页面异常 0。浏览器检查正负数、±1000 边界、空白／非数字／小数／正负越界提示及每次非法输入后恢复。证据 `independent-node.json`、`independent-browser-300.json`、截图；脚本 `/private/tmp/unit-workflow-current-only-browser.py` 使用单独临时服务，检查后关闭该服务，未改变 Worker 运行状态。

旧摘要策略同固定设计任务共 13 次实际 HTTP，输入 55,500、输出 7,818、总量 63,318 Token（前 10 次中断于试验预算，追加 3 次恢复完成）。本样本新策略调用数为 5 倍，总 Token 约 7.07 倍。相同预置设计，但旧任务有预算中断／恢复，模型随机输出、测试数量和代码也不同；不是多次随机种子控制的严格 A/B，不据此声称所有任务都会恶化。这个样本不支持取消历史上下文。

后续请求体检查发现 106 个 read 结果全文与当前文件快照重复，因此第一变体存在额外输入干扰，不能将 Token 增加直接归因于取消历史。追加去重变体：保留读取状态、路径及哈希，重复全文改为 current_product_files 引用；不在快照中的当前请求数据仍返回全文。先更新此试验约定，再修改手动入口并从空文件重测同一固定设计。已运行的第一变体结果保留，不覆盖。

## 无预置设计流程复测

目录 `/private/tmp/unit-workflow-current-only-full-20260917`，日志 `/private/tmp/unit-workflow-current-only-full.log`，从同一正式需求进入架构，不预置架构／计划／设计。新增 7 次 HTTP（106—112），最终 failed／architecture_docs，unit_plan_validation_failed。三次候选单元 id 使用 math.add、math.squareSum 等含点或大写标识，违反现有校验，均返回 unit_plan_invalid_unit；后续候选还存在整模块与功能混排，但首先被 id 校验拦截。纠正三次仍未解决。Trace 000022、000025、000028-validation.json 保留。此阶段本来没有工具执行历史，取消历史不能解决计划结构错误，完整自主流程未通过。

## 去重后的固定设计复测

目录 `/private/tmp/unit-workflow-current-only-dedup-20260917`，日志 `/private/tmp/unit-workflow-current-only-dedup.log`。与旧固定设计相同输入，从空产品开始，已去掉当前 read 全文与文件快照的重复。100 份发送体逐一确认：历史 assistant/tool 消息 0、自动工具摘要 0、重复读取全文 0，审核 `payload-history-audit.json`。

实际新增 100 次 HTTP（113—212），输入 552,716、输出 18,450、总量 571,166 Token。加法与平方程序单元测试通过；UI 实现及测试、入口、实现说明和验证脚本均已生成，但模型反复读取，不自行结束。共 write 9、read 208、系统 exec 2，最终 failed／develop，model_call_limit_exceeded。既有单阶段 100 次逻辑上限未改变；累计实际 HTTP 212，未触及全测试 300 上限。没有人为强制进入下一阶段或续跑失败任务冒充成功。

独立诊断产物 Node 18 项与 Chromium 18 组确认需求操作通过，页面异常 0。诊断没有替代自动 UI 单元验证／最终 test、start、verify，这些自动阶段未完成。证据 `independent-node.json`、`independent-browser-300.json` 和截图；脚本 `/private/tmp/unit-workflow-current-only-dedup-browser.py`，自建临时 HTTP 服务已关闭。

去重变体本样本 Token 为原摘要固定设计样本的约 9.02 倍，且流程未完成。不同随机输出、代码与测试数量、旧任务预算中断仍是对照限制，不能把倍数当作普遍结论。两个样本均不能支持切换正式服务到只提供当前上下文；下一步方案需另行讨论，不在本次测试中增加生产机制。

## 用量汇总

本次三轮新增 172 次，输入 1,014,125、输出 46,941、总量 1,061,066 Token。加上此前 40 次，累计实际 HTTP 212 次，输入 1,189,883、输出 100,781、总量 1,290,664 Token；上限 300 次。212 次均有完整 usage。汇总 `/private/tmp/unit-workflow-current-only-usage.json`，失败消耗也计入，没有将独立 Node／浏览器诊断计为模型调用。

## 项目验证与限制

后端 pytest 137 项通过；手动入口语法、差异检查通过。正式 Worker 未切换／重启，无业务库或 schema 改动，用户本人验收未执行。预置设计探针不能证明自主架构和设计能力。
