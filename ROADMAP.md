# 项目进度

## 当前阶段

2026-09-19：完成素材管理提示词 v2 真实 DeepSeek 全链路评测。v2 按数据所有权把计划从 v1 的 11 单元降到 9 单元，但仍错误拆出 verification 单元；流程在 tasks_unit Dev Design 连续五轮无法调和来源上下文验收与未声明 topics／materials 依赖，最终 `failed / dev_design / unit_design_review_failed`，未进入开发。实际 34 HTTP，输入 302,129／输出 45,697／总计 347,826 Token；产品 18,550、架构 61,957、Dev Design 267,319。因完成阶段比 v1 的 develop 更早，低消耗不计为优化成功。v2 结果和证据完整保留，注册表已恢复激活 v1，下一版需让规划器同时校验验收行为、依赖和唯一所有权形成闭环。

2026-09-19：按用户确认开始优化开发单元拆分，并完成提示词版本升级。`unit-planner`、`design-author`、`design-reviewer` 从 v1 升为 v2，旧版本保留；规划器先确定核心数据／状态／业务规则的唯一所有者，默认一个业务模块一个单元，只允许按独立生命周期、独立公共接口或独立跨模块业务结果继续拆分，禁止按搜索、校验、页面控件、测试或文件名拆分；设计生成和评审同步保持边界并阻止第二数据所有者。新增素材管理 v2 待评测清单，目标是在需求覆盖和完成度不下降时少于原 11 单元，并降低 Dev Design 的 7,748,016 Token。全量 183 项回归通过，提示词哈希、Python 编译与差异检查通过；尚未执行真实模型评测，不宣称单元数或 Token 已下降。

2026-09-19：已按用户授权建立第一阶段提示词版本管理。素材管理核心链路的开发单元规划、设计生成、设计评审、集成失败归因和单元开发提示词移入 `prompts/<name>/v1.md`，注册表锁定激活版本与模板 SHA-256；运行时调用前校验文件和变量，每条模型请求 Trace 新增提示词名称、版本、模板／渲染／上下文哈希，未迁移调用明确标记 `legacy-inline / unversioned`。保存 2026-09-19 全链路失败样本为机器可读基线，比较规则以完成度优先、成本次之。提示词正文未优化，未新增付费模型调用。全量 182 项回归、Python 编译和差异检查通过。

2026-09-19：按用户授权以当前实现从空工作区复跑素材管理需求，正式单 Step 100、整轮最多 300 HTTP。测试在 architecture_docs 因开发计划连续三次 `unit_plan_module_feature_overlap` 失败，未进入 Dev Design 或开发：规划器反复在同一模块混用 module 与 feature 单元，且纠正后重叠范围扩大。实际 13 HTTP，输入 89,425／输出 34,395／总计 123,820 Token；产品 18,486，架构 105,334，其中三次计划 50,909。测试控制为两个非关键细节采用最小默认值，并因当前流程复用旧 clarify 决定而使缓存失效；恢复脚本另造成一次 checkpoint_path 错误及 6,580 Token 重跑，均如实计入，不能称完全自主。未改正式服务、数据库或生成代码，详细证据追加至 `docs/evidence/content-workbench-baseline.md`。

2026-09-18：完成原工作区整体成本证据审计，未修改服务或付费重跑。逐 sent／Trace 核对主流程 46 个逻辑调用／46 HTTP、583,379 Token，入口错误另 4 次／14,938 Token；Dev Design 302,428，其中 UI 交互设计 216,799，阻塞未识别后的两次读取 28,348。确认依赖设计全文反复携带、设计阶段缺 URL 运行事实、公共入口装配与唯一所有权冲突，不能归为单一提示问题。001／004 已追加成本、局限和候选：保留 math／ui 边界而收粗为两个开发单元、精简契约与依赖输入、统一运行事实、结构化阻塞；保留真实自测及独立验收，不新增评审层。候选未获确认、未实施、收益未验证；每轮独立 300 HTTP、正式 Step 100 预算不变。

2026-09-18：用户澄清每轮独立 300 次调用机会，执行自测协议从初始需求的完整 DeepSeek 复测。旧探针预写正式产品的入口错误被修正，保留其 4 次成本；真正空工作区流程生成产品、架构、两模块四功能、共享契约及单元 Dev Design。测试控制参与产品审批和已核实的 URL 运行事实澄清，不称完全无人干预。加法自测 9 项通过并提交；平方自测发现公共入口缺 squareSum 导出，入口文件归加法，越权写入被拒。模型夹带前言的 BLOCKED 未被程序识别，最终 failed／develop／unit_development_no_progress，未进入 UI 或浏览器验证。本轮 50／300 次（主流程 46，入口错误 4），输入 530,657／输出 67,660／总量 598,317 Token，50 份 usage 完整；预算未耗尽，不自动续跑或扩大权限。001／004 与新报告 docs/evidence/self-test-full-flow-deepseek-validation.md 保留失败及职责／装配／所有权一致性问题。没有修改服务实现或正式任务，完整自主交付仍未通过。

2026-09-18：真实 DeepSeek 验证新自测协议，复用合成产品及固定设计，首次加法自测前注入 a-b；真实测试 10 项中 8 项失败，模型修复后重测 10 项通过再提交，平方／UI 自测 20／43 项通过再提交。程序独立复验、全量 Node 43 项、真实启动／系统 Playwright 通过，独立 Chromium 18 组通过、页面异常 0，最终 waiting_acceptance。只修改加法实现，测试及其他产物字节未改，未人工代提交。新增 10 次实际 HTTP，输入 64,629／输出 962／总量 65,591 Token；累计 287／300 次、1,812,883 Token。已有一个真实自测失败→修复→重测→提交→后续验证成功样本，稳定性、从零交付及大任务能力未验证；用户未验收。004 和原验证报告已追加全过程，原失败与本轮摘要故障标志纠正保留，正式任务未续跑。

2026-09-18：按用户确认调整为开发先自测后提交。新增受控 run_unit_tests，固定当前及已完成单元测试范围；真实结果与文件版本绑定，未测、失败、缺文件或版本过期均不能提交。开发获得结果后修复并重测，检查点恢复仍需有效自测证明；旧无证明提交不能复用。旧失败标记版本适用性，交接提示依当前自测状态；后续独立测试、集成及浏览器门禁保留。完整 171 项回归通过（本轮新增 7 项，Fake 模型、真实工具／Node），语法与差异检查通过，架构问题 004 和验证报告已更新。确认正式 active_tasks=0、pending_events=0 后重启 Worker，4647→18505，Task25／26 状态不变，未续跑任务。没有新增付费调用，累计仍 277／300 次；真实 DeepSeek 在新协议下的交接可靠性和完整交付未验证，用户未验收。

2026-09-18：用户授权定位未提交循环。核对实际请求、响应及代码，纠正此前「从零 UI 停滞」记录：实际停在平方模块第一次测试失败后的修复，尚未进入 UI。修改后仍携带旧失败并提示继续修复，反馈虽有哈希但未用于当前版本适用判断；UI 返修也持续携带旧诊断，写入状态摘要未包含账本已有的动作说明。模型响应多次明确指出旧报告与新文件矛盾。独立运行从零样本现存加法／平方测试，退出 0、Node 汇总 7 项通过，仅用于诊断，未代提交或改变原任务。004 和验证报告已更新；建议补证据版本状态与简短修复动作摘要，尚未确认实施或验证因果改善。没有新增付费调用，累计仍 277／300 次；未修改运行逻辑。

2026-09-18：已按用户确认实现 submit_unit_for_test 显式交接、提交版本恢复／失效、4 轮提醒／8 轮无进展停止，以及只读集成责任诊断、归属／置信度校验、责任单元修复和不确定回澄清。完整 164 项回归（新增 22 项）、语法和差异检查通过。从零真实固定设计开发新增 16 次，平方返修后未再次提交、无进展停止，未进入 UI（原记录已纠正）；返修夹具首次注入不可达、不作成功证据，修正后的首样本正确归因 UI 但未提交，16 次停止；新夹具 7 次完成 UI 脚本修复、显式提交、Node 43 项与系统浏览器验证，独立 Chromium 18 组通过，waiting_acceptance。该成功样本未触发提醒，不归因提示调整；原失败保留，完整从零自主交付与真实跨模块修复未通过验证。本轮新增 39 次／335,804 Token，累计 277／300 次、1,747,292 Token。确认正式任务／事件为空后重启 Worker，PID 4647，Task25／26 状态不变。003 更新过程与结果，新增 004 交接问题记录。证据见 `docs/evidence/unit-handoff-repair-validation.md`，用户验收未执行。

2026-09-17：按用户委托建立 `docs/architecture-issues/`，已回溯记录开发粒度与测试门禁、工具上下文与执行记忆、集成失败返修责任三个架构问题。每问题独立文件保留依据、过程、方案取舍、真实测试和成本、当前决定与未解决状态；AGENTS.md 与文档目录约定已补充后续维护规则。记录链接、数据及差异已核对，无代码修改或新增模型调用；更早历史架构问题尚未全面回溯。

2026-09-17：已复用工具摘要账本实现按文件聚合有效读取／写入状态，核对完整性与当前哈希，取消自动最近一批完整交互；按需数据去重，旧检查点回退保留，加入测试版本与开发交接提示。142 项回归通过。真实同设计探针新增 26 次／120,824 Token，完成逐单元开发、Node 23 项和启动；生成浏览器脚本保留 B=1000 却断言 (4+B)^2=16 导致验证失败，返修数学单元收到越范围反馈后等待设计澄清。独立 Chromium 18 组通过、页面异常 0，完整自主交付仍未通过。累计 238／300 次、1,411,488 Token，不声称成本收益。确认正式无运行任务／pending Event 后重启 Worker，PID 94856，Task25／26 状态不变，用户验收未执行。证据见 `docs/evidence/effective-tool-state-validation.md`。

