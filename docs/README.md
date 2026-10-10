# 文档结构与所有权

2026-10-10 008任务角色预期已补齐28角色87个正常／边界／反例场景，离线夹具一致性核对及22项相关回归通过；58公共／反馈组件继续细化。不能据此认证真实模型质量，新增HTTP0。[当前证据](evidence/prompt-platform-real-baseline-20261010.md) 。

2026-10-10 完成审计纠正008状态：评测机制已验证，但多数预期仍为通用骨架；当前9／28任务角色具体化，剩余角色／组件继续细化。公共组件版本与文件变化的激活门禁已补；原真实结果只读补取组件身份，新增HTTP0。[持续审计](evidence/prompt-platform-real-baseline-20261010.md) 。

2026-10-10 已补受控单次真实评测CLI／API／页面，实际Chrome未授权点击被拒绝且新增HTTP0，候选会话绑定已修正。真实成功路径与完整反例仍待验证；012候选和新预算待确认。[持续证据](evidence/prompt-platform-real-baseline-20261010.md) 。

2026-10-10 007—010已实现并验证，011有限真实基线19HTTP／426,372Token已留存；真实批次页面启动及012对照待继续，旧「待确认／未实施」条目保留为历史。[当前证据](evidence/prompt-platform-real-baseline-20261010.md) ；[有效设计](PROMPT_MANAGEMENT_DEV_DESIGN.md) 。

2026-10-10 用户委托保存 [提示词管理与评测平台方案——AI 草案](PROMPT_MANAGEMENT_PLAN_AI_DRAFT.md) ：统一版本注册、预期与反例、重要／普通／轻度分类和管理页面。需求已提出，分级含义、启用规则与存储方案为待确认建议；仅补文档，未实施或调用模型。

2026-10-10 用户委托验收与版本整理完成技术验证：本轮冻结素材平台原Node150项／实际Chromium60条通过，系统完整436项回归及前端构建通过，零模型调用。原生UI额外手工操作未完成，原因与证据边界已记录；系统仍待用户验收，未代发批准事件。已补忽略凭据副本目录，准备明确Git候选清单和源码／生成产品本地归档；不提交推送、不改正式任务。[验收与版本清单](evidence/acceptance-version-20261010.md) 。

2026-10-10 范围搜索同起点真实单缺陷返修完成：DeepSeek thinking12／20HTTP、343,838Token、59.1秒，人工改码／纠错0到待用户验收，原Docker Node150／Chromium60独立通过。较上一单缺陷396,416Token少13.26％，自测2→1且轨迹不同，不单因归责；实际第2轮两个搜索只限定product，正文仍20,857字符，未达到离线单文件90.7％。通过后仍3轮，接力后查询旧修改摘要／call确认根因，连续性问题保留。旧八份runtime／220保持，正式服务未操作，不追加调用；用户未验收。[真实证据](evidence/material-task-detail-scoped-search-deepseek-real-20261010.md) 。

2026-10-10 已按用户确认实现授权内范围搜索：search可选path限定文件／目录，默认全域保持，新会话提示词／schema支持范围，旧绑定不迁移。89项相关回归通过，离线两个原查询正文24,962→2,312字符（少90.7％），必要目标命中保留；这是手选范围投影，不是真实Token收益。八份旧runtime计数及字节保持，六份已知绑定匹配，两份更早未知绑定继续拒绝。空闲API61615／Worker61616已加载，health及五项状态指纹保持，零模型调用、不续跑或提交推送。[范围搜索验证](evidence/repair-scoped-search-validation-20261010.md) 。

[2026-10-10 开发成本诊断](evidence/repair-execution-cost-diagnosis-20261010.md) ：逐轮用量／输入内容／真实思考、有效去重与全域搜索限制，方案待确认，零模型调用。

2026-10-09 无审查新流程真实单缺陷返修完成：任务详情关联素材缺失由DeepSeek thinking自主修复，13／20HTTP（执行13、审查0）、396,416Token、67.1秒，无人工改码／纠错。原断言独立Docker Node150／150及实际浏览器60条通过，网站60777首页GET200匹配。目标仍open、系统待用户验收；第10轮自测通过、第13轮提交，仍3轮收尾调查。旧七轮runtime与旧220保持，机制未在实验中改变、正式服务未操作。不追加调用；单缺陷与历史两缺陷范围不同，不换算成本降幅，成本问题未解决。详见 [真实验证](evidence/material-task-detail-no-review-deepseek-real-20261009.md) 。

