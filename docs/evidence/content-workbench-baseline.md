# 多模块内容工具 DeepSeek 基准测试

日期：2026-09-17。状态：自动基准失败；已有生成产物的独立诊断验收通过。用户本人未验收。

## 用户确认的测试范围

- 需求来自 `docs/CONTENT_WORKBENCH_REQUIREMENTS_V1_AI_DRAFT.md`。
- 临时 SQLite、独立任务工作区；不修改正式 MySQL、服务配置或模拟器默认预算。
- 全阶段 DeepSeek，单 Step 逻辑上限 200；整个测试实际 HTTP 模型请求上限 200，包含传输重试。
- 原生 JavaScript 多模块，localStorage 持久化，不新增产品依赖。
- 仅在测试进程适配 Worker 的单模块提示、必需文件和 Node 测试入口；其他阶段、工具、审批事件、失败返修使用现有实现。保存适配后的函数源码供复核。
- 自动生成架构和 Dev Design；如出现未授权的业务决策澄清，暂停，不替用户猜测。
- 核对产品候选后由测试控制提交审批；完成生成软件自身验证后，独立浏览器按原始需求操作，测试验收不等于用户本人验收。
- 实际调用、Token、失败、人工干预、模块边界及持久化结果如实记录，不将适配后的能力称为正式 Worker 已支持。

## 实际运行

1. 沙箱首轮三次连接失败，无模型响应。保留在 `/private/tmp/content-workbench-baseline-20260917`。获得联网执行权限后从新隔离任务开始，预算从已消耗的三次继续计数。
2. 全 DeepSeek 产品门径 READY，生成 Draft、Review 和 Candidate。候选保留四模块及主要验收条件，但仍将部分口径转交 Dev Design，文档质量不视为无缺陷。测试控制核对后提交正式 document_approval 事件；这是测试审批，非用户本人审批。
3. 架构 Planner 跳过独立架构，Dev Design Planner 要求设计文档，随后生成、评审、正式化。Dev Design 承载模块边界、接口、数据、状态、引用完整性、失败处理及决策记录。
4. 开发生成四个业务模块、存储层、共享状态、工具函数、界面、Node 测试和浏览器脚本。默认 Python 缺少 Playwright，模型自行搜索本机环境并找到项目虚拟环境；出现任务工作区外的只读环境探查及外部临时诊断文件操作，不能称为严格沙箱隔离。未发现修改正式项目代码或配置的工具操作。
5. 开发自行发现并修正入口路径 404、App Shell 导入任务模块未导出 PRIORITIES 两处真实集成问题。Node 20 项通过，开发自身浏览器操作通过。
6. 模型结束开发后，原自动 Task 为 failed，原因 `implementation_files_missing:app.js`。实际入口为 `js/app.js`；适配器沿用了根目录 app.js 的固定必需文件要求，模型也未满足该提示。此处是设计生成路径与固定入口校验冲突，不能据此称软件不可用，也不能把失败 Task 改写为成功。
7. 保留原失败任务，新建独立诊断任务，复制已有 docs 与 product，不人工改生成代码，直接执行真实 Worker test、start、verify；Node 20 项、生成浏览器脚本均通过，进入 waiting_acceptance。没有新增模型调用。
8. 独立 Chromium 完成 13 组检查（每组含多项断言），覆盖三类空标题后恢复、标题与笔记检索、多对多关联、转任务去重、标题独立、草稿及状态、工作台、删除限制、取消删除、素材删除级联、刷新、同端口服务实际重启后保留、发布移除待办逾期；页面脚本错误为零。采用相同浏览器上下文和相同 origin；不声称更换端口后 localStorage 仍可共享。
9. 测试控制通过 acceptance_result 事件批准诊断任务，诊断 Task succeeded；原自动 Task failed 保持不变。

## 模块与能力结论

素材 MaterialModule、选题 TopicModule、任务 TaskModule、工作台 DashboardModule 有独立文件和公共 API。素材删除通过选题公开接口解除关联；任务通过选题接口查询来源；工作台通过任务公开接口只读聚合，无业务写方法。共享 StoreRoot 用 localStorage 保存。该样本体现了真实多模块协作，不等于正式 Worker 已具备通用多模块流水线。