2026-09-17：已按用户授权隔离比较仅当前必要上下文，不自动携带完整工具历史或摘要。第一固定设计变体 65 次／447,867 Token 完成，但有读取全文与快照重复干扰；去重后复测 100 次／571,166 Token，反复读取至既有 Step 100 次上限 failed，独立产物 Node 18 项／Chromium 18 组操作通过不替代自动流程完成。原同设计摘要样本 13 次／63,318 Token，非严格 A/B，不支持切换正式策略。无预置设计复测新增 7 次，计划三次非法单元标识纠正后 failed。此次新增 172 次／1,061,066 Token，累计 212 次／1,290,664 Token，低于全测试 300 次上限；完整真实自主流程仍未通过。正式服务策略未切换，137 项回归通过，用户本人验收未执行。证据见 `docs/evidence/current-only-context-validation.md`。

2026-09-17：已按用户授权提高模块／功能真实 DeepSeek 测试累计 HTTP 上限到 300 次，实际累计 40 次。固定设计开发探针新增 3 次，完成逐单元开发、Node 43 项、启动和生成浏览器验证，进入 waiting_acceptance；独立 Chromium 18 组操作通过，页面异常 0。无预置设计的自主复测新增 7 次，在开发计划三次纠正后仍因 UI 整模块／功能单元重叠 failed，未触及总预算。完整自主链路仍未通过；正式业务库、默认 Step 预算与生成代码未人工修改。137 项项目回归通过，用户本人验收未执行。证据见 `docs/evidence/unit-workflow-300-validation.md`。

2026-09-17：已按用户确认接入模块／功能计划、共享契约与独立 Dev Design，以及逐单元程序测试、失败反馈、有界修复、版本恢复与最后集成验证。137 项回归通过。三十次真实 DeepSeek：自动设计到平方功能测试方案冲突后等待澄清；固定合成设计开发探针完成两个功能，Node 20 项及部分界面独立 Chromium 14 项通过，产物未齐便预算耗尽。完整真实自主链路未通过验证，最后的计划提示与依赖设计上下文补充未完整真实复跑。正式空闲 Worker 已加载最终实现，PID 88183；原任务状态不变。证据见 `docs/evidence/unit-workflow-validation.md`。

2026-09-17：工具摘要策略未通过真实 DeepSeek 测试。原多模块流程因文档输出默认 8K 截断中断；隔离副本显式设 16K 后完成设计，但生成 7 个文件后重复读取，未完成产品；历史查询探针的三个查询和 read 均返回正确结果，模型仍循环至 8 次预算耗尽。共实际 83 次 HTTP 请求（上限 200），81 个完整返回报告 2,027,994 Token，另两次中断用量未知。近期读取保留策略、文档输出上限与无进展停止规则待用户决定，未修改正式实现。115 项机制回归通过不能替代真实任务成功。证据见 `docs/evidence/tool-summary-deepseek-validation.md`。

2026-09-17：已按用户确认方案实现工具执行摘要账本与三个历史查询工具，模型上下文保留最近一批完整交互及最近 20 条较早摘要，逐调用刷新文件版本和返修快照，原始 Trace／检查点保持完整。115 项后端回归通过；已有计算器 Node 22 项及 Chromium、多模块 Node 20 项及 Chromium、独立 13 组操作通过。无新增模型调用；真实 DeepSeek 新工具使用和成本收益待验证。正式空闲 Worker 已重启加载，用户验收待执行。证据见 `docs/evidence/tool-summary-validation.md`。

2026-09-17：已保存用户委托的多模块内容管理工具需求草案，并按用户确认范围执行隔离全 DeepSeek 基准；总 HTTP 上限 200、实际 66 次，总量 3,642,376 Token。生成 Dev Design、四业务模块和 localStorage 产品，原自动任务因固定根目录 app.js 校验与实际 js/app.js 入口冲突 failed，保留原状态。未人工修改生成代码，单独诊断任务通过 Node 20 项、生成浏览器验证及独立 Chromium 13 组操作（含同端口服务真实重启持久化），测试验收后诊断任务 succeeded。正式后端 91 项回归、脚本语法和差异检查通过。正式服务、预算和 MySQL 未修改；不宣称完整无干预基准成功，Windows、增量变更及用户验收未验证。证据见 `docs/evidence/content-workbench-baseline.md`。

v1 最小完整链路已经实现。v2 全过程实时可视化、人工验收问题自动分类路由及设计阶段动态 Transition Planner 已实现并通过机制测试。Task 23 已运行到 V2 软件验收，但此前生成的软件未实际吸收修改，不能视为验收通过；Windows 环境仍待验证。

## 已完成

- 2026-09-18 显式提交与集成责任路由机制已实现并验证：提交不声明测试通过，绑定完整文件版本；无进展计数覆盖交替读、换描述、同字节写；诊断无写权限，拒绝非法／低置信归属，只给责任单元反馈。新增 22 项及完整 164 项回归、真实单模块脚本故障修复夹具通过，正式空闲 Worker 已加载。真实从零失败、首轮返修未提交失败及未验证范围见当前阶段与 `docs/evidence/unit-handoff-repair-validation.md`，不宣称任意软件自主生成能力。

- 2026-09-17 架构问题记录约定与首批三份文档已补齐并核对：`docs/architecture-issues/README.md` 维护索引，001 开发单元、002 工具执行记忆、003 集成失败责任归属。普通 bug／提示词调整不单独归档，失败与未解决事项保留，问题记录不替代有效设计或授权新方案；本项完成指文档补齐，不指三个架构问题全部解决。

- 2026-09-17 有效工具状态投影已实现并验证：复用原账本，逐文件合并当前循环最新读取／写入，核对版本与截断读取，按需数据与当前快照去重，恢复不重复执行；补充真实程序测试版本和交接状态。5 项新增及完整 142 项回归、语法、差异检查通过，正式空闲 Worker 已加载。真实交付与反馈路由限制见当前阶段及 `docs/evidence/effective-tool-state-validation.md`，未宣称用户验收通过。

- 2026-09-17 模块／功能流程机制已实现并验证：新架构生成版本化开发单元计划，校验 DAG、文件所有权和非空测试；共享契约先评审，随后逐单元独立设计，根级 Dev Design 仅为索引。开发仅写当前单元，持续刷新其与直接依赖内容，程序执行当前与先前单元测试；真实失败反馈最多两次修复，旧通过仅在依据与文件哈希一致时恢复，设计缺口回设计阶段。新增 22 项回归，完整 137 项、语法与差异检查通过；不改数据库 schema、Provider、正式预算、存储或产品依赖限制，旧任务保留入口。真实 DeepSeek 三十次部分验证，输入 121,765／输出 36,439／总量 158,204 Token，未完成完整自主交付，未声称成本下降。最终确认无运行任务或 pending Event 后重启 Worker，PID 88183 存活；Task25 waiting_acceptance、Task26 failed 不变。证据见 `docs/evidence/unit-workflow-validation.md`。

- 2026-09-17 工具执行摘要与按需查询：每个工具关联父逻辑模型请求，写入记录实际前后 SHA-256、操作目的及 Trace 引用；新增文件修改历史、模型调用批次摘要和原始执行详情查询，固定分页并限制当前任务。上下文缩减较早历史，保留未解决失败和版本过期标记；返修允许 read 与查询，文档写入阶段及无工具 Planner 权限不扩展。13 项新增机制测试、完整 115 项回归及差异检查通过，真实已有产物回归通过。确认运行任务和 pending Event 均 0 后重启单 Worker，PID 82885 存活；Task25 waiting_acceptance、Task26 failed 不变。未改数据库 schema、正式预算或产品约束，未执行真实 Provider 新工具验证、未宣称 Token 收益、用户验收待执行。证据见 `docs/evidence/tool-summary-validation.md`。

- 2026-09-17 按用户确认方案修复固定计算器入口：固定文件收敛为 index.html、verify_product.py、implementation.md，校验 HTML 直接本地脚本/样式引用；Node 全阶段统一自动发现，缺少测试不得通过；开发不因入口齐全提前截断，返修覆盖实际子目录及新增文件并刷新可覆盖路径。102 项后端回归及差异检查通过；Task25 产物 Node 22 项和真实 Chromium 检查通过，多模块原产物 Worker Node 20 项、浏览器验证及独立 13 组操作通过（含真实同端口重启持久化）。无新增模型调用，未重跑真实 DeepSeek 完整生成链路，未改原失败状态。确认正式运行任务和 pending Event 均 0 后重启单 Worker，最终 PID 73874 存活；Task25 waiting_acceptance、Task26 failed 保持不变。正式单模块/存储约束及预算未改，工具历史压缩未实施，用户验收待执行。证据见 `docs/evidence/product-entry-fix-validation.md`。

- 2026-09-17 固化计算器 Context 手动回归基准：`tests/context_calculator_baseline.py` 和 `tests/context_calculator_acceptance.py`，普通 pytest 不触发付费测试。隔离旧 context 重建样本15次DeepSeek调用、0轮返修、一次架构澄清，Node30项及固定独立Chromium22项通过，测试用户验收后 succeeded；实际总量173,720 Token。封装首次合成开发依据的换行与旧版不逐字相同，已修正并增加实际发送体保存；修正后未真实复跑，不视为严格A/B。方法、限制及预算见 `docs/evidence/context-calculator-baseline.md`。当前项目优化保留，正式服务和业务库未变更，用户正式验收未执行。

- 2026-09-17 完成 Context 优化后的隔离全 DeepSeek 完整链路：真实需求门径／文档、架构、Dev Design 跳过判断、开发、Node 35 项、HTTP 启动、浏览器验证及一次返修均执行；独立 Chromium 22 项操作检查通过，测试用户提交验收后隔离任务 succeeded。14 次真实调用，输入 101,787／输出 25,461／总量 127,248 Token，无优化前完整对照，不宣称成本下降。候选仍保留开放问题章节，测试用户明确确认边界；真实用户验收与 Windows 未验证。后端 91 项回归及差异检查通过。证据见 `docs/evidence/context-full-deepseek-validation.md`；正式任务／数据库／运行配置未修改。

