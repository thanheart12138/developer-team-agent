# 文档结构与所有权

本目录用于用户设计、用户明确委托创建的设计文档、明确标注的 AI 评审及必要验证证据。

## 设计文档

当前设计文档：

- `docs/CONTENT_WORKBENCH_REQUIREMENTS_V1_AI_DRAFT.md`：用户委托撰写并保存的多模块内容管理工具需求草案；已按另行确认的隔离测试范围运行，不替代模拟器设计。

- `docs/product/开发团队模拟器 — 产品需求文档 v1`：当前有效的 v2 产品需求、范围和验收标准；为避免删除或移动既有文件而保留原路径。
- `docs/ARCHITECTURE.md`：当前有效的 v2 系统架构与技术选择。
- `docs/DEV_DESIGN.md`：当前有效的 v2 接口、数据、状态、关键流程和失败策略，包含已确认的 v2.2 已有产品变更及新任务按需设计 Planner 增量规则。
- `docs/DEV_DESIGN_V2_2_AI_DRAFT.md`：用户明确委托撰写的 v2.2 Dev Design AI 原草案；已确认的增量规则以当前有效 `docs/DEV_DESIGN.md` 为准，草案其余方案待评审。
- `docs/DEV_DESIGN_V2_3_AI_DRAFT.md`：用户明确委托按五步方案撰写的 v2.3 结构化任务记忆 Dev Design AI 草案，待评审、待确认、未实施；不替代当前有效设计。
- `docs/ARCHITECTURE_V2_3_AI_DRAFT.md`：v2.3 结构化任务记忆架构 AI 草案，说明组件职责、协作流程和恢复边界，隐藏字段与实现细节；待确认、未实施。

第一版及关键决定归用户所有。未经明确委托，AI 不代写、不预填、不悄悄改写用户原文。后续文档应标明当前有效版本和确认状态；更新时检查受影响的实现和测试。

新任务工作区使用 `docs/delivery-plan.json` 标识逐业务切片流程，执行卡保存到 `docs/slices/`，根级 `dev-design.md` 只保存切片索引；测试与恢复进度保存到 `evidence/slice-progress.json` 和 `evidence/slices/`。已有逐单元任务仍使用 `docs/dev-design/vN/`、`evidence/units/` 和 `development-progress.json` 恢复；不在项目治理文档目录生成被开发软件文件。

新逐切片任务在首张执行卡前生成内部 `docs/acceptance-standard.json`，绑定已批准产品版本；各卡引用行为 ID，完成审查保存到 `evidence/acceptance-coverage-review.json`。旧任务不自动迁移，正式产品文档不增加技术验证字段。

## 架构问题记录

`docs/architecture-issues/` 保存用户委托的架构问题过程记录，README.md 作为索引；每个问题采用 `NNN-english-topic.md`，按问题持续追加进展，不为每轮尝试新建问题文件。固定内容为问题与依据、目标、解决过程、方案取舍、测试方法与结果、当前决定与最终状态、证据及局限。可按问题复杂度增减篇幅，不强制增加无用字段。

仅记录架构层面的问题，普通 bug、提示词调整和参数修改不独立建档；它们可以作为架构问题的触发用例。用户决定、AI 建议和待验证判断分别注明，失败与未解决状态保留。记录引用设计与 `docs/evidence/`，临时运行文件注明留存限制，不复制密钥、个人数据或整个模型输入。该目录不存放被开发软件或运行数据库，不替代当前有效设计与真实进度。

## 评审与证据

- `docs/evidence/repair-objective-preservation-validation-20260930.md`：原始验收目标独立记账、返修输入与关闭门禁；237 项机制回归通过，真实模型修复效果未验证。

