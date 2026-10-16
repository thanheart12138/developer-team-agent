# v2.2 最小 Bug 分流：task24 隔离真实模型验证

- 日期：2026-09-15。
- 输入：task24 的正式需求、架构、Dev Design、`app.js`、`calculator.test.js` 和浏览器验证报告副本。只在临时副本把 `app.js` 的 `INITIAL_TEXT` 从 `0` 改为 `BROKEN_CLEAR`；原 task24 工作区和任务状态未修改。
- 用户反馈：「清除后显示不对：当前显示 BROKEN_CLEAR，期望显示 0。」
- 预期：Planner 先选取相关证据，程序实际读取，再把问题判为 `implementation_defect`，从 `develop` 开始返修；不重写正式需求或设计。
- 过程：使用内存 SQLite 保存隔离任务状态，真实 Kimi 调用最多 6 次逻辑调用、每次最多 1 次传输尝试。模型依次选择 `product/app.js`、`evidence/verification-report.md`；程序按文件清单核对路径，通过 `ToolRuntime.read` 读取并记录哈希及 Trace。
- 实际：5 次模型调用后分类为 `implementation_defect`，目标阶段 `develop`，隔离任务状态为 `running`。测试命令退出码为 0。
- 范围：本次只验证「调查→分类→路由」；未让隔离任务继续修改代码、跑测试或浏览器验收。完整 v2.2 动态行动 Planner 仍未实现。
