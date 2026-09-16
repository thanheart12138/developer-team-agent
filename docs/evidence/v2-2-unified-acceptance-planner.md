# v2.2 统一验收 Planner 验证

- 日期：2026-09-15。
- 范围：已有产品的所有未通过验收反馈先进入同一个 Next Action Planner；它可检查文件并直接提议澄清、更新需求／架构／Dev Design 或修改代码。程序从行动导出兼容分类字段，保留独立解释一致性检查与文档审批门径。新建任务入口和非 Bug 后续阶段仍沿用原有流程。
- 机制：四种更新／修改行动的阶段映射、需求变更行为契约、实现缺陷必须先读代码、清单外路径拒绝、置信度不足转澄清均有回归覆盖。完整后端测试 68 项通过。
- 真实 Bug 输入：隔离合成计算器的正式需求／设计要求清除后显示 `0`，`app.js` 故意显示 `BROKEN_CLEAR`，反馈要求恢复 `0`。Kimi 先选 `product/app.js`，程序实际读取，再提议 `modify_code`；随后真实 DeepSeek 返修一次，Planner 行动为 `modify_code → run_test → inspect → start_product → verify_product → finish`。Node 和 Playwright 均退出 0，浏览器报告 `[PASS] Clear displays 0`，第 7 次 Worker 轮询后隔离任务进入 `waiting_acceptance`；临时 HTTP 服务在验证后停止。
- 真实需求变更输入：另一隔离合成计算器的正式需求明确清除后显示 `0`，用户明确改为清除后显示空白并提供验收例子。Kimi 直接提议 `update_requirement`，程序映射为 `requirement_change → product_docs`，保存现状、期望与验收例子；正式 `product.md` 没有被直接改写，后续仍须文档候选审批。正式需求已足够判断，此分支无需额外读取代码。将真实结果交给原产品阶段的 `product_feedback_is_decided` 后返回 `True`，一致性记录为 `consistent=True`。
- 发现与修正：最初程序强制所有行动先读代码，真实 Kimi 两次正确提出需求更新却被误转澄清；现改为只有 `modify_code` 必须有实际读取的产品代码证据。两条真实路径在最终规则下重新验证通过。
- 限制：未验证非 Bug 文档候选从 Draft 到用户审批后的完整返工链；小功能任务和新建任务尚未由动态 Planner 接管。真实测试均使用合成文件，不包含 task24 原任务修改。