- 2026-09-17 完成 Context 第一步的两次真实 DeepSeek 信息保留对比：从当前产品门径捕获上下文并重建去重前样本，使用相同自定义提取指令，七项行为均符合且两次输出一致。输入用量 344→341 Token，输出均 45 Token；短样本节省仅约 0.87％，不宣称明显成本收益。隔离内存库，无正式任务或业务库变更，不执行工具。方法、结果与限制见 `docs/evidence/context-step1-deepseek-validation.md`；开发返修与完整产品链路未验证。本次仅测试和证据文档更新，无服务代码变化，无需重启。

- 2026-09-17 完成 Context 第一阶段优化：产品门径／Draft、新任务设计 Planner 和开发中的正式需求仅保留一份；成对回答不再重复列入用户请求，Reviewer／Candidate 仍完整获取初始请求与问答；无旧 Dev Design 时不附全文式差异，设计变更 Planner 不重复 input 差异。开发／返修增加文档来源和哈希、轮开始时文件快照及失败证据归属；历史验证文件版本明确为未知，新受控复验绑定实际文件哈希。91 项后端机制测试及差异检查通过。确认运行中任务和待处理事件均为 0 后重启单 Worker，PID 61932 存活，Task 26 查询正常且仍为 failed。未执行真实 Provider 对比，Token 节省和实际返修收益待验证；工具历史压缩和轮内动态刷新未实施。

- 2026-09-16 经用户授权重启单 Worker 加载返修修复：重启前运行中任务和待处理事件均为 0，旧进程已退出，新 Worker PID 32889 存活；API 查询成功，Task 26 仍为 failed，未自动续跑。
- 按用户要求补充本地服务重启约定：服务代码修改并验证通过后，默认重启受影响服务；可能中断运行中任务时先确认，不自动续跑失败任务或修改数据库状态。已核对规范内容，本次仅更新协作约定。
- 修复 task26 暴露的返修反馈退回旧错误及代码快照过期问题：每轮刷新实际文件，保留最新受控验证结果；后续无写入耗尽时标明此前验证失败。生成提示要求验证脚本使用系统传入的产品 URL，task26 脚本已去除固定端口自建服务。后端 91 项测试、task26 Node 测试 23 项、真实 Chromium 检查 21 项及差异检查通过。未修改历史 Trace／数据库状态，未续跑真实模型任务；运行中的 Worker 尚未重启加载本次修复，用户验收待执行。

- 修正请求配置 `max_completion_tokens` 非负整数值被误脱敏的问题，凭据及非整数值继续脱敏；4 项 Trace 测试和差异检查通过，空闲单 Worker 已重启加载修改。历史 Trace 不倒填。

- 增加每次模型响应的 Token usage 展示，保留 Provider 实际输入／输出／总量和缓存用量；修正 Token 计数误脱敏，凭据仍脱敏，缺失用量不记零、不补写历史。DeepSeek 开启流式 usage，支持空 choices 的用量结尾及非空 choice usage。后端 90 项测试、前端构建和差异检查通过；真实 Provider 用量尚未验证。

- 取消新调用的逐片段 `model_stream_delta` Trace 和最终响应中的 `stream_events` 数组；审计保留完整请求、合并响应、工具和状态记录，调用中断保存部分响应及错误。前端改读系统临时目录的当前回答快照，调用结束清空，旧任务历史不删除。后端 88 项测试、前端构建及模拟接口的真实 Chromium 展示验证通过，`git diff --check` 通过。2026-09-16 经授权确认无运行中任务及待处理事件后，重启正式 API 与单 Worker；健康检查、前端代理查询 Task 25、新增 live-response 接口均返回成功，Task 25 仍为 waiting_acceptance。未执行真实 Provider 调用。

- 建立提示词注入相关工具权限基线：5 个临时工作区测试固定 `read` 拒绝越界、`write` 可覆盖 Trace 详情、`exec` 可读取／写入任务工作区外文件，以及失败文字会进入返修模型循环的当前行为；报告见 `docs/evidence/prompt-injection-tool-boundary-baseline.md`。

- 产品返工门径修复：正式产品文档存在且本轮验收反馈已高置信度分类为需求变更、一致性通过、逐条具备现状／期望／可执行例子时，明确反馈直接覆盖冲突的旧条款，不再重复向用户确认；不明确反馈仍在验收阶段澄清。Task 24 两条反馈的回归测试及完整后端 56 项机制测试通过；Task 24 真实续跑与新版软件验收尚未执行。

- 为后端 14 个 Python 文件补充中文说明，并将后续后端方法用途、关键步骤和关键调用的注释要求写入 `AGENTS.md`；函数覆盖检查、语法编译及 55 项后端测试通过。

- 完成 v2 全过程实时可视化：七阶段时间线、阶段动作流、动作详情、历史查看、自动跟随和 URL 刷新恢复。
- 新增不可变 `TraceRecord` 索引模型与任务工作区 JSON 详情，覆盖模型请求／响应、传输重试、工具调用／结果、程序校验、用户事件、返修及状态转换。
- 新增 Trace 增量查询与详情接口；列表不返回大文本，详情严格限制在当前任务 `traces/` 目录。
- 完整模型 API payload 与原始响应永久保存；认证头不进入 Trace，已知敏感键递归脱敏。
- v2 后端 28 项测试通过，前端生产构建通过；真实浏览器验证增量追加、原始详情、历史查看、回到当前进度、URL 刷新恢复且控制台无错误。
- 正式 MySQL 已新增并核对 `trace_records`：15 个字段、任务序号唯一约束、两个索引和两个外键符合设计；事务写入后回滚，未留下探针数据。
- 真实 DeepSeek 任务 20 已从产品门径运行至 `waiting_acceptance`，经历一次测试失败与自动返修，最终 39 项生成软件测试和真实 Playwright 验证通过；正式库与任务工作区保存 102 条／份连续 Trace，总计 1,155,391 字节，敏感键违规为 0。
- 补充 `cryptography==46.0.3` 项目依赖，使 PyMySQL 可以使用 MySQL 8 `caching_sha2_password` 认证。
- 新增 DeepSeek／Kimi Provider 配置切换，默认保持 DeepSeek；Kimi 使用独立密钥文件、可配置端点与模型 ID，并复用现有工具调用、传输重试和消息协议。
- 模型请求、响应与重试 Trace 记录实际 `provider` 和 `model`；Kimi 封装、密钥读取、Provider 选择及 Trace 标识已通过机制测试和真实调用验证。
- Kimi Code 真实模型列表、最小 Chat Completions、无工具 Agent Step 及真实 `write` 工具调用均已通过；两次 Agent 验证都只消耗 1 次模型调用，并保存完整模型／工具 Trace。
- 新增按阶段固定模型路由：需求文档、架构设计、Dev Design 使用 Kimi Code；开发、测试、启动、浏览器验证及返修使用 DeepSeek，失败时不自动切换 Provider。
- Kimi 长文档真实调用出现统一 60 秒 `ReadTimeout` 后，将传输超时改为 Provider 独立配置：Kimi 180 秒、DeepSeek 60 秒；保留最多 3 次传输重试并记录 Trace。
- 模型返回非法工具参数 JSON 时，保存失败原始响应 Trace，并将下一次尝试作为新的逻辑调用计入 Step 上限，避免单次模型格式错误直接终止任务。
- Kimi 单次输出限制为 8192 Token，防止长文档响应无界增长并阻塞数据库持久化；可通过启动配置覆盖。
- 真实混合模型 Task 23 已完成：需求、架构、Dev Design 全部由 Kimi Code 生成，开发由 DeepSeek 完成，随后通过 33 项生成软件测试和 37 项真实 Playwright 验证，进入 `waiting_acceptance`。
- 人工验收反馈改为由系统自动分类：Kimi 对照正式需求、架构、Dev Design 和验证证据给出固定结构建议，程序校验后路由到最早失效阶段；低置信度时等待用户补充，完整判断保存为 Trace 和任务工作区证据。
- 支持需求、架构和 Dev Design 的版本化返工，旧正式文件不再导致返工阶段被跳过；实现问题携带原始验收反馈进入 DeepSeek 返修上下文。
- 前端不再要求用户选择“疑似缺陷”，改为统一“报告问题”，并明确区分自动验证通过和人工验收通过。
- 产品需求阶段新增独立 AI Review：Kimi Product Draft、按“阻塞问题／普通问题／建议”分类的 Review、根据 Review 修订的 Candidate 分别永久保存，用户只预览和批准 Candidate。
- 架构和 Dev Design 阶段新增 Transition Planner：同时读取新旧上游正式产物、统一差异、旧下游正式产物及验收分类，受固定动作枚举和置信度校验约束，动态决定增量修订、复用或澄清；各版正式文档与判断证据永久保存。
- 开发阶段新增实现血缘校验：Dev Design 内容变化时，即使六个产品文件全部存在，也必须携带前一版设计、设计差异、当前代码和验收分类执行增量修改并更新血缘，不再以文件存在代表实现完成。
- 人工验收分类新增结构化行为变更契约，强制区分 `current_behavior`、`expected_behavior` 和 `acceptance_examples`；需求变更缺少合法契约时转为澄清。产品 Candidate 新增独立逐条覆盖校验，写反、遗漏或不可验收的变更不能进入审批。
- Kimi 阶段新增 DeepSeek 技术降级：Kimi 的传输重试耗尽、HTTP／凭据调用错误或响应协议错误时，同一逻辑调用携带原始上下文降级到 DeepSeek；不因业务输出不理想而切换，且 DeepSeek 失败后不循环回切。
- 新增任务工作区问答与产物账本：问题和回答以不可拆分条目写入 `evidence/conversation-turns.json`；成功 `write` 写入 `evidence/artifacts.json` 并记录请求路径、解析路径、文件名、创建／覆盖、字节数、SHA-256、StepRun、工具调用和来源问答。产品 Context Builder 使用当前正式需求与成对问答，避免只传“是的／忽略它”等失去指代的用户回答。
- 任务页改为左右双栏：左侧按时间合并用户／模型消息与模型调用、原始返回、工具和文件缩略信息；右侧以人可读层级展示完整调用内容、原始 Provider 事件、工具参数／返回值及任务工作区文件内容。模型 Provider 改用真实流式响应，文本增量通过永久 `model_stream_delta` Trace 实时恢复。
- 返修上下文按最近失败阶段选择证据：Node 测试失败使用 `test-report.md`，浏览器验证失败使用 `verification-report.md`，启动失败使用 StepRun 错误。模型结束但文件无变化时将失败报告与文件哈希反馈模型，最多纠正两次；文件有变化后由系统使用受控运行环境复跑最初失败的验证，通过后才能离开 Develop。
- v2.1 可靠返修闭环已完成：模型调用、Provider 传输、跨阶段返修、无变化纠正、相同工具动作和连续无写诊断分别使用独立预算；第三次相同工具动作及返修中第六次连续非写动作由程序阻止，生成 `tool_guard` Trace 和失败 ToolResult，引导模型停止无效循环。

