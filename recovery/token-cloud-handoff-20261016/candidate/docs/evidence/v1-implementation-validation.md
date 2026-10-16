# v1 首次实现验证证据

日期：2026-09-10

## 已验证：机制

- 输入：FastAPI 任务／事件／消息请求，工具读写与执行请求，Worker 文档批准事件。
- 运行：`.venv/bin/python -m pytest -q`。
- 期望：API 事务与错误语义正确；事件按状态和文档版本消费或拒绝；工具拒绝越界路径并执行原子覆盖；读取限制为 100 KB；Worker 重启复用运行中的 StepRun。
- 实际：24 项测试通过。
- 测试位置：`tests/test_api.py`、`tests/test_tools.py`、`tests/test_worker_events.py`、`tests/test_model_runtime.py`。

## 已验证：前端构建

- 运行：在 `frontend/` 执行 `npm run build`。
- 期望：React 页面可生成生产构建。
- 实际：Vite 8.2.2 构建成功，输出位于 `frontend/dist/`。

## 已验证：FastAPI 实际启动和 HTTP

- 临时条件：SQLite 文件替代 MySQL，仅用于本机 HTTP 冒烟，不作为正式数据库证据。
- 运行：启动 Uvicorn 后请求 `/health`、创建任务、查询任务、增量查询消息。
- 期望：分别返回 HTTP 200、201、200、200，首条用户消息与任务处于同一持久化结果中。
- 实际：全部符合预期，随后正常停止服务。

## 已验证：MySQL 8.4

- 运行环境：现有 Docker 容器 `id-photo-mysql`，数据目录挂载为 Docker volume `/var/lib/mysql`。
- 创建结果：新建独立数据库 `dev_team_simulator`，字符集／排序规则为 `utf8mb4`／`utf8mb4_0900_ai_ci`。
- 表结构：创建 `tasks`、`step_runs`、`events`、`messages` 四张 InnoDB 表；字段数分别为 15、16、8、5。
- 约束：三张子表均有指向 `tasks.id` 的外键，`step_runs` 有 `uq_step_attempt` 唯一约束。
- 行为验证：在同一事务中写入一条 Task 及对应 StepRun、Event、Message，三条关联记录均可查询；随后回滚，确认测试 Task 数量为 0。
- 应用连接：项目 SQLAlchemy／PyMySQL 代码实际连接 MySQL 8.4.11，在事务内写入四个 ORM 模型并回滚；三个关联对象均可查询，回滚后测试 Task 为 0。
- 隔离检查：原 `id_photo` 数据库仍存在，未重启容器，未修改其表结构或数据。

## 已验证：进程与真实浏览器

- `exec` 后台进程：在随机本地端口启动 Python HTTP 服务，状态检查为运行，HTTP 返回 200；停止后端口确认释放，未遗留进程。
- Playwright：安装 Chromium 140.0.7339.16、Headless Shell 和 FFmpeg 到 Playwright 用户缓存。
- 浏览器联调：临时启动 FastAPI 内存数据库与 React，通过真实 Chromium 打开页面、点击「开始开发」，页面显示 `任务 #1`、`product_docs · pending` 和完整用户需求；随后正常停止两个服务，任务未写入 MySQL。
- 前端依赖审计：`npm audit --omit=dev` 成功，报告 0 个已知漏洞。
- DeepSeek 本地封装：使用拦截 HTTP 的测试核对固定 `deepseek-flash` 模型 ID、认证头、工具调用解析和 Message 持久化；这不是实际模型能力证据。
- 密钥文件：实现 `SIMULATOR_DEEPSEEK_API_KEY_FILE`，默认读取被 Git 忽略的 `secrets/deepseek_api_key`；使用测试临时文件和假密钥验证读取，未创建、读取或输出真实密钥文件。

## 已验证：真实 DeepSeek V4.1 Flash

- 官方 `/models` 实时返回 `deepseek-flash` 和 `deepseek-v4-pro`，据此将 V4.1 Flash API 模型 ID 固定为 `deepseek-flash`，并先更新架构与 Dev Design 后修改实现。
- 使用密钥文件完成一次最小真实调用，模型返回 `OK`，`finish_reason=completed`，Message 持久化成功；密钥未输出。
- 首次真实 `product_docs` Step 用 4 次模型调用生成候选并正确进入 `waiting_user`，但候选擅自增加连续计算且重新询问已固定技术事项，判定为内容失败。
- 增加 v1 固定边界后，第二次运行成功写入候选，但模型反复读取文件直至 10 次上限，Task 正确进入 `failed`。检查点证明程序错误地等待模型口头结束。
- 修正为“目标文件成功写入并经程序验证后立即结束模型循环”，新增回归测试；第三次真实 Step 只调用模型 1 次，生成候选并正确进入 `waiting_user`。候选覆盖计算器四则运算、两位小数、本地浏览器边界和验收标准，未重新询问技术栈。

