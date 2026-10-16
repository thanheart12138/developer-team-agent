# v2.2 新任务按需跳过设计验证

- 日期：2026-09-16。目标：产品需求获批准后，让 Planner 根据正式需求和项目固定约束判断架构、Dev Design 是否必要；跳过时留证据，不跳测试／浏览器／人工验收。
- 机制用例：新任务直接进入开发、只跳架构、只跳 Dev Design；只保留 Dev Design 时可直接从正式产品需求生成；已确认架构缺陷不可跳过；开发缺少 Dev Design 时只有明确跳过证据才能使用已批准需求作为实现依据；跳过两份设计后验收 Bug 仍能调查代码并退回开发。完整后端测试 84 项、前端构建及 `git diff --check` 通过。
- 真实输入：隔离合成单页整数加法计算器。用户明确两个文本输入、Add／Clear、初始显示 0、输入时不改显示、2＋3＝5、非法输入 `Error`、错误后 4＋5＝9、Clear 不清空输入；数值只接受安全范围内的带符号十进制整数；无存储、外部接口或额外状态。测试进程临时清空 `model.KIMI_STEPS`，所有模型请求使用 DeepSeek，正式模型路由和项目密钥文件不变。
- 真实步骤：DeepSeek 生成产品 Draft／Review／Candidate；测试用户检查候选后批准。Planner 对 `docs/product.md` 和固定约束选择 `modify_code`，证据文件 `evidence/initial-architecture-decision-v1.json` 的置信度为 0.9，明确跳过 `architecture.md`、`dev-design.md`。DeepSeek 从正式产品需求与项目约束生成代码、Node 测试、Playwright 脚本，血缘记录 `design_source=approved_product_and_constraints`。Worker 随后测试、启动和浏览器验证。
- 实际结果：13 次真实模型请求的 Provider 全为 `deepseek`；Node 16／16，最终本地 HTTP 健康检查及 Playwright 通过，Task 经 14 次 Worker 轮询进入 `waiting_acceptance`。两份设计文档均不存在，跳过原因、输入哈希和 Trace 保留。独立 Chromium 操作验证初始 0、2＋3＝5、非法输入 `Error`、随后 4＋5＝9、Clear＝0 且保留输入，页面脚本错误为 0。
- 成功试跑的临时工作区为 `/var/folders/h7/z81qmxk16ks2kn3jzr21_k7m0000gn/T/v22-new-simple-deepseek-bccmoa5f`；决定、测试报告、浏览器报告分别位于该工作区的 `evidence/initial-architecture-decision-v1.json`、`evidence/test-report.md`、`evidence/verification-report.md`，完整模型／工具过程在 `traces/`。临时目录不是永久项目产物。
- 失败与修正：前三个隔离试跑中，DeepSeek 的产品 Candidate 先后留下 Clear 清空输入、非整数／浮点、初始显示三项待决行为，Planner 或测试审批检查阻止跳过；合成用户逐项明确后继续。另一试跑中 Planner 把正式需求正文残留的「候选版」标题当成未审批，并把 Worker 的本地 HTTP 服务当成产品外部网络请求；已在有效 Dev Design 和 Planner 固定语义中澄清，复跑才通过。成功试跑中前两次 `start_product` 健康检查返回 `health_check_failed`，系统两轮返修后第三次启动通过；未确认这两次失败的根因，不据此声称代码缺陷。
- 边界：这是隔离合成任务，产品审批由测试用户代行，用户本人尚未验收软件。全 DeepSeek 路由只在测试进程生效；正式 Kimi／DeepSeek 混合路由的新任务尚未跑同一完整链路。当前生成产物仍使用固定六文件框架，不能据此声称支持任意软件。
