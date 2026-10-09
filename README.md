# AI Agent 工程实践项目

## 当前真实返修与面试入口

2026-10-10 用户委托验收与版本整理完成技术验证：本轮冻结素材平台原Node150项／实际Chromium60条通过，系统完整436项回归及前端构建通过，零模型调用。原生UI额外手工操作未完成，原因与证据边界已记录；系统仍待用户验收，未代发批准事件。已补忽略凭据副本目录，准备明确Git候选清单和源码／生成产品本地归档；不提交推送、不改正式任务。[验收与版本清单](docs/evidence/acceptance-version-20261010.md) 。

2026-10-09 无审查新流程真实单缺陷返修完成：任务详情关联素材缺失由DeepSeek thinking自主修复，13／20HTTP（执行13、审查0）、396,416Token、67.1秒，无人工改码／纠错。原断言独立Docker Node150／150及实际浏览器60条通过，网站60777首页GET200匹配。目标仍open、系统待用户验收；第10轮自测通过、第13轮提交，仍3轮收尾调查。旧七轮runtime与旧220保持，机制未在实验中改变、正式服务未操作。不追加调用；单缺陷与历史两缺陷范围不同，不换算成本降幅，成本问题未解决。证据见 [真实验证](docs/evidence/material-task-detail-no-review-deepseek-real-20261009.md) 。

2026-10-09 用户确认取消新 repair-v1 的独立模型目标／覆盖审查及审查预留。显式提交后执行全量测试、启动、实际浏览器验证，再等待用户验收；原始目标保持 open 到匹配提交／版本的用户批准，以 user_acceptance 记录关闭依据。总 HTTP 上限不变，旧尝试／原授权／审查记录／提示词绑定保留，不自动迁移或续跑。117 项相关回归及真实本地浏览器夹具通过；空闲服务已加载 API96441／Worker96442，五项状态指纹保持。零新增模型调用，真实 Token 收益未验证。详见 [验证记录](docs/evidence/repair-no-model-review-validation-20261009.md) 。以下真实调用数字为包含审查的历史证据。

截至2026-10-09，新repair-v1已完成素材检索及一个两文件跨模块故障的真实DeepSeek返修到待验收，未代用户最终验收。最新跨模块案例13HTTP／396,608Token，无人工改码或纠错，原断言独立Node150项与Chromium60条通过；收尾效率仍待优化，不代表任意项目稳定交付。

[面试演示指南](docs/DEMO_GUIDE.md) 提供固定静态网站、零模型启动、具体交互及只读恢复核查；当前地址为 http://127.0.0.1:51881/ 。完整真实进度与局限见 [ROADMAP](ROADMAP.md) ，下文阶段性「真实返修未验证」保留为当时历史。

## Sandbox v1 当前能力

首版支持已有原生网站的固定 Node／HTTP／Chromium 测试。新 `repair-v1` 的自测与提交验证统一经过 SandboxRuntime；旧任务保持原路径，未自动隔离。执行容器只读、断网、非 root，宿主以可信静态服务预览同一冻结快照。浏览器脚本需显式使用 `chromium_sandbox=True`。

构建命令：`docker build -t ai-agent-product/website-repair:pw-1.55.0-v1 runtime-images/website-repair`。构建不会自动启用入口；受控真实探针成功后才保存 `workspace/experiments/docker-isolation-20261005/profile.json`。源码、镜像、环境或证据变化会使启用记录失效，不应手工填成功字段绕过检查。

当前已通过真实隔离与合成流程验证。第二批增加连续主会话、任务产品写权限与明确提问／回答，执行及审查采用固定响应，真实模型返修未验证。运行记录见 [Sandbox 真实验证](docs/evidence/sandbox-isolation-real-20261009.md) 。

## 2026-10-05 返修升级第一批

显式新返修方式已增加全产品／需求版本提交、程序固定测试→启动→浏览器→独立原目标审查、实际 HTTP 累计请求守卫和独立预算停止原因。旧任务保持原流程，未自动迁移。API 可返回执行方式、返修阶段、当前提交和预算；新方式的验收携带提交 ID 与任务版本。

Sandbox v1 已按固定 Docker 后端实现，真实探针与合成集成通过；`repair_request` 仅在本机启用 profile 匹配当前控制源码、证据、镜像和 Docker 环境时放行，否则返回 `409 repair_execution_isolation_pending`。当前是机制实现和本地验证，不能据此声称已完成真实新模式返修。连续执行会话与任务产品范围写权限已实现；受控搜索、按实际可见范围读取去重和完整批次上下文接力已实现及机制／真实工具合成验证，真实模型效果未验证。详细设计见 `docs/DEV_DESIGN.md` 顶部，验证见 `docs/evidence/repair-v1-fixed-validation-20261005.md`。