## 已验证：真实完整任务与验收返修

- 真实任务：Task 3，名称 `v1-real-e2e-calculator`，数据库为 Docker MySQL 中的 `dev_team_simulator`。
- 产品阶段：开发助手按用户授权作为测试用户回答 DeepSeek 的澄清问题；产品文档经过五轮候选，最终固定两个数字输入、默认加法、四则运算、half-up 两位小数、无效输入与除零错误恢复，以及无键盘、无连续计算、无历史记录边界，并批准进入后续步骤。
- 后续步骤：真实完成 `architecture_docs`、`dev_design`、`develop`、`test`、`start_product`、`verify_product`；DeepSeek 生成六个必需产品文件。
- 生成软件单元测试：Node 内置测试共 18 项，通过 18 项、失败 0、跳过 0。
- 生成软件浏览器验证：真实 Chromium 共 29 项，通过 29 项、失败 0，console error 为 0；覆盖页面结构、四则运算、half-up 舍入、无效输入、除零、错误后恢复和单次计算。
- 门禁缺陷复现：首次 `verification-report.md` 显示 Playwright 因运行环境缺失而输出 `[SKIP]`，但脚本退出码为 0，Task 错误进入 `waiting_acceptance`。
- 修复：Worker 改用 `sys.executable` 对应的 Python 环境运行生成验证器，并明确拒绝 stdout 含 `[SKIP]` 的结果；新增回归测试证明跳过结果不能通过门禁。
- 返修闭环：开发助手以验收者身份提交上述缺陷，Task 正确从 `waiting_acceptance` 返回 `test`，重新执行测试、换端口启动和真实浏览器验证；新报告无 `[SKIP]` 且 29 项全部通过。
- 最终状态：开发助手依据用户授权代行测试用户批准验收，Task 3 状态变为 `succeeded`，无 failure reason。
- 全链路同时暴露并修复：产品上下文缺固定边界、用户历史不完整、模型循环结束条件错误、DeepSeek 原生工具消息协议缺失、生成路径错误、网络瞬断无有界重试、HTTP 健康检查继承代理，以及停止后台服务遗留子进程。

## 已验证：产品澄清与 Draft 双门径

- 初次真实验证使用 Task 6，初始输入仅为“帮我做一个网页版计算器”。DeepSeek 直接生成 Draft，并擅自加入四则运算、数字键盘、清除键和除零规则；据此判定阻塞问题判断失败，未把程序状态正常推进误报为产品流程通过。
- 修正规则后创建 Task 7。首轮真实 DeepSeek 返回三个产品问题，Task 为 `waiting_user`，`product_document_available=false`，且工作区没有 `product-v1-draft.md`。
- 开发助手作为测试用户回答后，程序恢复同一个 Product StepRun；模型确认信息充分后生成 `product-v1-draft.md`，Task 仍为 `waiting_user`，但 `product_document_available=true`。
- 批准前 `docs/product.md` 不存在；提交批准事件后，`docs/product.md` 出现且与获批 Draft 字节完全一致，Task 随后才进入 `architecture_docs`。
- 使用 Codex 内置浏览器真实操作 Task 8：初始模糊需求提交后，页面只展示 DeepSeek 问题及“回答产品问题”输入区；提交答案后才切换为“确认产品文档”与 Draft 预览。
- 防护验证：没有 Draft 时提交文档批准会被拒绝；API 明确返回 `product_document_available`；后端回归测试共 20 项通过，前端生产构建通过。

## 已验证：文档阶段工具历史隔离

- 失败复现：真实 Task 7／9 均在架构 Reviewer 阶段报告 `architecture_review_missing`。Draft 已存在，但 Review 不存在。
- 直接证据：模型消息明确表示自己看到了此前写入 `architecture-draft.md` 的工具动作，并误认为该动作是当前 Reviewer 所做，因此只在文本中拟出评审内容，没有调用 `write`。
- 根因：一个 StepRun 内连续执行 Draft、Review、Formal 三次独立模型循环，但恢复逻辑把整个 StepRun 的工具历史都传给每一次调用，破坏了角色与阶段上下文隔离。
- 修复：检查点条目增加 `history_key`；传给模型的 `tool_history` 只包含当前阶段同一 key 的成功工具记录，完整检查点仍保留所有阶段记录用于审计与恢复。
- 机制验证：新增回归测试构造已有 `architecture_draft` 工具记录，再启动 `architecture_review` 循环，确认 Reviewer 收到的工具历史为空；后端测试总数增至 21 项并全部通过。
- 真实验证：Task 8 的架构阶段依次生成 `architecture-draft.md`、`architecture-review.md`、`architecture.md` 并进入 `dev_design`；随后又依次生成 `dev-design-draft.md`、`dev-design-review.md`、`dev-design.md` 并进入 `develop`。