- `docs/evidence/deepseek-thinking-checkpoint-20260924.md`：按官方协议开启 DeepSeek thinking 并续传工具轮次思考内容；真实同断点 3 次调用完成测试夹具返修，保留正式服务未重启及全流程未完成的边界。
- `docs/evidence/luna-medium-checkpoint-20260924.md`：同一 DeepSeek 失败状态用 OpenRouter Luna medium 真实返修；当前切片通过，记录测试夹具修正、覆盖变化和相对 high 的用量。
- `docs/evidence/luna-direct-checkpoint-20260924.md`：OpenRouter Luna high 真实调用续测 DeepSeek 的 `topics-core` 失败状态；3 次请求完成当前切片，保留共享存储层改动和全流程未完成的限制。
- `docs/evidence/openrouter-luna-probe-20260924.md`：OpenRouter Luna 直连因地区限制返回 HTTP 403；经环境 HTTPS 代理的真实 Runtime 流式工具调用及解析已通过，正式返修待验证。
- `docs/evidence/unit-workflow-validation.md`：模块／功能独立设计、程序逐单元测试修复与恢复机制，137 项回归、三十次真实 DeepSeek 部分验证及完整流程未通过的限制。
- `docs/evidence/slice-workflow-validation.md`：逐业务切片规划、真实测试后再规划、内部重规划边界及旧任务兼容的机制验证。
- `docs/evidence/acceptance-standard-offline-validation-20260928.md`：内部行为提取、独立覆盖门禁与旧内容工作台编辑缺口的离线复现；真实模型提取与新增 Token 成本未验证。
- `docs/evidence/architecture-scaffold-validation.md`：架构代码骨架、逐模块 todo 门禁及旧任务兼容验证。
- `docs/evidence/unit-workflow-300-validation.md`：累计预算提高到 300 次后的续测，实际 40 次；固定设计开发链路通过，自主流程仍因开发计划单元重叠失败。
- `docs/evidence/current-only-context-validation.md`：去掉自动工具历史及摘要的真实对照、读取全文去重复测与用量；重复读取、完整自主流程未通过及正式策略未切换。
- `docs/evidence/effective-tool-state-validation.md`：复用账本聚合有效文件状态、142 项回归及真实探针；26 次模型调用，生成验证脚本错误与返修责任澄清、完整交付未通过。
- `docs/evidence/unit-handoff-repair-validation.md`：显式交接与责任路由、自测协议的 171 项机制回归及真实故障闭环；保留成功／失败和成本，稳定性待测。
- `docs/evidence/self-test-full-flow-deepseek-validation.md`：自测协议从空工作区的完整 DeepSeek 测试，每轮独立 300 次预算，保留入口修正与产品审批边界。

- `docs/evidence/tool-summary-deepseek-validation.md`：真实 DeepSeek 测试失败，文档输出截断、开发读取循环和历史查询闭环问题，83 次共用预算及实际用量。

- `docs/evidence/tool-summary-validation.md`：工具执行摘要、三个任务内查询工具、历史上下文窗口和检查点恢复验证，已有生成软件真实回归及 Worker 加载证据。

- `docs/evidence/product-entry-fix-validation.md`：通用入口、子目录模块及测试自动发现修复，计算器和多模块已有产物的真实回归，正式 Worker 加载证据。

- `docs/evidence/content-workbench-baseline.md`：多模块全 DeepSeek 基准的原自动失败、独立产物验收、200 次总预算、实际用量与限制。

- 后续确需保存且已获授权的 AI 评审放在 `docs/reviews/`，按评审对象和版本命名，明确标注「AI 评审」、日期与目标版本，区分阻塞问题、普通建议及未来问题。当前不创建该目录。
- 验证证据放在 `docs/evidence/`，按验证事项命名，记录输入、运行步骤、期望结果、实际结果、测试或日志位置和已知限制，并区分机制验证、真实 AI／工具验证与生成软件验证。
- `docs/evidence/v1-implementation-validation.md`：v1 首次实现的本机机制测试、构建和 HTTP 冒烟证据，以及尚未验证的真实环境项目。
- `docs/evidence/v2-trace-visualization-validation.md`：v2 Trace 与实时可视化的机制、构建和真实浏览器验证证据。
- `docs/evidence/v2-2-unified-acceptance-planner.md`：统一验收 Planner 的机制测试、真实 Bug 闭环和真实需求变更路由证据。
- `docs/evidence/v2-2-existing-feature-actions.md`：已验收产品小功能入口的机制测试及隔离合成乘法功能的真实行动闭环证据。
- `docs/evidence/v2-2-full-deepseek-feature.md`：测试进程使用全 DeepSeek 的已有产品小功能完整链路、浏览器操作及首次超时证据。
- `docs/evidence/v2-2-new-task-design-skip.md`：新任务按需跳过设计的机制测试、全 DeepSeek 合成加法任务及浏览器验证证据。
- 未执行标记「未验证」；实现、验证和用户验收分别记录。证据不得包含密钥或真实个人数据。

上述位置是文档存放约定，不是产品架构或运行时隔离方案。纯讨论不自动落盘，必要进度同步到根目录 `ROADMAP.md`。
