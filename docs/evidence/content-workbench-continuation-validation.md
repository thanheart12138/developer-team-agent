# materials 成功产物后的剩余切片续跑

日期：2026-09-20。状态：用户明确批准外发后已真实续跑；任务／选题切片通过，看板／页面切片因响应截断后的单次调用限制失败，完整产品未交付。

## 授权范围与预算

用户在讨论“保留基础模块和 materials、让系统继续规划和开发剩余切片、由 UI 所有者接通页面，最后实际浏览器验收”后明确指示「继续」。本轮为已有成功产物的增量续跑，不是从零生成，不由开发助手人工补生成产品代码。

新增最多 60 次 HTTP 请求，包含传输重试；原 Develop 已用的 8 次逻辑调用保留，正式 Step 上限不变，每次控制流切换后最多四次实现／修复不变。密钥仍通过已有受控文件使用，不更改、不输出、不写入模型载荷。

## 已完成的零模型准备

- 来源：`/private/tmp/materials-control-switch-v1-20260920`。
- 新隔离目录：`/private/tmp/content-workbench-control-switch-continue-20260920`。
- 入口：`tests/content_workbench_continue_validation.py`。默认只准备，`--run` 才执行真实请求；不被 pytest 自动收集。
- 原 workspace 和 Trace 复制到新目录，使用 SQLite 只读备份接口复制测试数据库，原失败／成功证据保留。
- 用原 `restore_submission` 校验材料切片提交及全部测试范围文件哈希；随后真实 `run_unit_tests` 和独立 Node 回归均通过，26 项、零 todo。
- 依据原真实提交和新独立复验，将 materials 登记为已通过；其余两张已通过基础切片保留。此操作属于测试入口对已有交付的证据导入，不是新模型自主完成，也没有伪造测试结果。
- 更新的仅为新隔离任务的工作区／检查点路径和恢复状态；生成产品代码未修改，正式 MySQL、主工作区 API／Worker 未改。
- 首个待执行动作是正式 Slice Planner 规划下一片。项目机制回归仍以前一轮 241 项通过为依据，本轮未改变 Runtime 实现。
- 续跑脚本 Python 编译、差异检查通过；实际准备入口已执行通过。

## 网络执行阻塞

第一次运行 `--run` 时自动审批拒绝，理由是向外部 DeepSeek 发送扩展的需求、架构、执行卡、代码和测试，需要具体载荷授权。命令未启动、请求未发送。

随后只读提取正式 Slice Planner 的待用输入范围并核查生成文档。预览含约 29,919 字符，字段包括生成产品需求、生成架构、骨架契约、已通过切片、产品文件哈希及剩余 todo；Planner 不开放工具。预览使用当前默认约束，实际基准执行会采用此前已确认的原生多模块／localStorage 约束。核查未发现凭据路径、token、私钥或认证头，也未读取真实个人业务数据。

将原始用户授权及核查证据提交自动审批后，第二次仍被拒绝。审批明确指出：即使没有凭据或个人数据，这些仍属于私有项目需求、架构和后续代码测试；要求用户在看到具体外发范围和 DeepSeek 目的地后明确批准。

当时没有绕过审批、换网络工具或间接发送，新增模型请求为零，不将审批拒绝记为 DeepSeek 能力失败。随后向用户说明外发数据范围为隔离生成产品的需求、架构、执行卡、代码及测试，目的地为 DeepSeek，新增最多六十次请求（含重试）；用户明确回复「同意」，审批通过后执行原入口。

## 真实续跑结果与失败原因

- 新增 16 次 HTTP、302,495 tokens，最终 `failed / develop / model_loop_call_budget_exceeded`；未用完六十次预算，Develop 累计逻辑调用为 24。旧样本费用未混入本轮。
- `tasks-and-topics`：普通 Developer 重复读取并违反推进约束后切换；独立实现第一次写两个模块，第二次写两份真实测试，Runtime 自测／提交和独立回归通过，累计 40 项通过、零 todo。证据为 `workspace/1/evidence/slices/004-tasks-and-topics-attempt-1.json`。
- `dashboard-and-app-ui`：同样成功终止旧读取对话。受限实现第一次写看板和页面实现，但仍有 14 个 todo；第二次只写看板测试，测试在非 async 函数内使用 await，产生 SyntaxError，同时引用未生成的 helpers 文件，UI 仍有九个 todo。
- 第三次受限实现响应尝试修复测试并补 UI，Provider 返回 `finish_reason=length`，completion_tokens 为 8,192，工具 JSON 被截断。Trace 172／173 保存中断及 `invalid_tool_call` 原文，该批没有执行写入。
- Runtime 的每批 `max_calls=1` 已用完：协议错误分支试图进入下一轮，但循环条件拒绝，最终抛出通用 `model_loop_call_budget_exceeded`。此时受限实现只用了三次，并非四次预算或六十次总预算耗尽；错误标签掩盖了直接原因。Trace 174／175 保存最终失败。
- 停止后独立 `node --test`：40 pass、1 fail、9 todo，退出码 1，完整输出在 `independent-final-node.log`。没有人工补生成代码，没有启动产品或宣称整页验收成功。

结论：本轮再次证明终止旧对话后可以产生并提交有效实现，但不证明完整产品成功。新增阻塞是输出截断与受限批次协议恢复之间的控制流问题；建议在既有四次预算内明确失败分类和下一批恢复语义，并限制每批输出规模。该建议尚未由用户确认、未实施，不通过重置计数或增加预算绕过。