生成浏览器脚本只验证刷新，真实服务重启由独立验收补齐。未验证后续跨模块需求变更、Windows、存储故障恢复或用户本人操作。没有全程无人工干预成功证据：存在测试入口适配、测试审批和自动失败后的诊断验证；未人工补生成代码。

## 预算与用量

- 实际 HTTP 模型请求合计 66 次：首轮失败三次，联网任务 63 次；请求 Trace 全部 deepseek，未调用 Kimi。
- 上限为整个测试 200 次实际 HTTP 请求，包含重试；单 Step 逻辑上限仅在测试进程设为 200。正式 Worker 的默认 100 不变。
- Provider 响应合计输入 3,564,354、输出 78,022、总计 3,642,376 Token。用量含缓存，不能直接当作计费金额。
- 首次输入 1,787 Token，末次输入 99,859 Token；最大请求 112 条 API messages。开发工具调用及完整结果持续累积，包含文件内容与重复验证输出，使后期输入显著增大。未做去重前后 A/B，不声称具体节省比例。

## 复核入口

- 基准脚本：`tests/content_workbench_baseline.py`；独立操作：`tests/content_workbench_acceptance.py`。均不由 pytest 自动收集，不触发普通回归付费调用。
- 原基准：`/private/tmp/content-workbench-baseline-20260917-network`；日志同名 `.log`。包含 test.db、adapter 函数源码、实际发送体、完整 Trace、summary.json 与生成软件。
- 诊断验证：`/private/tmp/content-workbench-diagnostic-20260917`。包含 test.db、生成软件副本、测试／验证报告、independent-acceptance.json、截图、重启服务记录和 final-status.json。
- 独立操作日志：`/private/tmp/content-workbench-independent-acceptance.log`。
- 本次预览：`http://127.0.0.1:54602`。独立验收后重启服务，最新 PID 在诊断目录 acceptance-server.json；原 summary 的 PID 属于已经停止的旧预览进程。
- 正式后端回归 91 项通过；手动脚本语法检查、git diff --check 通过。未修改正式服务源码，无需重启正式服务；无正式库 schema、数据或密钥变更。临时证据可能被系统清理。

## 2026-09-19：当前流程从零复跑

用户授权重新运行素材管理完整流程。本轮使用原始需求、当前未提交实现、空 SQLite 与空任务工作区；全阶段 DeepSeek。正式单 Step 逻辑上限保持 100，本轮实际 HTTP 上限 300。没有修改正式数据库、服务实现或生成代码。

测试在 `architecture_docs` 失败，错误为 `unit_plan_validation_failed`；未进入 Dev Design、开发、测试、启动或浏览器验证。产品候选额外提出优先级与删除确认问题，测试控制采用最小默认值：优先级为高／中／低三档，只有删除已关联素材要求影响确认。回答写入后，当前设计门径错误复用了旧 `clarify` 决定；测试控制保留旧证据并使缓存决定失效。恢复脚本还曾错误清空 checkpoint_path，造成一次 `NoneType` 失败；恢复原路径后继续。上述均属测试控制介入，本轮不能称完全自主运行。

架构 Draft、Review 和正式文档生成后，开发单元计划连续三次被程序以 `unit_plan_module_feature_overlap` 拒绝：第一次 app 同时有 module 与 feature；第二次 tasks、app 重叠；第三次 materials、topics、tasks、app 重叠。程序规则要求一个模块若存在 module 单元，该模块只能有这一个单元。规划器收到同一错误后仍未收敛，三次机会耗尽，最终失败。没有人工修改计划继续运行。

本轮累计 13 次实际 HTTP，输入 89,425、输出 34,395、总计 123,820 Token。产品阶段 4 次／18,486 Token；架构阶段 9 次／105,334 Token，其中三次计划生成共 50,909 Token。一次架构 Draft 调用因测试恢复脚本错误未形成产物，随后重跑；其 6,580 Token 仍计入本轮实际成本。证据目录：`/private/tmp/content-workbench-rerun-20260919`，含 test.db、sent 请求、完整 Trace、产物和 summary.json。临时证据可能被系统清理。

## 2026-09-19：修复后全链路复跑结果