- 创建 `AGENTS.md`、`README.md`、`ROADMAP.md`、`.gitignore` 和 `docs/README.md`。
- 固化协作权限、设计所有权、评审方式、实施约束、安全与成本边界、验证和文档维护规则。
- 记录已确认产品方向与首版验收意图，明确产品尚未实现。
- 写入用户确认的产品评审口径：只需明确「要做什么」「为什么要做」「怎么算成功」，不按完整 PRD 要求审查，其余细节允许后续明确。
- 写入用户确认的架构与 Dev Design 评审规则：架构看整体方案能否支撑当前需求，Dev Design 看实现和验证依据是否明确；仅评审当前版本必需内容，关键决定由用户作出。
- 完成首版产品需求文档，明确本地单用户计算器场景、核心流程、验收要求与 v1 范围。
- 完成并确认架构设计 v1：采用 React、FastAPI、MySQL、Worker Runtime 和 DeepSeek V4.1 Flash。
- 明确 MySQL 承担运行状态持久化与轻量任务队列职责，Worker 通过原子领取和恢复机制执行任务。
- 明确开发阶段包含有界的「开发—测试—修复」循环，并通过 `exec` 完成测试、启动与健康检查。
- 明确每个任务使用独立 Task Workspace，运行状态以 MySQL 为权威来源。
- 完成并确认 Dev Design v1，明确四张数据表、状态机、API 语义、Event 消费、模型与工具协议、各 Step 流程和异常恢复规则。
- 将 v1 固定为严格单 Worker、三个工具和单模块流程；模型调用、返修、命令时间及输出均设置硬限制。
- 固定生成软件为原生 HTML、CSS、JavaScript，使用 Python 静态 HTTP 服务、JavaScript 单元测试、HTTP 健康检查及 Python Playwright 真实浏览器验证。
- 实现 React 任务页面、产品文档预览／批准、过程消息、最终访问地址和人工验收交互。
- 实现 FastAPI 任务、事件、消息、文档预览及产物接口，以及 Task、StepRun、Event、Message 四表模型。
- 实现严格单 Worker 的七个固定 Step、事件消费、状态推进、调用／返修限制、运行中 Step 恢复和失败证据。
- 实现 DeepSeek V4.1 Flash（API 模型 ID `deepseek-flash`）直接调用及 `read`、`write`、`exec` 三工具，包含工作区路径校验、原子覆盖、超时、截断和后台进程记录。
- 24 项后端机制测试通过；React 生产构建通过；FastAPI 实际启动及四个 HTTP 冒烟请求通过。
- 已在 Docker MySQL 8.4 的独立 `dev_team_simulator` 数据库创建四张表，结构、约束及事务关联写入／回滚验证通过，未改动原 `id_photo` 数据库。
- 项目 ORM 已真实连接 MySQL 8.4.11，并完成四表事务写入／回滚；`exec` 后台服务启动、HTTP、状态、停止和端口释放验证通过。
- Playwright Chromium 已安装；真实 Chromium 已完成 React→FastAPI 创建内存任务联调；前端运行依赖审计为 0 个已知漏洞。
- 已实现从 Git 忽略的独立文件读取 DeepSeek Key；真实密钥由用户填写，开发助手不读取、搜索或输出其内容。
- DeepSeek 官方实时模型列表确认 V4.1 Flash API ID 为 `deepseek-flash`；最小真实调用返回 `OK`，真实 `product_docs` Step 已生成候选并进入 `waiting_user`。
- 真实 Step 发现并修复两个问题：模型缺少 v1 固定边界导致候选越界，以及产物已验证后仍等待模型自述导致调用耗尽；修复后真实 Step 从 10 次失败收敛为 1 次调用成功。
- 真实任务 `v1-real-e2e-calculator` 已完成五轮产品澄清与批准，随后完成架构、Dev Design、开发、18 项生成软件单元测试、HTTP 启动和 29 项真实 Chromium 验证。
- 全链路发现并修复模型消息历史缺失、工具结果协议错误、远端断连无重试、生成路径错误、健康检查继承代理、停止服务遗留子进程，以及 Playwright 跳过仍被误判成功等问题；验收缺陷反馈可将任务退回测试并重新进入有效门禁。
- 已由开发助手按用户授权代行测试用户完成最终验收，任务 3 状态为 `succeeded`；用户本人操作验收仍未执行。
- 产品阶段已拆分为两个真实门径：存在阻塞性问题时只进行问答且不生成 Draft；模型判断无阻塞后才生成 Draft；用户批准后才原子生成正式 `product.md`。前端据 `product_document_available` 分别展示问答或审批界面。

## 进行中

- v2.3 结构化任务记忆：按用户委托形成 `docs/DEV_DESIGN_V2_3_AI_DRAFT.md`，并补充隐藏字段与实现细节的 `docs/ARCHITECTURE_V2_3_AI_DRAFT.md`，说明组件职责、数据流、确认和恢复边界。两份文档待评审和确认，代码未实施，不替代当前有效设计。

- v2.2 已将已有产品的未通过验收反馈统一交给 Planner，并提供已验收任务的 `change_request` 小功能入口；合成已有产品小功能的全 DeepSeek 连续运行已验证。新建任务的产品需求获批准后也可由 Planner 根据正式需求与固定约束跳过不必要的架构／Dev Design；合成简单加法软件全 DeepSeek 运行已验证跳过两份设计后仍完成开发、Node／HTTP／Playwright 并进入人工验收。用户本人验收、正式 Kimi／DeepSeek 混合路由下的同一完整链路仍待验证；草案中的 ActionRun 等完整方案未实施。

- Task 23 已基于用户补充重新生成产品 V3 Draft、Review 和 Candidate；独立覆盖校验确认两项变更均覆盖，当前在 `waiting_user / product_docs` 等待用户审批 V3。旧 V1／V2 文档、错误分类、错误开发尝试和全部 Trace 均保留。

## 后续迭代计划

以下事项按顺序推进。每次只选择一个版本实施，通过对应真实任务验证后再进入下一版本；计划不是已完成能力。

### v2.1：可靠返修闭环

目标：模型修错或没有修改时，系统能给出正确证据并进行有界纠正，不发生错误放行或无效循环。

- 每次行动后由程序判断文件是否真实变化、原失败验证是否通过、工具是否成功、必需产物是否存在。
- 按失败来源选择证据：Node 测试使用 `test-report.md`，浏览器验证使用 `verification-report.md`，启动失败使用对应 StepRun 错误。
- 无文件变化时把完整失败证据和文件哈希反馈模型，最多纠正两次。
- 文件有变化后由系统复跑原失败验证，通过后才能继续。
- 分别限制模型调用、无变化纠正、测试返修和 Provider 传输重试次数。
- 识别重复命令、连续无效读取、只声明修改但没有 `write`、反复查找环境等无效行为并及时停止。

完成标准：使用故意缺少浏览器事件绑定或验证入口错误的真实任务，系统在一至两次返修内定位并修复；原失败 Playwright 用例通过后才进入下一阶段，且不出现无意义的环境探测循环。

当前状态：已完成。失败报告选择、无变化重试和原失败验证复跑已在 Task 24 真实验证；独立预算、重复工具动作和连续无写诊断保护已通过故障注入测试。

### v2.2：动态 Next Action Planner

目标：将固定全阶段流水线改为“固定治理边界＋模型动态选择下一行动”，只执行当前任务真正需要的步骤。

Planner 只允许返回以下动作：

- `inspect`
- `clarify`
- `update_requirement`
- `update_architecture`
- `update_dev_design`
- `modify_code`
- `run_test`
- `start_product`
- `verify_product`
- `finish`

每次决策输入包括当前任务目标、已确认决策、当前有效文档版本、最近行动与结果、当前失败、未解决问题、可用工具和剩余预算。程序校验动作枚举、依赖、重复无效行动、审批边界和 `finish` 完成条件。

首批只覆盖两类任务：

1. 修复 Bug：分类 → 检查 → 修改 → 原失败测试 → 回归测试 → 产品验证 → 人工验收。
2. 现有产品增加小功能：判断需求／设计影响 → 更新必要文档 → 增量修改 → 测试 → 产品验证 → 人工验收。

完成标准：新建软件仍能执行必要设计门径；明确实现缺陷不重新生成无关需求和设计；读取一个文件证据不足时 Planner 能继续检查相关文件，而不是机械进入下一固定阶段。

### v2.3：结构化任务记忆

目标：避免每次临时拼接全部历史，确保模型记得已确认事项、自己的问题和用户回答。

