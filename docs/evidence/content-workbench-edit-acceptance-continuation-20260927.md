# 内容工作台编辑验收门禁与 DeepSeek 返修续测

日期：2026-09-27。依据用户确认的现有需求：素材和选题的已有记录必须能在页面中编辑。本轮从 2026-09-26 隔离 DeepSeek 任务的 `waiting_acceptance` 产物继续，未重跑从零任务；所有模型调用由测试进程走 DeepSeek thinking，累计 HTTP 上限 150 次、单阶段逻辑调用上限 100 次。原任务和 Luna 对照结果见 [上一轮报告](content-workbench-optimization-rerun-20260926.md) 。

## 独立验收输入与复现

新增 `tests/content_workbench_edit_acceptance.py`，使用本机 Chrome 的 Playwright 独立浏览器 context。在页面新增素材后要求从该条记录进入编辑，修改笔记并保存；记录数不得增加，刷新后仍可按新笔记检索。选题同样须从已有记录进入编辑，修改角度及优先级，保存后不增加记录、刷新后保留。测试预期来自已批准产品需求，不从生成实现反推。对初始产物和最终产物运行均在第一个编辑入口断言失败：`material_edit_entry_missing`；代码检查也确认素材和选题视图仍只调用 `repo.create`，没有已有记录的编辑入口。由于第一步失败，脚本后续选题编辑断言未实际执行；选题缺口有静态代码证据，但不记为独立浏览器通过或失败的完整实测。

隔离基准脚本增加 `--verify-edit`：任务进入 `waiting_acceptance` 时执行上述真实浏览器检查，保存原始输出；仅在明确的 `material_edit_entry_missing`／`topic_edit_entry_missing` 断言下通过正式 `acceptance_result` 事件提交未通过反馈。检查环境异常不冒充产品缺陷；拒绝次数有界。该专用门禁只用于当前内容工作台基准，不把素材／选题规则硬编码进通用 Worker。

## 返修过程与机制修复

1. 首次验收反馈把实际行为、预期行为及复现证据写清，DeepSeek 规划器仍把 `inspect` 输出为 Markdown 伪工具调用，而协议要求纯 JSON。两次无效响应后任务进入 `waiting_user`。补清原有 JSON 契约并用测试控制重述同一需求和复现后，规划器读取代码，将问题分类为 `implementation_defect`／`modify_code`。此重述发生在产品阶段以后，故后续不计为「无人干预」证明。
2. 返修中的大文件修改按提示使用 `replace`，但无进展保护只把 `write` 计作成功写入，误拦截后续动作。修复为成功 `write` 或 `replace` 均重置计数，相关回归测试通过。
3. 生成的验证脚本自行启动 HTTP 服务、忽略 Worker 传入的产品 URL，并在本机缺少 Playwright 自带 Chromium 时输出小写 `[skip]` 后返回零。Worker 只拦截大写 `[SKIP]`，曾错误进入验证成功状态。现有 Dev Design 本就禁止脚本自建服务；预检加入 HTTP 服务创建检测，首次验证与切片返修复验共用预检和执行结果判定；标准输出或标准错误含任意大小写的 `[skip]` 均不得通过。旧产物实测得到 `verification_script_starts_server:68`，后来修改版本得到第 71 行与第 143 行的同类错误。
4. 切片返修复验失败原先直接抛异常终止，不走已有三轮返修预算。已改为保存最新错误后调用 `fail_or_repair`；测试证实第 1 轮失败会进入第 2 轮。原隔离任务因旧代码已失败，测试控制使用诊断恢复入口继续，属于额外介入，不改变原先从零测试的结论。

后端全套回归 221 passed，`git diff --check` 通过。每次服务代码验证后均先核对正式 MySQL 待处理事件 0、运行中任务 0，再重启正式 Worker；最终启动 PID 19087。正式业务任务未被续跑或改状态。未安装新依赖、未修改密钥或数据库 schema。

## 真实调用结果

| 节点 | 累计 HTTP | 已报告总 Token | 状态与证据 |
| --- | ---: | ---: | --- |
| 初始从零任务 | 57 | 4,752,915 | `waiting_acceptance`，但缺少页面编辑入口 |
| 首次验收反馈及返修 | 88 | 以最终累计为准 | 规划器经一次技术澄清进入 `modify_code`；验证脚本输出 `[skip]` 被旧门禁误判通过，Bug Planner 再转 `waiting_user` |
| 第二轮返修 | 107 | 9,525,179 | `failed / develop / slice_repair_validation_failed`；新预检检出验证脚本自行开服务，旧路由提前终止 |
| 诊断恢复后的有界续跑 | 128 | 12,026,798 | `failed / develop / unit_development_no_progress`；模型持续修改验证脚本，未补页面编辑入口 |

最终 usage 汇总：输入 11,365,316、输出 661,482、总计 12,026,798 Token；128 次 HTTP 对应 125 份有 usage 的模型响应，Provider 未提供美元费用。相对第 57 次节点，后续增加 71 次 HTTP、7,273,883 个已报告 Token。原始状态、响应和工具动作保存在 `/private/tmp/content-workbench-optimized-deepseek-20260926/summary.json`、`test.db` 及 `workspace/1/traces/`；最终失败见 Trace 000662，预检失败见 000566。最终独立浏览器再测仍为 `material_edit_entry_missing`。

## 结论与未解决问题

门禁机制现在能阻止已知的跳过浏览器和自建服务脚本，并在内容工作台基准中独立发现素材编辑缺口；这些机制已实现并验证。真实 DeepSeek 返修没有完成产品目标，不能称为已交付或已验收。续跑含测试控制对技术澄清的重述和失败任务的诊断恢复，不能作为「产品阶段后无人干预」成功样本。

当前的架构问题是验收反馈、最新验证脚本失败和开发切片之间的目标保持：原始的「页面缺少编辑」缺陷进入 `modify_code` 后，后续切片返修主要围绕 `verify_product.py` 与临时服务修改；原始缺陷没有作为必须闭合的独立条件持续约束完成。下一步应由用户决定如何在正式设计中同时保留验收缺陷与脚本错误的未解决账本、如何核验两者均闭合，再实施；本轮不继续重置失败任务或放宽预算。