用户授权修复后使用 DeepSeek 从空工作区运行素材管理完整流程，正式单 Step 逻辑上限 100，整次实际 HTTP 上限 300。测试控制采用已确认的最小业务默认值，并在核对产品候选后提交正式审批事件；未人工修改生成文档或产品代码。任务最终在 `develop` 失败，未进入全量测试、启动、浏览器验证或人工验收，不能称为全链路成功。

本轮依次暴露并修复：多单元模块 kind 可确定归一、产品审批后澄清未传播、Reviewer 残缺 JSON 直接终止、同模块公共操作重复所有权、内部契约冲突错误询问用户、Dev Design 工具参数截断后原样重试、真实自测刚通过却在提交前触发无进展失败。开发计划由 13 单元修正为 11 单元，Dev Design 最终完成并进入开发；`domain-rules`、`storage-persistence`、`materials-crud`、`materials-search` 四个单元通过真实 Node 测试并提交。`topics-crud` 因测试间共享 `hasTask` 模块状态，116 项中 115 项通过、1 项失败；Agent 多轮修改测试仍未收敛，第二次有界开发恢复最终遇到 DeepSeek HTTP 失败，任务终止。

实际 HTTP 共 225 次，其中保存了 222 个完整模型响应、43 个带用量或部分内容的中断记录。Provider 用量合计输入 9,348,854、输出 990,078、总计 10,338,932 Token：产品阶段 19,420，架构阶段 65,686，Dev Design 7,748,016，开发阶段 2,505,810。Dev Design 占总 Token 74.9%，其中 37 个完整响应达到约 8192 completion Token；开发阶段有 91 个完整响应，其中 71 个输出不足 1000 Token，但反复携带约 2 万至 3.4 万输入 Token，造成大量上下文成本。该统计包含缓存 Token，不等同计费金额。

直接成本原因有三项：开发计划拆得过细，逐单元 Author／Reviewer 成对调用；Dev Design 工具 JSON 截断后缺少纠错反馈，曾连续原样重试；开发工具历史和失败输出持续进入后续请求，使短工具决策仍携带大上下文。完成优先修复已经让流程从原来的架构计划失败推进到开发，但降低 Token 的目标未达成。本轮证据位于 `/private/tmp/content-workbench-fixed-fullflow-20260919`，包含 SQLite、225 份发送请求、完整 Trace、各版计划／设计、生成中的产品文件和 `summary.json`；临时目录可能被系统清理。

## 2026-09-19：提示词 v2 数据所有权拆分评测

使用相同素材管理需求和 DeepSeek，从空 SQLite／工作区运行；单 Step 100、整轮实际 HTTP 上限 300。测试控制只审批产品候选，没有人工修改生成文档或代码。Trace 证明 `unit-planner`、`design-author`、`design-reviewer` 使用 v2 及登记哈希，其余调用版本见 `summary.json`。

v2 计划生成 9 个单元，少于 v1 的 11 个：shared、storage、materials、topics、tasks、dashboard、linkage 各一个 module，app 与 verification 两个 feature。数据所有权拆分减少了 materials／topics／tasks 的 CRUD 与搜索等功能碎片，但仍把验证脚本和说明文档拆成独立 verification 单元，未完全遵守「测试和文档不独立拆分」。

流程在 `dev_design` 失败，未进入开发。shared、storage、materials、topics 设计正式化；`tasks_unit` 连续生成五份候选，Reviewer 始终判定其来源上下文验收需要读取 topics／materials，而计划只声明依赖 shared／storage。Author 在直接依赖、注入读取、委托 linkage 等方案间变化，却没有得到同时满足计划依赖与验收的设计，第五次仍为 revise，最终 `unit_design_review_failed`。这是计划把跨模块验收留给 tasks、却未给出合法依赖出口造成的边界矛盾，不是用户业务信息缺失。

本轮 34 次实际 HTTP，输入 302,129、输出 45,697、总计 347,826 Token。产品 18,550，架构 61,957，Dev Design 267,319。单元数下降属局部改善；完成阶段从 v1 的 develop 回退到 dev_design，因此低于 10,338,932 Token 是提前失败，不认定为成本优化。v2 评测标记失败，激活版本恢复到 v1；v2 文件和全部证据保留。证据目录为 `/private/tmp/content-workbench-prompt-v2-20260919`。
