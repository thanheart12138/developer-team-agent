# 自媒体选题与发布计划平台全流程测试

## 授权与范围

用户2026-10-10授权新项目全流程测试，代理校验产品文档并提交，最多200次实际HTTP，包含失败和重试。使用DeepSeek thinking，正式repair-executor v5不变；不使用旧素材平台产物。

持久现场：`workspace/experiments/editorial-platform-fullflow-20261010/`。目录README先定义结构，requirements.md明确五模块、关联删除、重复创建、发布历史、逾期及状态回退规则。approval.json绑定需求哈希及外发范围。密钥仅认证，不保存认证头。

## 执行边界

隔离SQLite、空产品工作区，系统生成产品候选；开发助手根据原需求逐项校验，以正式document_approval事件推进，不手写候选冒充模型产出。产品阶段之后不直接改产物、卡片或失败状态；需要产品外决策则停下记录。

采用此前素材平台原生多模块／localStorage范围，实验进程所有阶段路由DeepSeek。首次开发正式入口尚未接入sandbox，本实验进程的for_workspace连接已有SandboxExecution；Node和生成Python仅在现有受控容器执行，网站由可信快照服务预览。该适配不修改正式源码，但意味着本轮并非未经适配的正式服务测试。浏览器契约为bundled Chromium且chromium_sandbox=True。

调用账本发送前原子预约、独占控制锁、恢复核对原SQLite／工作区／计数，不归零或借用旧额度；每次实际发送保存脱敏正文及供应商usage。单阶段仍保留正式100次逻辑调用上限，不因总额度200绕过。

## 当前状态

2026-10-10 收尾核对：实际183／200 HTTP，已知16,349,587 Token，第16次用量未知；任务 waiting_acceptance，五卡通过，系统 Node／生成浏览器验证及行为覆盖通过，独立用户操作验收未完成。下文“续跑启动，最终结果待验证”为当时记录，保留作为过程证据。逐请求离线分析见 `docs/evidence/editorial-platform-request-cost-analysis-20261010.md`；本次分析零新增模型调用，未实施优化。

用户追加授权阶段上限200并继续：首次运行在119／200 HTTP时触发开发阶段100逻辑调用上限，四卡passed，但整站尚未进入启动与验收。仅提高隔离控制器阶段参数，保留原失败StepRun，以新Run继承100逻辑调用及原检查点，复制SHA256一致；HTTP计数119不重置、总上限仍200。授权与恢复身份见stage-limit-extension.json及stage-limit-resume.json，正式Worker上限不变。续跑启动，最终结果待验证。

已核对已有sandbox门禁有效及Docker可用，控制脚本语法检查通过。产品阶段真实4HTTP、27,403Token、未知用量0；系统生成v1候选，代理按原需求核对11类覆盖，接受D1—D8最小口径，通过正式document_approval事件晋升product.md。审批身份、反馈和候选哈希在product-review.json保存，独立验收意图在acceptance-plan.json冻结。

后续自主流程运行中。实现、真实交互及总成本待验证，不标记完成或验收。Windows是系统原有运行边界，本轮macOS环境不能证明Windows兼容。

## 基础设施适配问题

初版实验接入未覆盖首次骨架暂存区的`node --check ../evidence/scaffold-stage-...`及其测试路径，已有sandbox以`sandbox_arbitrary_command_rejected`拒绝。此为开发助手测试适配遗漏，不能归因于模型能力；原系统重试及Token保留计数。

已在实验控制器补齐暂存快照映射，语法检查通过可信Node包装执行原`node --check`，不修改模型业务文件、不取消原检查。零HTTP预检实际语法exit0、原骨架124个TODO测试发现exit0（不代表124项业务通过）。生成代码仍只在容器执行。

第16次请求在途时SIGINT停止本人控制进程，保留16次计数和1次未知用量；原Task及架构StepRun仍running，未手改数据库状态，续跑复用原Run及检查点。adapter-recovery.json记录停止身份、状态、计数和边界。这是一次基础设施干预，本轮不得报告为严格无干预成功；产品代码及卡片没有开发助手修补。
