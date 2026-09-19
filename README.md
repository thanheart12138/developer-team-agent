# AI Agent 工程实践项目

第一目标是通过亲自做产品和工程决策，检验并提升 AI Agent 工程能力；第二目标是自用项目成果。

这是独立的新项目，不自动继承旧学习仓库或旧「AI 软件开发团队模拟器」的教程门禁、阶段划分、角色数量、架构、技术栈或实现。

## 已确认方向

用户提出软件需求，系统通过必要对话确认事项，自主推进生成、验证和修复，最终交付可运行的软件。

首版场景：用户通过本地网页提出「做一个计算器」，系统完成必要澄清后，生成并启动计算器，用户通过网页实际使用。

首版验收意图：在已确认的功能和输入范围内计算正确；对非法及超限输入明确处理，不出现未处理异常或界面失去响应，错误后仍可继续使用。

以上是方向与验收意图，不是完整 PRD。计算器功能、输入范围、精度、交互及系统用户流程由用户后续设计，当前均待确认。大量测试通过不代表绝对没有 bug，单个计算器成功不代表具备任意软件生成能力。

## 当前实际能力与入口

已接入模块／功能串行流程：架构输出有依赖顺序和文件归属的开发计划，先评审共享契约，再逐单元生成 Dev Design；开发通过 run_unit_tests 先自测，根据真实结果修复并重测，当前范围文件版本通过后才能显式提交，之后仍独立测试；无进展有提醒与停止。最终集成失败先只读诊断责任单元，再在原所有权内修复或回设计澄清，保留全量与真实浏览器门禁。工具上下文复用执行账本，按文件合并当前读取／写入与版本状态，提供必要失败、已完成单元测试状态和开发交接提示；原始历史可按需查询，近期完整交互不自动累积。完整自主交付仍未通过真实验证，机制与能力证据见 `ROADMAP.md`。

v1 最小完整链路已实现。v2 在此基础上增加全过程实时可视化：React 展示完整阶段时间线、动作流和按需加载的原始 Trace；FastAPI 提供 Trace 增量索引与详情接口；Worker 追加记录模型输入输出、工具执行、程序校验、用户事件和状态转换。MySQL 保存结构化索引，每个任务工作区永久保存不可覆盖的完整 Trace。人工验收时用户只需描述问题，系统会对照正式需求与设计自动识别需求变更、架构问题、Dev Design 问题、实现缺陷或信息不足，并返回最早需要修订的阶段。产品上下文把模型问题与用户回答作为不可拆分的问答单元，并记录后续写入文件的路径、哈希和来源轮次。进入架构和 Dev Design 后，由 Transition Planner 对照新旧上游、差异及旧产物决定增量修订、确认复用或等待澄清；开发阶段以 Dev Design 血缘判断是否必须修改现有代码，不再按“文件已存在”直接跳过。

机制测试、本机 HTTP 冒烟、真实 MySQL／DeepSeek 完整链路、Kimi Code 模型与工具调用，以及 Kimi→DeepSeek 阶段路由均已验证。Windows 运行和用户本人操作仍待验证，不能据此视为已验收。详见 `ROADMAP.md`。

- [AGENTS.md](AGENTS.md) ：长期协作规范与职责边界。
- [ROADMAP.md](ROADMAP.md) ：当前真实进度与验证记录。
- [架构问题记录](docs/architecture-issues/README.md) ：按问题保存方案演进、取舍、测试、成本及未解决状态，供回顾和面试时复核。
- [docs/README.md](docs/README.md) ：设计文档与证据的存放位置、所有权。
- [docs/product/开发团队模拟器 — 产品需求文档 v1](docs/product/开发团队模拟器%20—%20产品需求文档%20v1) ：当前有效的 v2 产品需求、范围和验收标准；保留原文件路径。
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ：当前有效的 v2 架构设计与技术选择。
- [docs/DEV_DESIGN.md](docs/DEV_DESIGN.md) ：当前有效的 v2 接口、数据、状态、关键流程和失败策略。

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
