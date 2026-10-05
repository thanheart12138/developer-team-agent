# 文档结构与所有权

本目录用于用户设计、用户明确委托创建的设计文档、明确标注的 AI 评审及必要验证证据。

## 设计文档

### 2026-10-05 已有网站返修草案

用户于 2026-10-05 明确确认本组 AI 起草的返修增量方案，待分批实施；现有运行需求、架构和 Dev Design 保持，实施各批前同步有效规范。首版限本项目已有网站任务，先实现固定验证收尾，再在执行隔离确认后启用连续会话与任务范围权限，随后验证完整交付和成本。

- [产品范围草案](REPAIR_PRODUCT_V1_AI_DRAFT.md) ：普通用户流程、支持范围与成功标准。
- [架构草案](REPAIR_ARCHITECTURE_V1_AI_DRAFT.md) ：一个主要执行会话、程序验证、独立目标审查、预算与恢复边界。
- [Dev Design 草案](REPAIR_DEV_DESIGN_V1_AI_DRAFT.md) ：事件入口、运行记录、状态投影、权限、提交、验证、实际请求守卫、幂等与分批验收。

扩大权限前的命令执行隔离技术仍待用户决定；无新模型调用预算授权。旧素材平台的失败与累计 220 次计数不因本方案改变。

### 当前有效设计及其他草案

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

## 付费隔离实验的持久目录（2026-10-03 用户授权）

正式任务继续使用已有 MySQL 和 `workspace/{task_id}/`。本约定只修正手动付费实验的留存流程，不改变正式系统架构、数据库 schema 或模型路由。

- 实验根目录固定为 `workspace/experiments/<experiment>/`；沿用已有 `workspace/` Git 忽略规则，普通 pytest 夹具不受此限制。
- 每个根目录先保存 `README.md` 说明范围和结构；`test.db` 保存隔离状态，`workspace/` 保存正式依据、生成产品、Trace 与检查点，`call-count.json` 保存原计数。控制脚本保存在已跟踪的 `tests/` 或本实验根目录；脱敏发送体、运行日志、结果、截图也保存于本根目录。不得复制认证头、环境正文或密钥。
- 新实验自动分配独立目录；显式指定根目录时必须位于上述持久目录内，且不能复用非空旧实验。恢复必须显式指定原目录，数据库、工作区和合法计数必须存在；缺失／损坏时在创建数据库、加载凭据及调用模型之前拒绝，不自动新建实验冒充续跑。合法的无工具 Planner 可没有检查点文件，不要求所有 Run 都有检查点。
- 恢复沿用 `call-count.json`，不得用缺省零或逻辑 Trace 条数推测已有 HTTP 次数；显式历史计数不得低于已保存计数。各脚本的原调用上限与计数语义保持；恢复仍须遵守用户批准的范围及剩余预算，不因恢复另获调用授权。
- 同一实验同时只运行一个控制进程；计数在调用前原子保存。完整目录作为原断点保留，不只归档报告摘要；必要脱敏结论另存 `docs/evidence/`。复制运行中 SQLite 不能当作一致备份，复制须沿用 SQLite backup 或先停止写入。
- 诊断／返修夹具的源实验也必须明确指定并位于持久目录；禁止把历史 `/private/tmp` 路径作为固定来源。单元返修探针的新建 `--verified-repair-probe` 须同时提供 `--verified-source <原实验根目录>`；恢复已有探针不重新复制来源。源缺失时先停止，不创建目标数据库或调用模型。
- 这能避免系统临时目录清理导致的数据缺失，不提供磁盘故障／人为删除的灾难恢复；未执行真实机器重启试验。旧临时实验不会被自动找回或重建。

手动入口只在另有真实调用授权时执行，示例根目录需按实验命名替换：

```sh
PYTHONPATH=. .venv/bin/python tests/content_workbench_baseline.py --root workspace/experiments/example --max-http 12 --max-step 12
PYTHONPATH=. .venv/bin/python tests/content_workbench_baseline.py --root workspace/experiments/example --resume --max-http 12 --max-step 12
```

调用上限示例不是新增预算授权；恢复脚本遇到 failed／waiting_user 等状态的处理仍遵循原脚本，保存位置修正不自动把失败任务改成 running。

## 架构问题记录

`docs/architecture-issues/` 保存用户委托的架构问题过程记录，README.md 作为索引；每个问题采用 `NNN-english-topic.md`，按问题持续追加进展，不为每轮尝试新建问题文件。固定内容为问题与依据、目标、解决过程、方案取舍、测试方法与结果、当前决定与最终状态、证据及局限。可按问题复杂度增减篇幅，不强制增加无用字段。

仅记录架构层面的问题，普通 bug、提示词调整和参数修改不独立建档；它们可以作为架构问题的触发用例。用户决定、AI 建议和待验证判断分别注明，失败与未解决状态保留。记录引用设计与 `docs/evidence/`，临时运行文件注明留存限制，不复制密钥、个人数据或整个模型输入。该目录不存放被开发软件或运行数据库，不替代当前有效设计与真实进度。

## 评审与证据