第一目标是通过亲自做产品和工程决策，检验并提升 AI Agent 工程能力；第二目标是自用项目成果。

这是独立的新项目，不自动继承旧学习仓库或旧「AI 软件开发团队模拟器」的教程门禁、阶段划分、角色数量、架构、技术栈或实现。

## 已确认方向

用户提出软件需求，系统通过必要对话确认事项，自主推进生成、验证和修复，最终交付可运行的软件。

首版场景：用户通过本地网页提出「做一个计算器」，系统完成必要澄清后，生成并启动计算器，用户通过网页实际使用。

首版验收意图：在已确认的功能和输入范围内计算正确；对非法及超限输入明确处理，不出现未处理异常或界面失去响应，错误后仍可继续使用。

以上是方向与验收意图，不是完整 PRD。计算器功能、输入范围、精度、交互及系统用户流程由用户后续设计，当前均待确认。大量测试通过不代表绝对没有 bug，单个计算器成功不代表具备任意软件生成能力。

## 当前实际能力与入口

新任务采用架构骨架加逐业务切片流程：架构固定模块、数据所有者、公共接口和关键流程后，受限 Scaffolder 先生成可加载入口、模块接口、装配关系和逐模块 `test.todo` 骨架；Dev Design 只生成第一张结构化执行卡。开发完成当前切片的实现、自测和程序独立测试，并清除本片 todo 后，Planner 才依据真实代码与测试选择下一片。内部文件与实现顺序可有界重规划，改变需求、数据所有权、公共接口语义或验收仍回用户决定。已有 `development-plan.json` 的任务保留旧逐单元恢复入口。最终全量测试、HTTP、真实浏览器和人工验收门禁不变。工具上下文复用执行账本，按文件合并当前读取／写入与版本状态；原始历史可按需查询。真实素材管理基准仍暴露测试覆盖绑定和 Developer 上下文收敛问题，证据见 `ROADMAP.md`。

v1 最小完整链路已实现。v2 在此基础上增加全过程实时可视化：React 展示完整阶段时间线、动作流和按需加载的原始 Trace；FastAPI 提供 Trace 增量索引与详情接口；Worker 追加记录模型输入输出、工具执行、程序校验、用户事件和状态转换。MySQL 保存结构化索引，每个任务工作区永久保存不可覆盖的完整 Trace。人工验收时用户只需描述问题，系统会对照正式需求与设计自动识别需求变更、架构问题、Dev Design 问题、实现缺陷或信息不足，并返回最早需要修订的阶段。产品上下文把模型问题与用户回答作为不可拆分的问答单元，并记录后续写入文件的路径、哈希和来源轮次。进入架构和 Dev Design 后，由 Transition Planner 对照新旧上游、差异及旧产物决定增量修订、确认复用或等待澄清；开发阶段以 Dev Design 血缘判断是否必须修改现有代码，不再按“文件已存在”直接跳过。

机制测试、本机 HTTP 冒烟、真实 MySQL／DeepSeek 完整链路、Kimi Code 模型与工具调用，以及 Kimi→DeepSeek 阶段路由均已验证。Windows 运行和用户本人操作仍待验证，不能据此视为已验收。详见 `ROADMAP.md`。

- [AGENTS.md](AGENTS.md) ：长期协作规范与职责边界。
- [ROADMAP.md](ROADMAP.md) ：当前真实进度与验证记录。
- [架构问题记录](docs/architecture-issues/README.md) ：按问题保存方案演进、取舍、测试、成本及未解决状态，供回顾和面试时复核。
- [docs/README.md](docs/README.md) ：设计文档与证据的存放位置、所有权。
- [docs/product/开发团队模拟器 — 产品需求文档 v1](docs/product/开发团队模拟器%20—%20产品需求文档%20v1) ：当前有效的 v2 产品需求、范围和验收标准；保留原文件路径。
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ：当前有效的 v2 架构设计与技术选择。
- [docs/DEV_DESIGN.md](docs/DEV_DESIGN.md) ：当前有效的 v2 接口、数据、状态、关键流程和失败策略。

## 手动模型实验留存

付费隔离实验统一保存到 `workspace/experiments/<experiment>/`，包含 SQLite、生成产品、完整 Trace／检查点、脱敏请求和调用计数；沿用 `workspace/` 的 Git 忽略规则。恢复必须明确指定原目录，缺失断点或非法计数时停止，不自动新建数据库或重置次数。实验控制脚本也须留在项目或实验目录，完整断点不只留报告摘要。

正式任务继续使用 MySQL 和 `workspace/{task_id}/`。本地留存不是异地备份，旧已丢失实验不会被自动恢复；真实调用仍需明确范围与预算。入口及目录约定见 [docs/README.md](docs/README.md) ，机制证据见 [留存验证](docs/evidence/experiment-storage-validation-20261003.md) 。

