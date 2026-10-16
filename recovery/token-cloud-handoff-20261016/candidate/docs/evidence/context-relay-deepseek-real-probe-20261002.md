# 上下文接力：同断点真实 DeepSeek 有界验证

日期：2026-10-02。授权：用户确认最多 12 次真实 API 请求，重试计入；沿已有产物失败断点执行，不从零重跑、不人工改产品代码或代提交。

## 结论

**在 12 次请求上限内未完成模型交接。** 模型完成五次替换，把当前固定 Node 诊断从三项失败修到 86／86 通过，但没有调用 `run_unit_tests` 或 `submit_unit_for_test`。隔离任务终态为 `failed / develop / model_call_limit_exceeded`；原目标 E4-1 仍 open，完整自动流程和正式关闭审查未完成。

本次消耗 444,711 Token，比上次同起点、同 12 HTTP 样本的 621,348 少 28.43％。实际协议和文件上下文接力工作，但单次样本不能证明稳定节省成本或提高成功率。

正式浏览器验证入口及按原需求编写的独立素材／选题编辑操作复验均通过。原编辑实现已存在于起点，本次没有修改业务实现；不能把此前修好的编辑功能计为本轮新完成的产品修复，也不能用独立复验补记模型自测或提交。

## 输入和隔离

- 源目录：`/private/tmp/repair-objectives-completion-deepseek-20260930`，复制 20 个产品文件和原文档、目标、失败证据，SQLite 使用只读备份。
- 本轮目录：`/private/tmp/context-relay-deepseek-20261002-_6ip7z8p`，目录约定记录在 `STRUCTURE.md`。
- 已核对 20 个源文件哈希与上一轮 `repair-diagnostic-deepseek-20261002-r94q4iem/baseline.json` 完全一致，采用同一个起点。
- 新隔离 StepRun 19／attempt 6，新增 Trace 从 933 之后汇总，不计入复制的旧模型成本。新检查点为 `workspace/1/evidence/context-relay-checkpoint.json`，不接入旧循环。
- 使用当前实际 `slice_workflow.handle_repair`、Worker、DeepSeek Runtime、工具与门禁，Developer v12。探针仅在真实提交后停止；失败时达到上限停止，没有追加请求。
- `deepseek-flash`、thinking enabled，未指定 effort；显式 `max_tokens=65536`，等于官方 thinking 默认输出上限。未修改正式 Runtime、密钥或配置。
- 认证由现有受控凭据读取，认证头不进入记录；请求、响应和完整思考只存临时实验目录，不进 Git。

官方字段及续传要求核对了 [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/) 和 [thinking 工具协议](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/) 。当前会话保留所有原始思考与成对工具消息，新消息上下文不续接边界前的旧消息。

## 实际运行与用量

| 项目 | 本轮 |
|---|---:|
| HTTP 请求／有 usage 响应 | 12／12 |
| 输入／输出 Token | 415,966／28,745 |
| 总 Token | 444,711 |
| 输入缓存命中／未命中 | 81,536／334,430 |
| 模型 read／replace | 16／5 |
| 成功读取／失败读取 | 13／3 |
| 模型主动自测／提交 | 0／0 |
| 程序诊断执行 | 4 |
| 修改文件 | product.test.js、implementation.md |
| 完整边界／实际新会话请求 | 3／2 |
| 耗时 | 141.58 秒 |

Provider 未报告美元费用，本记录只统计实际 usage。

### 时间线

1．入口固定 Node 诊断有三项失败：旧脚本自建服务要求、旧 `--serve` 测试、浏览器日志匹配。
2．第 1 至 6 次响应仅读取。第 2 次两项 read 只给 `end_line=200`，未给 `start_line`，真实工具返回 `invalid_line_range`；后续读取修正参数后成功。
3．第 7 次修改 `product.test.js` 与 `implementation.md`，对齐当前 Worker 托管服务的契约。整批后诊断仍有两项失败；边界完整落盘。
4．第 8 次请求开始新消息上下文，旧 assistant／tool 消息为空，已知代码范围按当前版本提供。请求的 `product.test.js` 第 620 至 720 行已经包含在接力的第 600 至 760 行正文中，被正确拦截一次；未提供的范围读取成功。
5．第 10 次改写旧 `--serve` 测试夹具及 URL 日志断言，程序诊断剩一项编辑日志匹配失败。第 11 次开始第二个新会话，读取新报告及必要测试范围。
6．第 12 次将素材／选题编辑证据断言对齐脚本真实输出中的引号和完整文字。程序诊断 86 tests、86 pass、0 fail、0 skipped、0 todo；保存第三个完整边界，此后没有第 13 次 API 请求。
7．模型循环达到预算上限而失败，未主动自测或提交。没有把程序诊断通过改成模型完成。