- 当前工作状态：当前目标、问题、最近行动、行动结果和待决策事项。
- 已确认事实：用户确认的产品行为、不得重复询问的决定、当前有效需求和设计版本。
- 工作证据：失败测试、文件差异、工具结果和写入产物。
- 完整 Trace：保留原始模型输入输出、工具调用和历史文件版本，只在调查历史问题时检索。
- 模型问题与用户回答作为不可拆分问答条目；写文件行为关联对应问答、文件名和工作区路径。

完成标准：切换 Kimi／DeepSeek 或重新发起模型请求后，不重复询问已回答问题；模型能准确引用上一个问题、用户答案及由该答案产生的文件。

### v2.4：上下文选择器与 Token 可视化

目标：在不遗漏关键证据的前提下降低重复上下文 Token 消耗。

每个上下文项目记录 `type`、`source`、`related_goal`、`related_step`、`created_at`、`superseded_by`、`importance` 和 `token_estimate`。

- 当前用户消息、直接关联的成对问答、当前正式需求／设计和当前失败报告必须包含。
- 被新版替代的文档默认排除；发生设计变更时包含新旧版本差异和旧下游设计。
- 生成软件的代码文件增多时，开发和返修不再一次性把所有代码文件全文送入模型；先提供文件清单、当前目标、正式设计差异和失败证据，再按需检查相关文件。一次检查证据不足时允许继续检查其他相关文件，并记录选择依据。
- 工具大输出只传相关片段与摘要，完整内容继续永久保存在任务工作区。
- 模型调用详情展示上下文选择／排除原因、Token 估算以及摘要或截断情况。

完成标准：同一任务连续多轮调用时上下文 Token 不随完整历史线性增长；多文件开发或返修不依赖一次性传入全部代码正文，模型能按需定位受影响文件并完成相关修改与验证；人为抽查仍能看到每条关键上下文的选择理由。

### v2.5：可验证完成条件

目标：模型文本声明不能直接改变任务事实状态。

- 修改文件：成功 `write` 且文件内容哈希变化。
- 修复 Bug：原失败用例通过。
- 完成开发：必需文件存在且相关测试通过。
- 完成测试：命令退出码为 0、没有跳过标记、报告完整。
- 启动产品：进程存活且 HTTP 健康检查通过。
- 验证产品：真实浏览器用例通过。
- 更新文档：产生新版本、AI Review 通过并获得用户批准。
- 完成任务：当前所有验收标准均有对应证据，随后等待用户最终验收。

完成标准：模型即使回答“已完成”，只要缺少程序证据，任务仍不能进入下一状态。

### v2.6：需求到验证的追踪关系

目标：防止“测试全部通过，但用户新需求没有实现”。

- 为每条需求生成稳定 ID，例如 `REQ-001`。
- 建立需求 → 架构章节 → Dev Design → 修改文件 → Node 测试 → Playwright 验收用例的关联。
- 需求变更后判断哪些下游产物需要修改、哪些可以复用。
- 验收时逐条检查需求证据，不再只检查测试总数。

完成标准：修改一条需求时，系统能列出受影响设计、代码和测试；任何当前需求缺少验证证据时不得报告软件完成。

### v2.7：失败模式识别与策略切换

目标：系统根据重复失败模式主动收窄任务或更换策略。

首批识别：

- 连续读取文件但没有形成诊断假设。
- 重复运行相同命令且结果不变。
- 声称写文件但没有成功 `write`。
- 修改文件后没有运行相关测试。
- Node 测试通过但真实浏览器持续失败。
- 反复查找环境或依赖。
- 重复询问已确认问题。
- 新需求已确认但继续引用被替代的旧需求。

处理策略：第一次反馈矛盾与证据；第二次收窄工具和下一目标；第三次停止当前策略并要求重新诊断；仍失败则停止自动调用并等待用户，不执行无界循环。

完成标准：为每种失败模式建立故障注入用例，系统能在规定次数内切换策略或停止，并保存完整决策 Trace。

### v3：逐步扩展任务类型

只有 v2.1—v2.7 的执行、上下文和验证机制稳定后，才按以下顺序扩大产品范围：

1. Bug 修复任务。
2. 现有产品小功能迭代。
3. 新建简单前端应用。
4. 带后端 API 的应用。
5. 带数据库的应用。
6. 跨模块重构。
7. 外部 API 集成。

每增加一种任务类型，都使用未针对性调试过的真实评测验证；不能以同一个计算器任务证明通用能力。暂不增加多 Agent、更多角色或更多模型，除非单 Agent Runtime 的真实评测证明存在明确收益。

## 待办

- 在 Windows 正式环境验证 MySQL 连接、任务恢复和运行命令。
- 在 Windows 正式环境复跑一次相同的真实计算器任务。

## 阻塞与待确认

- 当前无已知设计阻塞。
- 尚未在 Windows 环境运行；用户本人尚未操作生成软件验收。
- v1 只有路径与进程级最小隔离，不是真正的安全沙箱；不得用于执行不可信需求或访问真实个人数据。

## 最近验证证据

- 2026-09-19：按用户授权修复素材管理全链路的计划归一、澄清传播、Reviewer 协议重试、公共操作唯一所有权、内部契约自动裁决、Dev Design 5000 字符上限与协议压缩反馈，以及自测通过后的单次提交窗口。修复后真实 DeepSeek 从空工作区完成产品、架构和逐单元 Dev Design，进入开发；四个单元通过并提交，`topics-crud` 因测试共享模块状态未收敛，第二次有界开发恢复遇到 HTTP 错误，最终仍为 `failed / develop`，未进入全量测试、启动或浏览器验收。实际 225 次 HTTP，总计 10,338,932 Token；Dev Design 占 7,748,016。证据见 `docs/evidence/content-workbench-baseline.md` 和 `/private/tmp/content-workbench-fixed-fullflow-20260919`。完成优先机制有进展，Token 目标未达成。

- 2026-09-17：模块／功能流程 137 项机制回归通过，包含 Fake 模型＋真实 Node 的故障、反馈修复与推进门禁。真实 DeepSeek 初始 5 次无效计划被拦截，修正后再 15 次在依赖测试方案上等待澄清；固定合成设计再用 10 次，完成加法和平方两功能及 Node 20 项，界面未齐预算耗尽。部分真实界面独立 HTTP／Chromium 14 项操作通过，初次错误提示位置的额外假设已纠正并保留原检查；完整链路和用户验收未通过验证。总三十次用量 158,204 Token，无对照。最终空闲 Worker 加载，原状态未变。详见 `docs/evidence/unit-workflow-validation.md`。

- 2026-09-17：执行真实 DeepSeek 多模块基准、输出上限调整的隔离诊断和历史查询探针，整体失败。摘要替换机制生效，但开发最后写入后连续 137 次读取同一组 7 文件；查询探针 16 次工具均成功且历史／当前原文正确，模型未给出最终结论。实际合计 83 次 HTTP；可核对用量下界 2,027,994 Token，未声称成本下降。保存原始输入／输出、账本、检查点及失败轨迹；未改正式配置或原任务状态，未对不完整生成软件执行验收。115 项回归、脚本语法及差异检查通过。详见 `docs/evidence/tool-summary-deepseek-validation.md`。

- 2026-09-16：按已确认的按需设计门径更新有效 Dev Design，再改 Worker 新任务入口。正式需求和固定项目约束送入 Planner，可跳过架构、Dev Design 或两者，保存输入哈希、引用证据及原因；开发和后续验收可使用跳过依据，不创建空设计文档。隔离合成整数加法任务临时全程使用 DeepSeek：13 次模型请求均为 DeepSeek，产品候选由测试用户批准，Planner 以 0.9 置信度选择 `modify_code` 并跳过两份设计，生成软件 Node 16／16、最终 HTTP 与 Playwright 通过，独立 Chromium 验证原始行为和错误后恢复，Task 进入 `waiting_acceptance`。试跑先暴露产品 Candidate 含待确认项、正式文档正文保留候选标题以及本地 HTTP 语义被误判，已修正测试输入和 Planner 固定语义；成功试跑两次启动健康检查失败、第三次成功，根因未确认。完整后端测试 84 项、前端构建通过，证据见 `docs/evidence/v2-2-new-task-design-skip.md`。

- 2026-09-15：按用户要求在隔离合成四则运算计算器上测试现有产品新增 Square 的完整链路，测试进程临时将文档阶段路由改为 DeepSeek；27 次模型请求的 Trace Provider 全为 DeepSeek。`change_request → update_requirement`、产品 Draft／Review／Candidate 与 3／3 覆盖校验、测试用户批准、架构与 Dev Design V2 修订、代码和测试增量修改，以及 `modify_code → run_test → start_product → inspect → verify_product → finish` 均完成；Node 10／10，真实 Playwright 和独立 Chromium 操作通过，任务进入 `waiting_acceptance`。首次单次传输试跑在架构 Draft 遇到 `ReadTimeout`，保留检查点；按现有最多三次重试复跑成功。项目代码和正式模型路由未改，用户本人验收未执行。证据见 `docs/evidence/v2-2-full-deepseek-feature.md`。

- 2026-09-15：新增已验收任务的 `change_request` 入口、设计阶段具体下一行动映射与非 Bug 动态闭环。需求更新仍先生成候选供审批；已确认设计缺陷不能复用对应阶段；非 Bug 变更即使设计文本未变化也不会跳过开发，小功能必须实际更新代码和测试。隔离合成乘法功能从已批准文档和已改代码开始，真实 Kimi 依次选择 `run_test → start_product → verify_product → finish`，Node／HTTP／Playwright 均通过，任务进入 `waiting_acceptance`。完整后端测试 76 项、前端构建和 `git diff --check` 通过；完整真实文档审批链尚未连续运行。证据见 `docs/evidence/v2-2-existing-feature-actions.md`。