## 证据与尚未验证

- `continuation-input.json`：源样本、既有调用数、预算及起始文件哈希。
- `workspace/1/evidence/slices/003-materials-continuation-revalidation.json`：新独立 Node 测试及版本证据。
- `planner-payload-preview.json`、`payload-review.json`：离线输入预览及核查结果。
- `summary.json`、`new-call-count.json`、`sent-requests/`、新增 Trace 66—175：本轮请求、用量及停止证据。
- 尚未通过：看板／页面切片、全量集成；尚未执行：正式启动、整页实际操作及用户验收。

上述原始证据在临时目录，可能被系统清理；本报告保存关键事实与阻塞原因。

## 后续局部替换提示调整

用户要求提供局部替换工具或强化优先使用的提示。核查确认受限执行器已开放 `replace(path, old, new)`，要求 old 唯一精确匹配；v1 原有一句「局部修改优先 replace」，失败样本仍选择整文件 write。按授权新增并激活 v2，明确局部修复使用最小片段、按顺序匹配最新内容，不用整文件 old/new 绕过；write 保留给新文件或绝大部分仍待实现的骨架。未移除工具权限，未改变四次预算和协议失败恢复路径。

`tests/test_prompt_registry.py` 与 `tests/test_slice_control_switch.py` 共 21 项通过，差异检查通过；没有新增付费请求，不将机制测试当作模型遵循提示或避免截断的证据。

### v2 真实局部回放

用户随后要求局部测试。在 `/private/tmp/replace-prompt-v2-local-20260920` 复制失败时产品文件，回放原第 16 次请求，仅把 system 中完整 v1 模板替换为 v2；其余上下文、工具定义和模型参数保持原样。使用正式 DeepSeekRuntime 解析响应、RestrictedImplementationTools 执行写入和独立 Node 自测，不续跑 Planner、提交或整页验证。入口为 `/private/tmp/replace_prompt_local_validation.py`，请求上限两次，实际一次、无重试；这是隔离单批回放，不恢复或重置原任务四次预算。

- 本次输入 30,327、输出 860、合计 31,187 tokens，finish_reason=tool_calls，无截断；原失败响应输出为 8,192 tokens。
- 模型返回两次 replace，均只修改 `product/tests/dashboard.test.js`，唯一精确匹配成功，没有 write。修复不存在的 helper 引用、配置真实模块依赖及非 async 函数中的 await；原五个测试断言保留，没有删除或跳过。
- 独立 `node --test`：45 pass、0 fail、9 todo，退出码零。看板五项测试恢复通过，UI 九项 todo 没有实现，不能把退出码零当作切片完成。
- 单样本支持“新提示在这次修复中促使局部替换并避免截断”，不证明稳定性。输出减少也伴随完成范围缩小：本次没有尝试补齐 UI 测试，不能将 860 对比 8,192 解读为同等交付量的纯效率提升。

原请求、响应、动作结果、文件变化和独立日志保存在该目录的 `request.json`、`response.json`、`summary.json`、`node.log`。没有人工修改生成产品，没有追加第二次付费调用。

## 用户要求推送后恢复原全流程

2026-09-20，用户要求推送代码并继续先前中断的 DeepSeek 全量测试。完整项目回归 241 项通过；代码提交 `7c4d0a9` 推送至 `thanheart12138/developer-team-agent` 的 `codex/slice-control-switch` 分支，main 未改变。首次推送被自动审批要求明确目的地和完整载荷，用户明确确认后推送成功。

在原隔离续跑目录保存 `before-user-resume-v2/`（SQLite 备份、失败状态、用量和原摘要）及 `resume-v2-manifest.json`，核对生成文件哈希未变化。仅按用户显式续跑要求开放原失败尝试的剩余额度：HTTP 16／60、Develop 24／100、受限实现 3／4 原样保留，将任务／Step 恢复 running、该受限状态恢复 ready。不修改正式数据库、Runtime 恢复策略或生成产品；局部回放修复没有导入。

正式 Worker 新增一次请求，输入 30,321／输出 410／合计 30,731 tokens，finish_reason=tool_calls。两次 replace 只修改看板测试：移除函数内非法 await 并合并 import，却继续引用不存在的 `tests/helpers/dashboard-import.js`，未生成真实依赖接线。Runtime 自测及停止后独立 Node 均为 40 pass、1 fail、9 todo；错误变为 `ERR_MODULE_NOT_FOUND`。UI 九项 todo 未补齐。

此时实际用完第四次实现，最终 `failed / develop / slice_restricted_call_budget_exceeded`，本次是真正的四次额度耗尽，与上轮截断后通用错误不同。续跑累计 17 次 HTTP、333,226 tokens（不含独立 v2 局部回放的一次／31,187 tokens）；未到正式全量测试、启动及浏览器阶段。新 Trace 从 176 开始，独立日志 `independent-resume-v2-node.log`，最新 `summary.json` 保存累计状态。没有重置计数、额外第五次调用或人工补写。

本次再次支持 replace 提示可以改变工具选择并缩短输出，但也表明局部一次修复成功不等于稳定修复：相近输入下仍可能只修表层语法、遗漏真实依赖。完成整张切片所需的后续尝试或预算策略待用户决定，不能把剩余总 HTTP 额度自动变成新的切片额度。