## 已验证：产品 Draft 程序级硬门禁

- 失败复现：真实 Task 10 的初始输入已明确四则运算和两位小数，但仍缺输入交互、连续计算、异常行为与舍入规则。模型直接生成 Draft，且 Draft 自身列出 7 项“尚未确定、需用户确认”，证明单靠提示词约束同一次调用不可靠。
- 修复：产品阶段拆为两次上下文隔离的模型调用。第一阶段的工具列表为空，只允许返回 `BLOCKED` 加问题或严格的 `READY`；程序仅在返回内容逐字符等于 `READY` 时启动第二阶段，第二阶段才提供 `write` 工具生成 Draft。
- 防护：无工具的门径调用若仍返回工具动作，程序以 `model_tool_call_not_allowed` 拒绝；任何空值或非 `READY` 返回都不能进入 Draft 生成。
- 机制验证：新增测试确认门径请求的 tools 为空、阻塞时 Task 进入 `waiting_user` 且 Draft 不存在；后端测试总数增至 22 项并全部通过。
- 真实验证：Task 11 使用与 Task 10 相同的初始需求。首轮 DeepSeek 返回 `BLOCKED` 和三个问题，Task 为 `waiting_user`、`product_document_available=false`、Draft 不存在；回答后门径调用返回严格 `READY`，随后独立生成调用创建 `product-v1-draft.md`，而正式 `product.md` 仍不存在。
- 提问密度调整：第一次放宽后 Task 13 错误地把按钮键盘、C 键与连续计算当作默认假设，因这些会改变控件和状态行为，判定真实测试失败。收准规则后，Task 14 对相同需求只询问“输入交互形态”和“单次或连续运算”两个独立决策，不再追问布局、样式或具体提示文案；此时 Draft 仍不存在。

## 已验证：模型传输重试与调用额度分离

- 失败复现：Task 17 在 `product_docs` 失败，检查点包含 10 条 `ConnectError`，没有模型消息、工具调用或 Draft，最终错误却是 `model_call_limit_exceeded`。
- 根因：传输异常通过外层模型循环立即重试；每次连接失败都先增加 `model_call_count`，且没有退避，短时网络故障会快速耗尽整个 Step 的业务调用额度。
- 修复：每次逻辑模型调用内部最多进行 3 次传输重试，退避为 0.5 秒、1 秒；连接异常、HTTP 429 和 5xx 使用该独立额度，不重复增加 `model_call_count`。耗尽后返回 `model_transport_failed:<错误类型>`；其他 4xx 不重试。
- 机制验证：一次连接失败后成功时底层调用 2 次、逻辑调用计数为 1；连续失败时底层调用 3 次、逻辑调用计数仍为 1，并保留 `model_transport_failed:ConnectError`。后端测试总数增至 23 项并全部通过。
- 真实验证：DeepSeek 官方地址连通并返回未认证 `401`；重启 Worker 后创建 Task 18，真实模型一次正常返回产品问题，Task 进入 `waiting_user`，无传输错误检查点，未再出现调用上限错误。

## 已验证：真实单元测试失败返修

- 失败复现：Task 19 的生成计算器有 15 项测试，其中 3 项失败；两项源于等待右操作数时显示错误回落到 `0`，一项测试期望与正式 Dev Design 冲突。任务连续进入三轮返修但没有改变文件，之后一次恢复又因逐文件读取耗尽 10 次模型调用。
- 根因：`develop` 在发现六个必需文件齐备时直接推进到 `test`，返修轮次也错误复用该捷径；取消捷径后，返修上下文仍只给文件路径，模型必须反复调用 `read` 才能获得现状。
- 设计与实现修复：先在 Dev Design 明确返修不得因文件齐备而跳过；程序一次性提供正式设计、最新测试报告及全部当前产品文件，返修只开放 `write`、`exec`，并以至少一个产品文件实际变化作为完成条件，否则返回 `repair_made_no_changes`。
- 机制验证：新增回归测试确认必需文件全部存在且 `repair_round > 0` 时仍调用模型，模型直接获得当前文件内容，且未改文件不能进入下一步；后端测试共 24 项通过。
- 真实验证：恢复 Task 19 后，DeepSeek 修改 `product/app.js` 和 `product/calculator.test.js`；系统执行 Node 单元测试 15／15，通过后启动生成软件并完成真实浏览器验证，任务进入 `waiting_acceptance`。开发助手随后在生成产品目录独立执行 `node --test calculator.test.js`，结果为通过 15、失败 0、跳过 0。

## 未验证

- Windows 本地运行：当前验证环境为 macOS。
- 用户本人实际操作验收：待用户执行；当前最终验收由开发助手按用户授权代行测试用户完成。