- `docs/evidence/calculator-rounding-repair-real-20261003.md`：误选测试对象的历史实验，六次 DeepSeek thinking／230,075 Token 修旧计算器舍入，实际结果保留；用户目标是素材管理平台，不执行其切片／Planner 路径，排除出目标产品和机制验证，不安排计算器验收。
- `docs/evidence/calculator-rounding-repair-blocked-20261003.md`：现存失败 Task 26 的三个舍入错误由独立 Node／Chrome 复现，原 23 项漏测；持久副本及原计数已保留，原 Worker 程序测试自然进入返修。真实 DeepSeek 六次上限命令被自动审批拒绝，具体数据外发授权待确认，零调用；旧流程没有显式提交门禁，不宣称新切片交接或模型修复通过。
- `docs/evidence/formal-service-recovery-20261003.md`：原 MySQL 正式数据与全部 Trace 详情文件仍在；恢复 API 8001、前端 5173 和空闲单 Worker，九条只读服务／真实 Chrome 检查通过，状态／逻辑计数／schema／文件哈希保持，零模型调用。旧临时素材平台与实验断点未恢复，不能补记目标闭合或用户验收。
- `docs/evidence/experiment-storage-validation-20261003.md`：用户授权修正隔离实验留存，五入口统一持久根目录、拒绝缺失断点／计数重置并原子保存；移除固定历史临时来源，原软件与正式持久化保持。最终二十六项本地检查及新进程 SQLite／历史／文件恢复通过，零真实模型调用；未重启机器、未恢复旧实验或证明模型闭环。
- `docs/evidence/planner-evidence-reuse-interrupted-20261003.md`：修复后六次上限续测的上次可见记录到启动／测试成功及第三次 DeepSeek 目标复审开始；当前临时断点和原平台目录缺失、旧进程与端口未运行，项目现有文件不匹配。当前只读恢复检查零新模型调用，最终状态／用量未确认；保存中断与留存缺口，先找备份、不重置预算或重跑开发。
- `docs/evidence/planner-evidence-reuse-validation-20261003.md`：用户确认后修复跨 Run Trace 复用、当前门禁事实及字段级纠错，零重复 read、坏证据／同 Run 重选／额度／仍非法回归；首次 96 通过／1 夹具失败，修正后该项通过，真实旧证据离线恢复通过。空闲 Worker 27466 已加载，原平台与任务保持，零新真实调用；完整模型收敛和成本未验证。
- `docs/evidence/context-slimming-delivery-real-20261003.md`：沿新交接副本真实完整浏览器与 Node 102 项通过，四次 Kimi／22,857 Token 后在 start_product 因重复选择已读非法 inspect 路径失败；跨阶段证据恢复和具体纠错缺口已记录，建议未批准／实施，目标复审及 finish 未执行。累计成本 496,892 不能与旧完整范围算降幅，原平台保持，新临时服务已停。
- `docs/evidence/context-slimming-deepseek-real-20261003.md`：同旧两项测试失败断点真实 DeepSeek thinking，最多十二 HTTP、实际十一／474,035 Token，自测 86／86 并显式提交后即停；二十文件起点、原目标／协议及提交版本保持，总 Token 比旧同范围少 30.16％，调用／读取及输出增加。新副本的后续浏览器／目标复审／finish 未执行，当前待验收源实例未替换。
- `docs/evidence/request-context-slimming-validation-20261002.md`：2026-10-02 授权、2026-10-03 收尾；自测结果／历史报告去重、流程 Planner 状态与按需调查、当前关联源码接力。最终定向 11 项通过，39 个旧真实请求正文投影减少 36.03％，协议与目标事实保持；不含新增字段／指令开销，不是实测 Token。正式空闲 Worker 已加载，任务／产品保持，零新模型调用。
- `docs/evidence/content-platform-objective-finish-real-20261002.md`：沿 verify_product 断点，最多六次授权、实际三次 HTTP／98,364 Token，Node 102 项与原浏览器通过，两个目标当前版本独立闭合，正常 Planner／程序 finish 到待验收；三轮累计 39 HTTP／1,924,458 Token，产品／协议／正式环境保持，最终用户验收未完成。
- `docs/evidence/content-platform-test-handoff-real-20261002.md`：沿原反馈断点追加 12 HTTP／776,744 Token，DeepSeek 主动自测 86 项并显式提交，原浏览器与全量 Node 102 项通过，独立页面三项复验通过；预算在 verify_product 前用尽，目标复审／finish 未执行，累计 36 HTTP／1,826,094 Token。
- `docs/evidence/content-platform-feedback-repair-real-20261002.md`：用户外发授权后真实原系统返修，24 HTTP／1,049,350 Token；两项页面缺陷独立复验通过，生成测试两处失败、无主动自测／提交，预算用尽停在 failed，保留代理澄清与未闭环边界。
- `docs/evidence/content-platform-feedback-repair-blocked-20261002.md`：用户要求交原系统返修，两项独立红灯与反馈入口已准备；真实模型调用被自动审批要求具体外发授权而拒绝，尚未提交反馈 Event、零模型调用。
- `docs/evidence/content-platform-business-test-20261002.md`：用户委托当前素材平台独立业务测试，48 条检查通过；旧错误提示残留和 favicon 404 单独保留，产品文件／正式环境保持，零模型调用，最终验收未自动提交。
- `docs/evidence/static-server-backlog-fix-validation-20261002.md`：用户确认后 Worker 服务队列设为 128，连接突发红绿回归与相关入口 12 项通过；实际服务首次加载和原状态复验共 15 条通过，本地 Worker／隔离服务重启，正式任务保持，零模型调用，最终验收边界保留。
- `docs/evidence/module-load-reset-root-cause-20261002.md`：首次模块加载重置的 TCP／内核队列定位、无效对照、本机最小拒绝实验及真实 ToolRuntime 的队列 128 候选验证，8／8 通过；零模型调用，正式启动修复待确认，原验收失败保持。
- `docs/evidence/delegated-acceptance-blocked-20261002.md`：用户委托独立代行验收首开模块请求连接重置，总体未通过；单次重开及剩余步骤补验共 42 条检查通过，0 模型调用，产品／目标账本／正式任务保持，根因未确认，未自动修复。
- `docs/evidence/objective-review-and-finish-real-20261002.md`：授权后 Node 102／102、真实浏览器及原目标审查通过，3 HTTP／88,591 Token，Kimi inspect 后 finish，程序进入隔离实例待验收；版本、协议和正式任务保持，服务保留，导航旧超时根因仍未知。
- `docs/evidence/navigation-diagnosis-20261002.md`：当前原 CLI、带日志 CLI、实际 Worker 门禁对照及八次限定导航采样通过；此前两次超时未复现、根因未知，零模型调用，后续目标审查及 finish 被自动审批拒绝，原目标仍 open。
- `docs/evidence/objective-close-validation-blocked-20261002.md`：提交恢复及独立编辑／Node 102 项通过，后续正式浏览器两次素材页切换超时；探针 null 统计错误已保留并修正，零真实模型 HTTP／零 Token，原目标 open，未进入待验收。
- `docs/evidence/post-green-handoff-deepseek-real-probe-20261002.md`：从上次已通过产物保留历史续测，最多 6 HTTP，实际 4 HTTP／163,166 Token，模型主动自测 86／86 后显式提交成功；到交接停止，原目标仍 open，独立关闭审查及完整交付未执行。
- `docs/evidence/repair-feedback-validation-20261002.md`：失败定位及实际／期望值保留，接力旧报告只留查询引用，read 参数说明与实际逻辑预算、Developer v13；首次相关回归 226 通过／1 失败，修正后最终 16 项定向通过，旧真实行号离线恢复，无新模型调用。
- `docs/evidence/context-relay-deepseek-real-probe-20261002.md`：同断点真实 12 HTTP／444,711 Token，接力真实触发、固定诊断最终 86／86 通过，独立浏览器复验通过；仍零模型自测／提交、预算失败，原目标 open，未扩大额度。
- `docs/evidence/deepseek-context-relay-validation-20261002.md`：已有产物返修的完整批次上下文接力、已知代码刷新、协议结果去重及恢复，215 项相关回归和 4 项截断定向回归通过；无付费调用，真实成本和交付未验证。
- `docs/evidence/focused-repair-and-batch-diagnostics-validation-20261002.md`：聚焦返修任务与批次诊断，193 项本地验证通过，离线 context 字符数减少约 56.4％；没有新付费调用，真实收敛未验证。
- `docs/evidence/repair-diagnostic-first-validation-20261002.md`：切片返修先取得当前真实诊断，190 项机制验证通过；真实 DeepSeek 12 HTTP／621,348 Token，修改两文件但未自测交接，预算失败，原目标 open。
- `docs/evidence/read-progress-deepseek-small-probe-20261001.md`：新进展与任务焦点的真实 DeepSeek 小范围测试，12 HTTP／532,706 Token，零修改／自测／提交，调用预算停止；机制运行但交接未完成。
- `docs/evidence/read-progress-and-current-task-validation-20261001.md`：用户同意必要读取进展和当前任务视图，保留通过后催促提交；188 项定向验证通过，无新模型调用。
- `docs/evidence/real-failure-root-cause-audit-20261001.md`：两次真实返修的环境、契约、上下文及模型行为原因；定向修复与原环境失败浏览器用例复验，未追加模型调用。
- `docs/evidence/handoff-verification-contract-validation-20260930.md`：显式交接取消叠加诊断门禁、统一验证职责，16 项定向机制验证通过，真实模型收敛效果未复测。

- `docs/evidence/repair-objectives-completion-deepseek-20260930.md`：修正后一次 20 次真实续测，编辑验收保留，自动交接未完成，记录成本及旧测试契约冲突；未继续加预算。

- `docs/evidence/repair-context-and-replace-guard-validation-20260930.md`：单元／切片按需读取、替换恢复门禁及 239 项回归；离线请求体积下降，实际模型成本与交接效果未验证。

- `docs/evidence/repair-objectives-deepseek-real-validation-20260930.md`：20 次真实 DeepSeek 返修，限定编辑操作独立通过；记录交接未完成、关闭审查未触达及 3,484,768 Token 成本。

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