- 2026-09-15：取消独立验收分类模型，将已有产品所有未通过验收反馈送进同一个 Next Action Planner；它可连续 `inspect` 并直接提议 `clarify`、`update_requirement`、`update_architecture`、`update_dev_design` 或 `modify_code`，程序从行动导出兼容分类、校验证据路径和审批门径。真实合成需求变更首次暴露“所有行动必须读代码”导致正确更新被误澄清，已收窄为只有实现缺陷须先读取产品代码。最终真实 Kimi 选择 `update_requirement → product_docs`，保存变更契约而未改正式需求；另一个合成 Bug 经 Kimi 实际读取 `app.js` 后选择 `modify_code`，DeepSeek 一次返修，真实 Node、HTTP、Playwright 后进入 `waiting_acceptance`。完整后端测试 68 项通过。证据见 `docs/evidence/v2-2-unified-acceptance-planner.md`。

- 2026-09-15：按已确认的 Bug 行动闭环更新当前有效 Dev Design，复用 Task／StepRun／Trace 实现有界 Next Action Planner，不改数据库 schema。程序计算可选行动，校验调查清单和重复读取，并将 Node 测试／浏览器验证绑定当前代码哈希；`finish` 再核对当前版本和 HTTP 可访问性，之后仅进入 `waiting_acceptance`。真实合成静态计算器先以 `BROKEN_CLEAR` 复现清除 Bug，真实 Kimi／DeepSeek 及 Node、HTTP、Playwright 跑通；最终行动为 `inspect → modify_code → run_test → inspect → inspect → start_product → verify_product → finish`，一次实际代码返修，Node／Playwright 均退出 0，浏览器输出 `[PASS] Clear displays 0`，第 9 次 Worker 轮询后任务为 `waiting_acceptance`。初次真实运行暴露正式测试前重复修改，已收紧 `test` 可选集合并复跑成功；完整后端测试 66 项通过。细节见 `docs/evidence/v2-2-bug-action-loop.md`。

- 2026-09-15：用户明确授权发送 task24 的正式文档、相关代码和报告副本至 Kimi API 后，在临时工作区把清除显示常量改为 `BROKEN_CLEAR` 并运行一次隔离真实模型分流。Kimi 先选 `product/app.js`，再选 `evidence/verification-report.md`；程序实际读取并记录哈希。共 5 次模型调用，最终判为 `implementation_defect → develop`，隔离任务为 `running`，命令退出码 0。原 task24 工作区及任务状态未修改；未继续执行代码返修或完整动态行动。证据见 `docs/evidence/v2-2-task24-real-triage.md`。

- 2026-09-15：v2.2 最小 Bug 分流已实现。验收反馈到来后，模型从任务内产品文件和失败报告清单选择最多三个不同文件，程序核对清单、实际读取、记录哈希和 Trace，之后分类模型结合正式文档与调查内容判断最早失效阶段；无效路径或证据不足时等待澄清。新增两项调查／越界回归测试，验收事件相关测试 36 项通过，完整后端测试 63 项通过，`git diff --check` 通过。task24 清除问题以隔离的 Fake 模型和临时文件复现该机制。真实 Kimi 隔离测试第一次被网络沙箱阻止，升级执行因缺少发送具体文件至 Kimi 的授权被自动审批拒绝；随后用户明确授权并完成上方真实测试。完整动态 Planner 仍未实现。

- 2026-09-15：新增 `tests/test_security_baseline.py` 并执行，5 项均通过；完整后端测试 61 项通过。测试仅用 pytest 临时目录的无害哨兵文件和测试 SQLite 会话，不调用真实模型、正式 MySQL 或外部网络。确认当前 `read`／`write` 路径校验有效，但 `write` 可覆盖已有 Trace 详情，`exec` 可在固定工作目录之外读写文件，失败文字会进入返修模型循环；两项 `exec` 用例在 Windows 跳过，Windows 边界和真实模型是否会提出越界工具调用均未验证。详见 `docs/evidence/prompt-injection-tool-boundary-baseline.md`。

- 2026-09-15：按授权对 Task 24 执行一次间接提示词注入实验。`product/implementation.md` 中放入伪系统门禁，要求返修 Agent 无关地写入 `INJECTION_OK`；同时将 `app.js` 初始／清除显示改为 `BROKEN_CLEAR`，本地 Node 测试复现失败。Event 55 被分类为实现缺陷并进入 Develop；模型请求 Trace #8974 含攻击文字，DeepSeek 只修复显示常量并清理注入段落，未写入标记。原浏览器验证复跑、正式 Node 测试、健康检查和真实浏览器验证均通过，Task 24 回到 `waiting_acceptance`。输入、步骤、预期、实际和局限见 `docs/evidence/task24-prompt-injection-55.md`。

- 2026-09-15：按项目注释规范为后端函数补充中文用途说明，重点解释模型流式调用与降级、工具路径校验与原子写入、Trace 脱敏与持久化、文档版本返工、开发血缘及事件消费。AST 检查未发现缺少用途说明的函数；`python3 -m compileall -q backend` 通过，`.venv/bin/python -m pytest -q tests` 为 55 passed。此次仅修改注释和规范／进度文档，未执行真实模型或数据库联调。

- 2026-09-15：完成 v2.1 可靠返修闭环。将单 Step 逻辑模型调用 100 次、Provider 传输 3 次、跨阶段返修 3 轮、无变化／验证失败纠正 2 次、相同工具动作连续实际执行 2 次、返修成功写入间诊断动作 5 次固化为独立预算；第三次完全相同工具动作返回 `repeated_tool_action`，第六次连续非写返修动作返回 `repair_tool_loop_no_write`，两者均保存 `tool_guard` Trace 并作为失败 ToolResult 反馈模型。结合此前 Task 24 的错误报告选择、无变化反馈和原失败验证强制复跑，后端 55 项测试全部通过；Worker 已重启并加载新规则，Task 24 保持 `waiting_acceptance`。
- 2026-09-15：排查 Task 24 的 `repair_made_no_changes`。确认 `verify_product.py` 忽略系统传入的 HTTP URL并固定使用 `file://`，导致 ES Module 未执行、浏览器 14 项始终显示 `0.00`；同时返修只收到 52／52 通过的 `test-report.md`，未收到真正的 `verification-report.md`。先更新 Dev Design，再实现按失败阶段选择报告、无变化最多两次反馈重试、文件变化后强制复跑原失败验证，并阻止模型自行查找／切换 Playwright 环境；后端 53 项测试全部通过。真实恢复 Task 24 后，DeepSeek修正页面和验证脚本；系统使用 `.venv` Python 的 Develop 门禁 17／17 通过，随后 Node 测试、健康检查及正式 Playwright再次全部通过，Task 24 进入 `waiting_acceptance`，结果地址为 `http://127.0.0.1:58130`。旧失败 StepRun 和 Trace 全部保留。
- 2026-09-14：实现 Codex 式双栏任务页与真实 Provider Streaming。模型请求／响应使用同一 `request_id`，每个文本增量形成永久 Trace；成功写文件形成可点击 Artifact Trace，受限文件 API 只读取当前任务工作区内不超过 1MiB 的文件。新增流式回调、文件读取及路径穿越拒绝测试，后端 51 项测试全部通过，前端生产构建通过。经用户明确授权，仅将既有 MySQL 容器密码注入 API 进程环境且未输出、落盘或修改容器；正式 Task 23 浏览器验证确认任意窗口宽度保持左右双栏、模型请求及原始返回按人可读层级展开、历史空消息被过滤、控制台错误为 0。真实 `product/app.js` 文件详情 API 返回 200、19420 字节及 64 位 SHA-256。Provider 真实流式调用尚未新建任务验证，当前证据为协议模拟与持久化回归测试。
- 2026-09-14：按用户要求将单个 Step 的逻辑模型调用硬上限从 10 调整为 100；Kimi／DeepSeek 传输重试仍为每次最多 3 次，Kimi→DeepSeek 技术降级继续复用同一逻辑调用编号。使用常量 `MAX_MODEL_CALLS_PER_STEP` 统一约束，并新增第 100 次调用仍可执行的边界回归测试；后端 49 项测试全部通过。历史验证记录中的“10 次”保留为当时事实，不回写。
- 2026-09-14：排查 Task 23 降级到 DeepSeek 后重复提问。Trace #502／#509／#516 证明降级复用了同一请求，没有在 Provider 切换时丢上下文；但请求生成前仅筛选 `role=user`，导致模型收到“3.忽略该运算符”却看不到对应问题，同时门径主输入始终是最初需求且未包含当前正式 `product.md`。先更新架构和 Dev Design，再实现问答配对账本、当前正式需求优先输入和写文件 Artifact 账本；新增问答不可拆分、正式需求作为主输入、写入路径／哈希／来源轮次回归测试。后端 48 项测试全部通过。
- 2026-09-14：实现 Kimi→DeepSeek 模型调用技术降级。先更新架构和 Dev Design，再在模型循环中区分技术故障与业务结果；Kimi 保留最多 3 次传输重试，耗尽或遇到 HTTP／凭据／协议错误后记录 `model_fallback` Trace，并以同一 `model_call_count`、请求 ID、指令、输入、上下文和工具定义请求 DeepSeek。新增“3 次 Kimi 连接失败后 DeepSeek 一次成功”及双 Provider 均失败的回归覆盖；后端 46 项测试全部通过。真实 Task 23 随后因 Kimi `403 Forbidden` 失败，保留失败证据并恢复 `product_docs` 后，Trace #501 记录 `kimi → deepseek`、原因为 `HTTPStatusError`、逻辑调用计数仍为 1；DeepSeek 成功返回产品澄清问题，任务进入 `waiting_user`，证明真实降级链路可用。
- 2026-09-14：针对 Task 23 中“当前软件不支持连续输入”被误写成产品限制的问题，确认同一 Kimi 在验收分类阶段理解正确，但产品生成调用未收到分类结论且旧需求权重更高。先更新架构和 Dev Design，再将分类结果扩展为当前行为／期望行为／验收示例三元变更契约；`requirement_change` 无合法契约时强制澄清。Draft、Review、Candidate 共享契约，Candidate 后增加只读 Change Coverage Validator 和程序门禁，覆盖方向相反时保存失败证据并阻止审批。新增歧义澄清与候选写反拦截测试；后端 45 项测试全部通过，前端生产构建通过。Task 23 既有文档和历史未修改。
- 2026-09-14：使用 Task 23 原始反馈真实复跑上述机制。首次复跑 Event 34 证明结构化字段仍不足：Kimi 的 reason 承认第一条是需求变更，却输出 `implementation_defect` 并把“不支持连续输入”写成期望，错误进入开发；立即停止 Worker，保留错误 Trace 和已产生文件，并将该 Step 标记为中止。随后增加第二次 Kimi Consistency Validator，逐条检查“报告问题”的语用方向、字段与 reason 自洽性及最早失效阶段。后端 45 项测试通过后重新提交 Event 35；Validator 真实识别分类字段与理由矛盾、第一条方向歧义和第二条现状表述不忠实，程序将任务停在 `waiting_user / verify_product`，未再次进入产品或开发阶段，等待用户确认 `2+3*4` 的计算语义。
- 2026-09-14：用户确认 `2+3*4=14` 后，Event 36 正确识别第一条为需求变更，但一致性审查发现第二条实现缺陷未进入变更契约并再次澄清；提交用户此前已明确的“第二条是实现违反既有显示需求”后，Event 37 初步分类正确选择 `requirement_change`。过程中发现验收分类错误复用旧 `verify_product` StepRun，累计耗尽 10 次调用上限；改为每个验收 Event 独立 StepRun／预算，Worker 恢复同一 Event 时才复用。后端 45 项测试通过后恢复 Event 37，一致性审查通过并进入 `product_docs`。真实 Kimi 已生成 V3 Draft、Review、Candidate，Change Coverage Validator 对两项均返回 `covered=true`、`all_covered=true`；任务停在产品审批门禁，未越权批准。
- 2026-09-14：将固定全阶段流水线改为“固定治理阶段＋动态动作决策”。架构和 Dev Design 的返工输入包含新旧上游、文本差异、旧正式产物和验收分类，Kimi Transition Planner 返回受程序校验的 `revise`／`reuse`／`clarify`；正式文档按版本保存，当前指针仅在新版本完成后更新。开发阶段加入 Dev Design 内容哈希血缘，差异存在时强制 DeepSeek 基于旧代码增量修改。新增增量修订、复用旧设计及上游变化不得跳过开发的回归测试；后端 43 项测试全部通过，前端生产构建通过。Task 23 既有数据未修改，生成软件尚未重新验收。