## 当前本机服务（2026-10-03 恢复验证）

- 前端：[http://127.0.0.1:5173](http://127.0.0.1:5173) ，旧任务示例：[Task 23](http://127.0.0.1:5173/?task=23) 。
- API：[http://127.0.0.1:8001/health](http://127.0.0.1:8001/health) ，8000 已由其他项目占用，本轮保留该服务。
- MySQL 沿用已有 `id-photo-mysql` 数据卷和 `dev_team_simulator`；单 Worker 已恢复，启动前没有可运行任务或待处理事件。

本轮仅在进程环境设置数据库认证和前端 `VITE_BACKEND_URL`，未修改 `.env`。正式任务／调用计数／表结构／产品哈希保持，真实 Chrome 只读界面检查通过；旧临时素材平台未恢复，新模型返修未执行。证据见 [正式服务恢复](docs/evidence/formal-service-recovery-20261003.md) 。以下 Windows 命令仍使用其默认端口。

## Windows 本地运行

模型回答保留实时展示，但流式片段不永久保存。审计保存完整请求、合并后的响应、工具和状态记录；调用中断时保存部分响应与错误。当前回答使用系统临时目录中的单份快照，调用结束清空，旧版流式 Trace 不删除。

前置条件：Python 3.12、Node.js、MySQL，以及可用的 DeepSeek 和 Kimi Code API Key。先创建空数据库 `dev_team_simulator`，再在 PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python -m playwright install chromium
Set-Location frontend
npm install
Set-Location ..
```

仅在当前 PowerShell 会话设置数据库配置，不写入 `.env`：

```powershell
$env:SIMULATOR_DATABASE_URL = "mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/dev_team_simulator"
```

DeepSeek Key 使用项目内被 Git 忽略的独立文件。由用户亲自创建并填写，开发助手不得读取、搜索或输出其内容：

```powershell
New-Item -ItemType Directory -Force secrets
notepad secrets\deepseek_api_key
$env:SIMULATOR_DEEPSEEK_API_KEY_FILE = "secrets/deepseek_api_key"
```

密钥文件只包含 Key 本身，不加变量名、引号或其他内容。`secrets/` 已被 `.gitignore` 整体排除。

Kimi Code Key 同样使用独立密钥文件：

```powershell
notepad secrets\kimi_api_key
$env:SIMULATOR_KIMI_API_KEY_FILE = "secrets/kimi_api_key"
```

OpenRouter 是供独立模型探针使用的可选 Provider。Key 由用户自行保存在独立密钥文件；默认模型为 `openai/gpt-6-luna`，推理强度为 `medium`：

```powershell
notepad secrets\openrouter_api_key
$env:SIMULATOR_OPENROUTER_API_KEY_FILE = "secrets/openrouter_api_key"
$env:SIMULATOR_MODEL_PROVIDER = "openrouter"
```

`SIMULATOR_MODEL_PROVIDER` 不改变正式 Worker 的阶段路由。OpenRouter Runtime 从启动该进程的 `https_proxy`／`HTTPS_PROXY` 读取 HTTPS 代理；启动前需确认该变量指向可用代理。2026-09-24，经环境代理的真实 Luna 流式请求已返回工具调用并完成解析；Luna 仍未接入正式返修阶段。详见 `ROADMAP.md`。

Worker 按阶段自动路由：需求文档、架构设计和 Dev Design 首选 Kimi Code；开发、测试、启动、浏览器验证及返修使用 DeepSeek。Kimi 调用发生凭据、HTTP、传输或响应协议等技术故障时，同一逻辑调用自动降级到 DeepSeek；业务评审、澄清或校验不通过不会触发降级。Kimi 默认使用 OpenAI 兼容端点 `https://api.kimi.com/coding/v1` 和自动升级别名 `kimi-for-coding`，单次最大输出为 8192 Token；模型 ID 和输出上限可分别用 `SIMULATOR_KIMI_MODEL`、`SIMULATOR_KIMI_MAX_COMPLETION_TOKENS` 覆盖。

分别打开三个 PowerShell 窗口，并在项目根目录运行：

```powershell
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
.venv\Scripts\python -m backend.app.runtime.worker
```

```powershell
Set-Location frontend
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。运行测试：

```powershell
.venv\Scripts\python -m pytest -q
Set-Location frontend
npm run build
```

连续会话实现及验证见 [第二批验证](docs/evidence/repair-session-validation-20261009.md) 。

受控搜索与上下文验证见 [第三批记录](docs/evidence/repair-search-context-validation-20261009.md) ，面试讲解见 [面试证据索引](docs/INTERVIEW_GUIDE.md) 。
