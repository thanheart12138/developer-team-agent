# 文档结构与所有权

本目录用于用户设计、用户明确委托创建的设计文档、明确标注的 AI 评审及必要验证证据。

## 设计文档

当前设计文档：

- `docs/product/开发团队模拟器 — 产品需求文档 v1`：当前有效的 v2 产品需求、范围和验收标准；为避免删除或移动既有文件而保留原路径。
- `docs/ARCHITECTURE.md`：当前有效的 v2 系统架构与技术选择。
- `docs/DEV_DESIGN.md`：当前有效的 v2 接口、数据、状态、关键流程和失败策略，包含已确认的 v2.2 已有产品变更及新任务按需设计 Planner 增量规则。
- `docs/DEV_DESIGN_V2_2_AI_DRAFT.md`：用户明确委托撰写的 v2.2 Dev Design AI 原草案；已确认的增量规则以当前有效 `docs/DEV_DESIGN.md` 为准，草案其余方案待评审。
- `docs/DEV_DESIGN_V2_3_AI_DRAFT.md`：用户明确委托按五步方案撰写的 v2.3 结构化任务记忆 Dev Design AI 草案，待评审、待确认、未实施；不替代当前有效设计。
- `docs/ARCHITECTURE_V2_3_AI_DRAFT.md`：v2.3 结构化任务记忆架构 AI 草案，说明组件职责、协作流程和恢复边界，隐藏字段与实现细节；待确认、未实施。

第一版及关键决定归用户所有。未经明确委托，AI 不代写、不预填、不悄悄改写用户原文。后续文档应标明当前有效版本和确认状态；更新时检查受影响的实现和测试。

## 评审与证据

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