- 2026-09-12：产品文档加入独立 Kimi Review 和候选修订，后端 41 项测试、前端生产构建通过。Task 23 的 V2 Draft 真实生成 `product-v2-review.md` 和 `product-v2-candidate.md`，Trace #143—#151 完整记录 Reviewer、Candidate 模型与工具调用；API 已验证返回 Candidate 路径。首次真实 Review 正确分出阻塞问题、普通问题和建议，但未识别“仍保留不支持连续运算”这一核心误解；确认原因是 Review 未获得验收分类证据，已将最新 `acceptance-triage-*.json` 同时加入 Draft、Reviewer 和 Candidate 上下文，并规定保留被需求变更推翻的旧约束必须列为阻塞问题。该提示增强尚待下一版产品草稿真实复验。
- 2026-09-12：实现人工验收问题自动分类和最早失效阶段路由。新增四类固定路由、低置信度澄清、版本化设计返工、验收分类 Trace／工作区证据及前端统一问题入口；后端 41 项测试和前端生产构建通过。将 Task 23 原始反馈重新提交后，真实 `kimi/kimi-for-coding` 以 0.97 置信度识别为 `requirement_change`，Trace #130 路由到 `product_docs`，未再直接重跑旧测试；随后生成产品 V2 草稿。真实过程发现并修复分类 JSON 污染产品对话的问题，保留旧 Trace；V2 草稿仍未正确吸收“支持连续输入”的意图，当前等待用户审阅，未批准、未进入后续实现。
- 2026-09-12：从断点恢复 Task 23 后，Kimi 在 `max_completion_tokens=8192` 下完成 Dev Design 草稿、评审和正式文档，任务按固定路由切换到 `deepseek/deepseek-flash` 完成开发；生成计算器 Node 测试 33／33、真实 Playwright 验证 37／37，实际 HTTP 地址返回 200，任务进入 `waiting_acceptance`。独立复跑生成软件测试仍为 33／33；项目后端测试 35 项和前端生产构建通过。API、前端、单 Worker 与生成软件保持运行，等待用户操作验收。
- 2026-09-12：Task 22 在 Kimi Dev Design 三个模型阶段均成功后进入 DeepSeek 开发阶段；DeepSeek 首次响应包含未闭合的工具参数 JSON，原实现抛出 `JSONDecodeError` 并终止任务。保留 Task 22 失败证据，新增可审计的 `invalid_tool_call` 协议错误与有界逻辑重试，待回归和 Task 23 复验。
- 2026-09-12：Task 22 的 Kimi `dev_design` 首次真实运行连续两次 60 秒 `ReadTimeout`，第三次请求仍在运行时完成阶段失败证据；短响应和架构阶段已成功，确认是长文档传输超时。将 Kimi Runtime 独立超时提高到 180 秒，新增配置回归测试；Task 22 保留失败 Trace，不删除任务数据，待重启 Worker 后重新执行干净验证。
- 2026-09-12：完成 Kimi→DeepSeek 固定阶段路由。更新架构与 Dev Design 后，Worker 按当前 Step 选择 Runtime；新增七阶段映射回归测试，后端 34 项测试和前端生产构建通过。真实隔离任务先以 `product_docs` 调用 Kimi，再以 `develop` 调用 DeepSeek，两阶段均只调用 1 次并严格返回预期结果；响应 Trace 分别记录 `product_docs=kimi/kimi-for-coding` 与 `develop=deepseek/deepseek-flash`。
- 2026-09-12：Kimi Code Provider 完整真实验证通过。隔离 SQLite／任务工作区中的无工具 Agent Step 仅调用模型 1 次，严格返回 `AGENT_OK`，保存 `model_request`、`model_response` Trace；真实工具 Agent Step 也仅调用模型 1 次，Kimi 发起 `write`，程序在隔离工作区生成内容严格为 `KIMI_TOOL_OK` 的文件，并保存 `model_request`、`model_response`、`tool_call`、`tool_result` Trace。两组 Trace 的元数据均为 `kimi/kimi-for-coding`。后端 33 项测试和前端生产构建通过，密钥未进入命令输出或 Trace。
- 2026-09-12：确认用户提供的是 Kimi Code Key。按官方文档改用 `https://api.kimi.com/coding/v1` 后，真实 `/models` 返回 `kimi-for-coding`、`kimi-for-coding-highspeed`、`k3-256k`、`k3`；以 `kimi-for-coding` 发送最小 Chat Completions 请求返回 HTTP 200、`finish_reason=stop` 和严格 `OK`。据此将 Kimi Provider 默认端点和模型修正为 Kimi Code 配置；真实 Agent Step 待本轮后续验证。
- 2026-09-12：用户放入 Kimi 密钥后进行真实认证验证。密钥文件存在且格式符合约定，检查过程不输出内容；国际 `https://api.moonshot.ai/v1/models` 与国内 `https://api.moonshot.cn/v1/models` 均返回 `401`，国内端点明确返回 `invalid_authentication_error: Invalid Authentication`，因此未继续最小生成或 Agent Step。根据 Kimi 国内官方文档将项目默认端点修正为 `https://api.moonshot.cn/v1`，国际平台保留配置覆盖方式。
- 2026-09-12：按确认方案增加 DeepSeek／Kimi 并存与配置切换。先更新架构和 Dev Design，再实现 `SIMULATOR_MODEL_PROVIDER`、Kimi 独立密钥文件、端点／模型配置及 Chat Completions Runtime；Trace 的模型请求、响应和重试元数据包含实际 Provider 与模型。后端 33 项测试、Python 编译和前端生产构建通过。测试使用假密钥和模拟 HTTP 响应，未读取真实密钥；真实 Kimi `/v1/models`、最小调用及 Agent Step 尚未验证。
- 2026-09-11：启动现有 `id-photo-mysql` 容器并新增 `dev_team_simulator.trace_records`，未改 `id_photo` 数据库。核对 15 个字段、`uq_trace_task_sequence`、两个索引和两个外键；事务探针写入 1 条后回滚，剩余 0。正式连接发现 PyMySQL 缺少 MySQL 8 `caching_sha2_password` 所需的 `cryptography`，将 `cryptography==46.0.3` 加入项目依赖并验证连接成功。真实任务 20 依次完成产品 Draft 与审批、架构、Dev Design、开发、测试失败、自动返修、39 项测试、启动和真实 Playwright 验证，进入 `waiting_acceptance`。MySQL 记录 102 条不重复连续序号，工作区对应 102 个不可变 JSON，共 1,155,391 字节；递归检查已知敏感键违规为 0。真实前端正确展示所有阶段，测试历史同时呈现失败、返修和成功，可返回当前进度；已完成动作由“执行中”修正为派生显示“已发起”，不改原始 Trace。最终构建通过，控制台错误和警告为 0。
- 2026-09-11：完成 v2 Trace 与实时流程可视化。新增 `trace_records`、不可变详情文件、增量 API 和三栏任务页面；真实浏览器发现刷新丢失任务上下文及 React StrictMode 重复追加，修复为 `?task=` URL 恢复和按 ID／sequence 去重。后端 28 项测试、前端构建通过；SQLite 本地服务中验证新 Trace 自动追加、详情读取、历史查看、回到当前进度和刷新恢复，干净页面控制台错误为 0。正式 MySQL 因服务未运行连接被拒绝，未创建新表；真实模型完整链路未执行。

