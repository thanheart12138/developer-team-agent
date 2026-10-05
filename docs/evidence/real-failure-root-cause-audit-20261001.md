# 真实返修失败的原因与定向修复

## 范围与结论

用户要求先分析已有真实调用，再解决有证据的问题。本轮逐项核对 2026-09-30 两次隔离 DeepSeek thinking 返修的请求、响应、工具结果、摘要和生成测试；没有新增模型调用、扩大预算或恢复旧任务。

不能把失败单独归因于模型能力。已有生成的素材／选题编辑在独立操作中通过，说明模型完成了部分实现；失败发生在环境、自测判断、冲突测试处理及显式交接上。模型的证据理解和行动收敛也有直接负面证据，但没有同条件模型对照，不能量化它与提示词／上下文的贡献，更不能由局部成功断言完整软件正确。

## 已核对的原因

| 类别 | 直接证据 | 判断及当前处理 |
|---|---|---|
| 执行环境 | 首次返修 Trace 765：外层 succeeded，内部 passed=false、Node exit_code=1，输出含 `No module named 'playwright'`。生成测试的 findPython 优先从 PATH 选择 python3，未检查 Playwright；Worker 的 `.venv/bin/python` 启动方式没有使子进程 PATH 优先使用虚拟环境 | 实际自测环境错误，不是缓存。现已修正受控 run／start 的子进程 PATH，沿用 Worker Python，不修改系统环境 |
| 提示词与旧卡契约 | 第五卡要求 verify_product.py 提供静态服务；当前 Worker 负责服务。第二次独立 Node 的三项失败包含两项旧托管要求和一项日志文字匹配，真实当前 URL 浏览器操作实际通过 | 模型必须同时处理相互冲突的要求。9 月 30 日已注入统一当前契约并激活 Planner v6／Developer v9，允许在原权限内纠正系统执行要求；尚未真实复测这些修正后的交接效果 |
| 重复上下文 | 首次第 2 次请求 current_product_files 为 261,545 字符；两次第 2／20 次请求 input 与 context.card 均是同一张 22,339 字符卡 | 全文按需读取已于 9 月 30 日修复；本轮普通切片及返修只在 context.card 保留卡片，input 引用它。每轮少发送一份卡片，不等于已证明相应 Token 降幅 |
| 修改记忆缺失 | 首次新 StepRun 的 39 条 replace 记录（含失败／阻止）没有 file_path、before_hash、after_hash；文件历史和上下文投影仅处理 write／read | 模型无法从摘要核对局部修改，容易追加历史查询；但不能断言这导致了全部重复读取。现已登记 replace 的真实前后哈希，进入修改历史及 latest_write |
| 自测摘要误报 | Trace 765 实际失败，对应账本仍为 `run_unit_tests: succeeded`，没有内部退出码或错误摘录 | 原始完整结果并未丢失，但短摘要误导。现已按真实 passed 标记摘要失败，保留内部命令错误、失败附近输出和实际测试范围版本；外层工具状态仍表示调用是否完成 |
| 局部读取摘要失真 | 第二次读取 verify_product.py 的 200—430 行，摘要 truncated=false 却无范围；旧投影将其标为 complete=true | 一段正文被描述为全文件已读。现已保留范围，只在完整覆盖且未截断时标 complete；缺少范围依据的旧摘要不证明全文读取 |
| 循环控制 | 首次有 8 个动作、第二次有 7 个动作被 repair_tool_loop_no_write 拒绝，包含必要读取、自测或 replace。第二次思考提出通过写说明恢复读取额度 | 保护规则诱发绕行。显式提交流程的叠加五动作门禁已于 9 月 30 日取消；保留重复内容／动作、无进展、版本和总预算保护。本轮未改变交接状态机 |
| 模型行为 | 首次真实失败输出已经进入 unit_self_test，模型却将结果解释为缓存／旧结果；第二次虽每轮都有 next_action=run_unit_tests，但 20 HTTP 内执行了 28 次 read、4 次 replace、2 次 write，零自测、零提交 | 有证据表明 DeepSeek 的证据理解和收敛不足，不能全部归咎于程序。补充工具状态与测试通过的区别，不把停滞视为完成；是否改善仍需后续有界真实证据 |

两次直接终止原因都是 model_call_limit_exceeded：分别报告 3,484,768 与 1,167,148 Token，均为 20 HTTP。调用上限只是终止条件；增加预算不能证明能消除上述问题。第二次从已修编辑产物出发，两组不是严格成本对照。协议要求的 DeepSeek 思考／工具历史仍保留，未通过删历史来压低成本。

另一个当前实现一致性问题：普通单元／切片的提示和运行时支持 replace，但实际工具列表只给 read／write。本轮补齐 replace，仍受既有文件所有权限制；两次返修已经提供 replace，不能把这项缺口写成那两次失败的原因。

## 修复与验证

先增加／增强定向用例：错误 PATH 下真实 Node 子进程、后台环境传递、真实 replace 版本历史、真实 Node 自测失败的摘要、普通单元／切片工具列表。修复前六项全部失败，修复后六项全部通过。随后补充局部读取和自测范围版本用例，复现并纠正相应状态问题。

- `tests/test_tool_summaries.py`、`tests/test_slice_workflow.py`、`tests/test_unit_workflow.py`、`tests/test_worker_events.py`：最终 181 项通过。覆盖原有失败／过期／未自测提交拒绝、恢复、预算与显式交接等相关机制，不是全套后端重跑。
- `tests/test_tools.py` 与 `tests/test_tool_summaries.py` 的另一批定向验证：30 项通过，与上项有交集，不累加为独立总数。
- 通过修复后的 ToolRuntime，对首次实验产物运行 `node --test --test-name-pattern='传入产品 URL' product.test.js`。实际执行原来环境失败的单个用例，真实浏览器完成，1 passed、0 failed、0 skipped，命令退出 0、未超时。未改该产物，未调用模型。输出：`/private/tmp/real-failure-audit-node-target-20261001.txt`。
- 不把上述浏览器用例当作新系统完整交付或旧任务自动交接成功。原目标账本仍未由正式流程关闭，旧冲突测试仍待模型按现行契约处理，用户尚未验收。

本轮改动在已有 ToolRuntime、摘要、开发请求和文件工具配置内，先同步 Dev Design 实现约定；没有新增架构组件、自动提交、模型路由、数据库变更或依赖。

差异及文档链接检查通过。正式库确认 0 待处理事件／0 运行任务后重启 Worker，PID 62576，日志 `/private/tmp/ai-agent-worker-root-cause-fixes-20261001.log`；未续跑旧失败任务。

## 证据与剩余问题

原始请求与 Trace 位于 `/private/tmp/repair-objectives-deepseek-20260930` 和 `/private/tmp/repair-objectives-completion-deepseek-20260930`。分别仅统计 Trace ID 大于 662／811 的新增记录，避免混入复制历史。重点 Trace：765 工具结果、771 模型判断，以及两组 sent-requests 的 002.json／020.json。临时数据可能失效，不复制完整模型输入或思考记录进 Git。

更早从零运行仍存在产品行为没有落到卡片操作与浏览器证据的问题；已有内部标准与覆盖门禁不能被此次局部返修审计解释为完备性已解决。该历史与候选保留在架构问题 003，本轮没有重切片或重跑。

当前修复能保证更准确的环境、版本和失败信息，不能保证模型一定自测并提交。需要后续由用户确认范围和预算的真实测试，才能评价修正后的自主完成率与 Token；本轮不追加。无进展只能提醒／有界失败，模型可能还想改代码时不能主动结束其工作。