2026-10-09 用户确认取消新 repair-v1 的独立模型目标／覆盖审查及审查预留。显式提交后执行全量测试、启动、实际浏览器验证，再等待用户验收；原始目标保持 open 到匹配提交／版本的用户批准，以 user_acceptance 记录关闭依据。总 HTTP 上限不变，旧尝试／原授权／审查记录／提示词绑定保留，不自动迁移或续跑。117 项相关回归及真实本地浏览器夹具通过；空闲服务已加载 API96441／Worker96442，五项状态指纹保持。零新增模型调用，真实 Token 收益未验证。详见 [验证记录](evidence/repair-no-model-review-validation-20261009.md) 。

用户已决定保留现版本；七轮优化全过程与负优化复盘集中于 [面试文档第７节](INTERVIEW_GUIDE.md#７优化过程复盘含负优化) ，区分检索／跨模块两组，包含真实数字、撤回依据、当前不足与追问。

最新真实推进测试：同起点11HTTP／249,583Token到待验收，原150项Node／60条浏览器独立通过，较上轮Token少65.33％；耗时更长、计划参数错误和共同机制／轨迹变化限制保留。详见 [真实证据](evidence/material-cross-module-progress-deepseek-real-20261009.md) 。

最新推进规则已确认并用于新返修提示词，旧v2／legacy绑定保持，83项机制回归通过；零新增HTTP，真实行为／Token收益未验证。详见 [验证记录](evidence/repair-investigation-progress-validation-20261009.md) 。

最新定位后持续调查评审：已有两轮真实记录的第3—14轮逐项核对，模型软性推进规则待确认；未改执行代码或新增付费调用。详见 [调查分类与规则建议](evidence/repair-investigation-progress-review-20261009.md) 。

最新连续性修正：成本实测倒退后恢复返修已读依赖、明确修改操作、保留精确去重，80项回归与14份实际接力请求离线核对通过，零HTTP。正文增加，真实Token收益未验证。详见 [修正证据](evidence/repair-context-continuity-validation-20261009.md) 。

最新真实成本对照：同起点跨模块任务自主交付通过，但719,905Token较396,608增加81.52％，25／30HTTP，正文去重生效而行动次数增多，成本目标未达成。详见 [真实对照](evidence/material-cross-module-cost-deepseek-real-20261009.md) 。

最新上下文成本修正：返修接力接通当前自测、v2同一失败正文引用去重；80项相关回归及十二轮只读回放通过，零新增HTTP。详见 [机制证据](evidence/repair-context-cost-validation-20261009.md) 。字节收益不代表真实Token收益。

## 2026-10-09 四项推进与固定演示

[跨模块真实验证](evidence/material-cross-module-deepseek-real-20261009.md) ：既有多选题删除及任务详情需求、真实绿色／红色预检、DeepSeek13HTTP／396,608Token返修、原断言独立Node150／Chromium60通过；仍5轮收尾，可选模型进度未使用，未发现需本轮修机制的阻塞失败。[面试演示指南](DEMO_GUIDE.md) 提供冻结静态演示、零模型启动、实际Chrome交互和只读恢复检查／四种损坏拒绝，真实运行中崩溃恢复未验证。依据 [已授权计划](evidence/cross-module-repair-plan-20261009.md) ，四项均已推进至可检查结果，不扩大业务或继续试跑。

## 2026-10-09 当前事实与模型进度真实对照

[真实效果与局限](evidence/material-search-current-facts-deepseek-real-20261009.md) ：同起点8HTTP／155,482Token，原断言独立Node149／149与Chromium55条通过，无人工纠错；比上一轮Token少46.89％、最后通过至提交5→3轮。真实工作判断生效，仍历史查询及单独计划调用，轨迹差异保留，不宣称稳定降幅。

## 2026-10-09 当前事实与模型进度已实施

[新上下文契约验证](evidence/repair-current-facts-validation-20261009.md) ：仅新返修绑定v2，程序事实与模型判断分开，失效／独立失败／恢复／旧契约保持。41份原请求离线核对通过，本地服务加载，零新增模型调用；真实提交轮次与Token收益未验证。下文候选状态是当时历史。

## 2026-10-09 上下文结构评审，待确认

[当前任务事实与历史输入评审](evidence/repair-context-view-review-20261009.md) ：实际请求事实核对及单一当前事实投影建议；保留原审计／思考、明确提交和独立验证。仅建议，尚未修改运行契约或追加真实调用。

## 2026-10-09 接力修正后的真实对照

[接力真实效果与局限](evidence/material-search-handoff-comparison-deepseek-real-20261009.md) ：同起点13HTTP／292,780 Token，原断言独立Node149／149、Chromium55条通过；比上一轮Token少32.05％，但最后自测通过到提交4→5轮，接力信息正确却仍反复确认。停止继续同方向试跑，后续上下文组织建议待确认。

## 2026-10-09 提交延迟分析与接力修正

[逐轮分析与最小修正](evidence/repair-handoff-progress-analysis-20261009.md) ：两次接力遗漏跨批次修改、模型重复怀疑修改／测试先后；必要补测保留。修正接力修改区间与自测事实、同版本证据提示及计划／提交批次说明，全套411项通过，原Trace离线演算通过；没有新真实模型调用，不能声称实际收尾轮次减少。

## 2026-10-09 自测成本真实对照

[同起点真实DeepSeek对照](evidence/material-search-cost-comparison-deepseek-real-20261009.md) ：同一素材笔记检索缺陷两轮均完成待验收，优化后16HTTP／430,905 Token，比原629,781少31.58％，但请求15→16、耗时90.6→130.8秒。原断言独立Node149／149与真实Chromium55条通过。摘要真实生效，缓存未触发，收尾请求没有减少；单例不能推断稳定成本优势。

## 2026-10-09 自测成本修正

[自测成本机制验证](evidence/repair-selftest-cost-validation-20261009.md) ：用户确认后实现新返修成功自测摘要、失败详情与原日志引用、同版本真实通过证据复用和明确提交提示。保留思考／工具配对及显式提交。全套 404 项通过、4 项端口权限失败后复验通过，最终相关 32 项通过；旧真实轨迹离线请求字节减少 36.74％，不是实测 Token 收益，本轮新增模型请求为零。

## 2026-10-09 新架构真实返修结果

[素材笔记检索真实验证](evidence/material-search-repair-deepseek-real-20261009.md) ：真实 DeepSeek thinking 沿新流程自主修复隔离素材平台的注入缺陷，15 HTTP／629,781 Token，原测试独立复测 Node 149／149、真实浏览器 55 条通过，系统待用户验收。无人工改码，原平台及旧 220 次计数保持。成本偏高，不能由单例宣称稳定能力或 Token 收益。下文机制验证条目保留当时证据边界。

## 2026-10-09 搜索与上下文当前状态

2026-10-09 第三批已实现及验证：新主会话增加授权范围字面搜索、50 条分页与版本校验、默认 200 行读取、实际可见范围去重及稳定完整批次接力。全套 399 项通过后再完成两项读取门禁修正，最终相关 53 项通过；固定模型驱动真实 Docker／HTTP／Chromium 合成链路到待验收。离线同视图请求字节 21,790→12,391，不是实测 Token 收益。真实模型新架构返修仍未验证。详见 [第三批验证](evidence/repair-search-context-validation-20261009.md) 。


## 面试材料

[面试讲解与证据索引](INTERVIEW_GUIDE.md) ：用户委托记录，串联真实失败、架构取舍、实现证据和简历措辞。不能替代真实进度或将合成验证描述为真实模型完成。

## 2026-10-09 连续会话当前状态

2026-10-09 第二批已实现：新返修直接进入任务级连续主会话，任务 product 范围写权限、计划／决定状态、成对回答、跨阶段协议恢复和测试 Diff 审查。全套 388 项通过，真实 Docker／Chrome 合成集成到待验收，执行及审查为固定响应；真实模型返修与成本收益未验证。详见 [第二批验证](evidence/repair-session-validation-20261009.md) 。下一批是受控搜索与有效上下文。


## 2026-10-09 当前实现与运行状态

2026-10-09，Sandbox v1 真实隔离探针与合成集成通过，全套 376 项通过。profile 绑定当前源码、镜像、Docker 环境和原始证据，检查通过后新 repair-v1 入口可用；环境或证据变化则关闭。正式空闲 API／Worker 已加载，原任务、schema、产品和旧调用计数保持。真实模型返修未验证；第二批连续会话／任务范围写权限状态见当前实施记录。详见 [真实验证记录](evidence/sandbox-isolation-real-20261009.md) 。


## 已确认返修增量的第一批（2026-10-05）

有效第一批规则见 `DEV_DESIGN.md`、`ARCHITECTURE.md` 顶部。`backend/app/runtime/repair_runtime.py` 保存显式新尝试、提交版本、固定阶段和实际请求预算；旧任务不自动生成这些记录。Docker 隔离与统一 Sandbox 已实现及真实工具验证，真实 `repair_request` 仅在当前本机 profile 核验通过时放行，否则返回 409／`repair_execution_isolation_pending`；机制夹具不能作为启用依据。

任务工作区新增程序专有 `evidence/repair-runtime-v1.json`、`repair-authorization-<id>.json`、`repair-attempt-<event_id>-runtime.json`、`repair-attempt-<event_id>-<submission_number>-submission.json`、对应 `-validation.json`。授权由运行控制准备并核对原累计请求，不由客户端任意写额度；runtime 原子更新，旧尝试与每次提交不覆盖。目标账本、需求、授权、阶段及审计不能由模型修改。连续 session 检查点尚属第二批。

本轮证据见 [固定收尾机制验证](evidence/repair-v1-fixed-validation-20261005.md) 。真实模型、真实缺陷修复和成本优势尚未验证；未续跑旧素材平台。

本目录用于用户设计、用户明确委托创建的设计文档、明确标注的 AI 评审及必要验证证据。

## 设计文档

### 2026-10-08 项目 Sandbox

[Sandbox 架构与接口增量](SANDBOX_V1_AI_DRAFT.md) ：AI 起草，用户已确认接口及状态并授权实施。复用既有 Runner／快照／预览，不新增多后端框架或模型调用预算。运行验证状态见 ROADMAP。

[Sandbox 接入记录](evidence/sandbox-integration-20261008.md) ：接口与流程代码接入、机制回归、Docker daemon 阻塞及未验证事项。不得以机制回归替代隔离探针。

### 2026-10-05 Docker 执行隔离细化

用户已确认该设计并开始实施。新增 `runtime-images/website-repair/` 只保存镜像 Dockerfile、固定控制程序、版本配置和 seccomp 来源，不放产品／凭据／实验数据。运行快照与容器结果仍在各 Task 的 isolation／evidence；隔离验证记录及 profile 存在 `workspace/experiments/docker-isolation-20261005/`，沿用忽略规则。该实验仅合成数据、零模型预算，不迁移旧任务。

[Docker 隔离设计](REPAIR_DOCKER_ISOLATION_V1_AI_DRAFT.md) 定义已确认的快照／挂载、凭据、断网回环测试与宿主预览、镜像／浏览器、运行限制、恢复及启用探针。实施进行中，当前隔离门禁不解除，真实调用预算不增加。[实施记录](evidence/docker-isolation-implementation-20261005.md) 区分机制测试与实际隔离探针。

### 2026-10-05 已有网站返修草案

用户于 2026-10-05 明确确认本组 AI 起草的返修增量方案，第一批已实施并机制验证，有效规范已同步；后续待实施，真实新模式未启用。首版限本项目已有网站任务，执行隔离确认后再启用连续会话与任务范围权限，随后验证完整交付和成本。

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

[011／012剩余真实验证执行单](PROMPT_FINAL_REAL_EVALUATION_PLAN.md) ：待确认建议，明确候选、预算分配、原回归与真实入口边界，未授权调用。