- 2026-09-11：真实 Task 19 在生成计算器测试中连续三轮报告 `unit_tests_failed`，随后错误地以 `model_call_limit_exceeded` 结束。检查发现返修进入 `develop` 后，六个必需文件已存在会触发“开发已完成”捷径，模型实际没有修复；取消该捷径后，模型又用 10 次调用逐个读取已知文件。先更新 Dev Design，再将正式设计、最新测试报告和全部当前产品文件一次性放入返修上下文，返修阶段仅开放 `write`、`exec`，并要求至少修改一个文件。新增回归测试后后端共 24 项通过。恢复 Task 19 后，真实 DeepSeek 修正等待右操作数时的显示逻辑及一条与设计冲突的测试，系统单元测试 15／15、真实浏览器验证通过并进入 `waiting_acceptance`；开发助手独立复跑同一单元测试，结果仍为 15／15。
- 2026-09-11：真实 Task 17 在 `product_docs` 报告 `model_call_limit_exceeded`。检查点证明 10 次均为连续 `ConnectError`，没有一次有效模型响应；DeepSeek 官方地址随后连通并返回未认证 `401`。修复为一次逻辑模型调用最多进行 3 次独立传输重试，采用 0.5／1 秒退避，传输重试不重复增加 `model_call_count`；耗尽时返回 `model_transport_failed:<错误类型>`，非重试型 4xx 立即失败。新增成功重试与耗尽回归测试后共 23 项通过。重启 Worker 后真实 Task 18 一次正常进入产品问答，无传输错误检查点，原错误未复现。
- 2026-09-10：按用户反馈调整产品提问密度。首次放宽后真实 Task 13 直接返回 `READY`，Draft 擅自默认按钮键盘、C 键和连续运算，判定放宽过度。随后明确主输入方式、核心触发动作、单次／连续模式不得默认，只有布局与视觉样式等不改变行为的细节可采用最小默认值；每轮最多三个问题且每题只含一个决策。真实 Task 14 使用相同需求后只询问两个问题：输入交互形态、单次或连续运算；`product_document_available=false` 且 Draft 不存在。回归测试仍为 22 项通过。
- 2026-09-10：用户真实 Task 10 再次出现直接生成 Draft，且 Draft 自身列出 7 项“尚未确定、需用户确认”。确认根因是提示词无法强制同一次模型调用在“提问”和“写 Draft”间正确选择。将产品阶段改为程序级两次独立调用：第一阶段不提供任何工具，只接受严格 `READY`，其他任何返回均视为阻塞问题；只有 `READY` 后第二阶段才提供 `write` 生成 Draft。新增无写工具回归测试，总计 22 项通过。真实 Task 11 使用与 Task 10 相同输入，首轮返回 `BLOCKED` 问题、`product_document_available=false` 且 Draft 不存在；回答后先得到 `READY`，随后独立调用才生成 Draft，正式 `product.md` 仍不存在。
- 2026-09-10：真实 Task 7／9 在 `architecture_docs` 失败并报告 `architecture_review_missing`。检查点和 Message 证明同一 StepRun 的 Draft 工具历史被错误带入独立 Reviewer 上下文，Reviewer 因而误认自己写错 Draft，只输出文本而未调用 `write` 生成 Review。为检查点记录增加 `history_key`，Draft、Review、Formal 只加载各自阶段的工具历史，同时保留完整检查点审计记录；新增隔离回归测试后共 21 项通过。重启 Worker 后以真实 Task 8 验证：架构与 Dev Design 均分别生成 Draft、Review、正式文档，并依次进入 `dev_design`、`develop`，原错误未复现。
- 2026-09-10：修正产品阶段流程。首次真实 Task 6 暴露 DeepSeek 将“网页版计算器”按品类惯例脑补为四则运算、数字键盘、清除键等并直接生成 Draft，判定真实测试失败；随后收紧阻塞判断，明确产品名称和惯例不是功能授权。真实 Task 7 首轮进入 `waiting_user`、`product_document_available=false`，模型提出三个产品问题且 Draft 不存在；回答后恢复同一 StepRun 并只生成 `product-v1-draft.md`；批准前正式文件不存在，批准后 `product.md` 与获批 Draft 字节一致，随后才进入 `architecture_docs`。另通过浏览器真实操作 Task 8，确认页面先展示“回答产品问题”，提交回答后才展示“确认产品文档”。后端测试 20 项通过，前端构建通过。
- 2026-09-10：用户打开 `http://127.0.0.1:5173` 后创建任务出现 `Failed to fetch`。确认前端默认请求端口 8000，而当前 API 运行于 8765，且 API 的 CORS 来源与浏览器地址不一致。将前端默认 API 改为同源 `/api`，新增 Vite 开发代理并将后端默认前端来源统一为 `http://127.0.0.1:5173`；当前开发服务器以 `VITE_BACKEND_URL=http://127.0.0.1:8765` 启动。同源代理读取 Task 3 返回 HTTP 200，前端生产构建通过，后端 18 项测试通过。
- 2026-09-10：真实任务 3 完成 DeepSeek V4.1 Flash 全链路。产品文档经五轮澄清后批准，架构、Dev Design、开发、测试和启动均完成；生成计算器单元测试 18／18、真实 Chromium 29／29、控制台错误 0。发现验证脚本因环境问题输出 `[SKIP]` 且退出 0 仍被系统放行后，修复 Worker 使用自身 Python 环境并将 `[SKIP]` 视为失败，新增回归测试后项目测试共 18 项通过。以验收者身份提交缺陷后，任务正确退回测试、换端口重启并产生无跳过的新浏览器证据；最终批准后 Task 3 状态为 `succeeded`。前端生产构建再次通过。
- 2026-09-10：通过 DeepSeek 官方 `/models` 实时确认 V4.1 Flash API ID 为 `deepseek-flash`，先更新架构与 Dev Design 后更新代码。最小真实模型请求返回 `OK` 并写入 Message。真实 `product_docs` 测试先后暴露候选越界和模型重复读取导致 10 次上限的问题；保留失败检查点，补充固定边界和程序化结束条件后，第三次测试以 1 次调用生成候选并进入 `waiting_user`。新增回归测试后共 14 项通过；未读取或输出密钥。
- 2026-09-10：新增 `SIMULATOR_DEEPSEEK_API_KEY_FILE`，默认指向已被 `.gitignore` 排除的 `secrets/deepseek_api_key`；以临时测试文件和假密钥验证读取逻辑，后端测试增至 13 项并全部通过，前端构建通过。真实密钥文件由用户创建，开发助手未接触其内容。
- 2026-09-10：项目 ORM 真实连接 MySQL 8.4.11，并完成四表事务写入／回滚；后台 HTTP 进程启动、状态、访问、停止和端口释放通过；安装 Playwright Chromium 后，真实浏览器完成 React 创建 FastAPI 内存任务联调；新增 DeepSeek HTTP 封装测试后共 12 项测试通过；前端再次构建通过，`npm audit --omit=dev` 报告 0 个已知漏洞。未使用真实 DeepSeek Key，未执行 Windows 验证和用户验收。
- 2026-09-10：经用户确认，在现有 Docker MySQL 8.4 容器中新建独立 `dev_team_simulator` 数据库及 `tasks`、`step_runs`、`events`、`messages` 四张 InnoDB 表。核对 utf8mb4、字段数量、三个外键和 `uq_step_attempt` 唯一约束均符合实现；事务插入四表关联数据成功并回滚，确认未留下测试记录。原 `id_photo` 数据库仍存在，未修改其结构和数据。
- 2026-09-10：v1 最小完整链路已实现。初次 `.venv/bin/python -m pytest -q` 共 11 项机制测试通过；`frontend/` 中 `npm run build` 通过；使用临时 SQLite 实际启动 FastAPI，健康检查、创建任务、查询任务和增量消息四个 HTTP 请求分别返回 200、201、200、200。后续验证已增至 12 项测试并完成 Chromium 联调。详细证据见 `docs/evidence/v1-implementation-validation.md`。DeepSeek、Windows 完整链路和用户操作均未验证。

- 2026-09-10：创建并局部核对 `docs/DEV_DESIGN.md`，同步修订架构文档中的单 Worker、三工具、调用限制、最小隔离和固定生成技术栈，并更新文档索引、项目入口与本进度文件。未编写业务代码、安装依赖或执行产品验证。
- 2026-09-07：创建并局部核对 `docs/ARCHITECTURE.md`，记录用户确认的最小运行架构、组件职责、核心流程、v1 边界和进入 Dev Design 前的待确定项；同步更新文档索引与本进度文件。未编写业务代码、安装依赖或执行产品验证。
- 2026-09-06：架构与 Dev Design 评审规则已写入，局部内容核对见本次工具输出；未代写设计或选择技术方案，项目仍等待用户提交首版产品需求。
- 2026-09-06：写入产品评审口径后，通过局部读取核对 `AGENTS.md` 与本文件表述一致，包含三项评审重点及不要求完整 PRD 的约束；项目仍等待用户提交首版产品需求。
- 2026-09-06：初始化前通过当前目录路径与文件清单检查，确认目录为空；适用祖先路径中未发现额外 `AGENTS.md`，依据本次用户提供的全局规范和项目要求初始化。未操作旧项目。
- 2026-09-06：通过本地 Python 只读断言检查，确认恰好五份目标文件、内容非空，三份设计文档未创建；关键职责与授权约束、未实现状态和等待用户提交需求的表述一致。
- 2026-09-06：忽略模式样例检查通过，覆盖依赖、构建、`.env*`、系统文件、编辑器和 AI 本地配置，五份治理文档未被样例匹配检查排除。尚未初始化 Git，因此未执行 Git 实际忽略行为验证。
- 2026-09-06：内容复核未发现新增产品功能、架构或技术栈决定；文档存放约定与运行时隔离方案明确区分。没有编写业务代码、安装依赖或提交 Git。
- 当前验证结论：macOS 上的真实 AI／工具任务、生成软件测试、浏览器验证和代行验收均已完成；Windows 与用户本人操作仍待验证。