两项旧系统职责测试按已确认契约修正，保留真实服务夹具、浏览器执行、页面编辑、刷新持久化和不跳过的断言。日志调整依据真实失败输出；未删除业务预期或使用恒真断言。

## 上下文机制的实际证据

- 新会话实际发送在第 8、11 次，分别只有 system／user 消息，`reasoning_content` 和 tool 结果历史字符为零。
- 接力范围第 8 次为 6 段，第 11 次为 7 段；包含以前实际读到的代码和报告，不增加全部未读文件全文。
- 25 项接力产品版本检查均与各次请求的当前文件清单哈希一致。
- 144 项原始思考、工具参数和结果对照检查均一致；原检查点完整保留，没有选择性删某轮思考。
- 所有 12 次请求都保留 E4-1 原目标，写权限清单未变。
- 协议消息中的读取结果在 `current_requested_data` 变为调用 ID 引用，最近读取仍完整位于 tool 消息。
- 接力带来的 user 正文不是恒定小体积：第 8 次 89,268 字符、第 11 次 102,983 字符，包含已读代码及报告。读取阶段历史仍增长，不能声称已解决全部上下文成本。

审计摘要：`audit-summary.json`；逐请求状态：`request-stats.json`；完整边界：`workspace/1/evidence/deepseek-context-session-19-*.json`。

## 独立产物复验

在模型循环停止后，用本实验自己的静态服务托管隔离产品，服务验证完成后关闭，无额外模型调用：

- 当前正式 `verify_script_preflight` 返回无错误；通过实际 `run_product_browser_validation` 使用位置 URL 执行生成脚本，真实浏览器入口通过，无 skip。
- 独立 Chrome 创建素材与选题，通过页面编辑入口修改素材笔记、选题角度和高优先级，显式保存、不新增重复记录，刷新后结果保留，页面异常为零。
- 复验预期来自保留的原始 E4-1 和已有独立验收脚本，模型未修改这份独立验收脚本。
- `repair-objectives.json` 仍 open，没有调用模型关闭审查、添加自测／提交记录或推进正式任务。

证据：`independent-validation.json`、`independent-inline-edit.log`、`independent-check.py`。独立通过是产物证据，不是自动交接成功。

## 与上次样本比较及原因边界

| 指标 | 上次 v11 | 本次 v12＋接力 |
|---|---:|---:|
| HTTP | 12 | 12 |
| 总 Token | 621,348 | 444,711 |
| 首次修改 | 第 10 次 | 第 7 次 |
| 最后程序诊断 | 3 项失败的入口报告，修改后未新验证 | 86／86 通过 |
| 模型主动自测／提交 | 0／0 | 0／0 |
| 耗时 | 109.94 秒 | 141.58 秒 |

已验证的判断：更早修改、修改后诊断逐步消除错误、消息接力真实触发、Token 在这一样本中减少。尚未完成的目标：上限内主动自测并交接。

从实际轨迹看，前六次主要读取，加上两次参数错误和后续分轮对齐日志，最终诊断在第十二次才通过，停止前没有进入主动自测／提交。不能仅凭这个上限断言模型无法完成，也不能假设再给一两次就一定能交接。当前仍须区分长读取、提示与参数使用、完整反馈后的行动，以及有界测试的观察窗口。

两轮同时改变了提示词、返修输入、诊断和接力机制，模型轨迹与缓存命中也不同；不是单一机制的严格 A/B，28.43％不能直接归因于接力或推广为稳定收益。输出上限未发生 length 截断。本轮没有为取得成功追加预算、改提示词、人工修产品或代提交。

## 完整证据及隔离复核

临时目录保存 `probe.py`、`baseline.json`、`run-baseline.json`、`run.log`、`result.json`、`call-count.json`、`sent-requests/001.json` 至 `012.json`、`request-stats.json`、`audit-summary.json`、独立复验与 `isolation-verification.json`。临时目录可能被系统清理，必要结论与复现说明保留在本仓库。

源产物 20 个文件哈希未变；正式数据库任务状态／阶段／版本、Trace 数量与实验期间只读基线一致，仍为 0 待处理事件／0 运行任务，Worker 50890 日志为空。本轮未改服务实现，不重启正式 Worker，没有修改正式数据库或续跑正式失败任务。
