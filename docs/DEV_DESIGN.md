# 开发团队模拟器——Dev Design v2

## 文档状态

- 版本：v2
- 状态：当前有效
- 确认日期：2026-09-10
- v2 确认日期：2026-09-11
- 依据：当前产品需求文档与 `docs/ARCHITECTURE.md`

## 1．范围与原则

本设计用于实现本地单用户、严格单 Worker 的首版完整链路。v1 固定生成一个原生 HTML、CSS、JavaScript 计算器，不实现多 Worker、同时调用多个模型、动态工具注册或真正的安全沙箱；人工验收问题允许一次有界的跨阶段返工。模型传输层按当前 Step 在 DeepSeek 与 Kimi 之间固定路由。

程序负责校验文件、数据库状态、工具结果和状态转换。模型只能提出内容或结构化工具调用，不能自行宣称写入、测试、启动或交付成功，也不能自行指定下一 Step。

## 2．数据模型

字段类型、长度、索引名称和外键写法在实现时按 MySQL 统一确定，不得改变以下字段语义。

### 2.1 Task

```text
id
task_name
cur_step
status
workspace_path
result_url
port
process_id
process_command
product_path
repair_round
version
failure_reason
created_at
updated_at
```

- `id` 是返回前端的 `task_id`，不重复设置另一列 Task ID。
- `repair_round` 是测试、启动或真实验证失败后返回开发阶段的累计次数，最多为 3。
- `version` 防止 FastAPI 与 Worker 同时更新任务时互相覆盖，不用于 Worker 竞争。
- 端口、进程及结果字段在软件成功启动后写入；任务失败时写入 `failure_reason`。

### 2.2 StepRun

```text
id
task_id
step
status
attempt
model_call_count
input_path
output_path
message_path
checkpoint_path
last_completed_action_index
error
started_at
finished_at
created_at
updated_at
```

- 每次进入一个 Step 创建一条 StepRun。
- `attempt` 表示该 Step 的第几次执行。
- `model_call_count` 必须持久化，单个 Step 最多为 100。
- `checkpoint_path` 指向本次 Step 的运行检查点；`last_completed_action_index` 指向最近一次已持久化成功的 Action。
- 输入、输出或消息路径在当前 Step 不需要时允许为空。

### 2.3 Event

```text
id
task_id
type
status
data
error
created_at
processed_at
```

Event 类型：

```text
user_message
document_approval
acceptance_result
```

Event 状态：

```text
pending
consumed
rejected
```

- 用户事件不设置过期时间。
- Event 是否有效由任务当前状态、当前 Step 和目标文档版本决定。
- Event 与任务状态不匹配时标记为 `rejected` 并记录原因。

### 2.4 Message

```text
id
task_id
role
content
created_at
```

- MySQL Message 表是消息的权威来源。
- `id` 同时作为前端增量查询游标，不另设 `cur_text_id`。
- Workspace 中的 Markdown 消息文件只是过程快照或审计产物。

关系：

```text
Task 1 ── N StepRun
Task 1 ── N Event
Task 1 ── N Message
Task 1 ── N TraceRecord
StepRun 1 ── N TraceRecord
```

### 2.5 TraceRecord

```text
id
task_id
step_run_id
sequence
step
attempt
type
status
title
summary
detail_path
metadata
started_at
finished_at
created_at
```

- `sequence` 在单个 Task 内严格递增，与 `task_id` 组成唯一约束，是前端增量游标。
- TraceRecord 只追加，不提供更新和删除接口。
- `detail_path` 必须指向当前任务工作区 `traces/` 内已写入的 JSON 文件。
- MySQL 保存结构化摘要与索引，完整输入输出保存在详情文件。
- Trace 不作为状态机判断依据；记录失败不得将原本可成功的任务改为失败。

## 3．状态机

### 3.1 TaskStatus

```text
pending
running
waiting_user
waiting_acceptance
succeeded
failed
```

### 3.2 StepStatus

```text
running
waiting_user
succeeded
failed
```

### 3.3 固定 Step

```text
product_docs
architecture_docs
dev_design
develop
test
start_product
verify_product
```

`waiting_user` 和 `waiting_acceptance` 是 Task 状态，不是 Step。固定转换表只限定合法候选阶段；Transition Planner 决定候选阶段采用 `execute`、`revise`、`reuse` 或 `clarify`。程序校验决定后才更新 Task，模型不能返回任意跳转。

### 3.4 状态转换

```text
创建任务                         → product_docs
product_docs 存在阻塞问题        → waiting_user（等待用户回答，不生成 draft）
用户回答阻塞问题                 → 恢复同一个 product_docs StepRun 继续判断
product_docs 无阻塞问题并生成候选 → waiting_user（等待用户确认 draft）
用户拒绝产品文档                 → product_docs 重新生成候选
用户批准且正式文件写入成功       → architecture_docs
architecture_docs 成功           → dev_design
dev_design 成功                  → develop
develop 成功                     → test
test 失败且 repair_round < 3     → repair_round + 1，develop
test 失败且 repair_round = 3     → failed
test 通过                        → start_product
start_product 失败且可返修        → repair_round + 1，develop
verify_product 失败且可返修       → repair_round + 1，develop
返修次数达到 3 后再次失败         → failed
start_product 成功               → verify_product
verify_product 通过              → waiting_acceptance
用户验收通过                     → succeeded
```

状态与文件的更新必须经过程序校验。模型不能直接写 Task 或 StepRun 状态。

## 4．FastAPI 接口语义

具体 URL 和 HTTP 方法在实现时统一命名，以下请求、响应及状态语义不得改变。

### 4.1 创建任务

输入：

```text
task_name
initial_message
```

输出：

```text
task_id
status = pending
cur_step = product_docs
```

API 在同一事务中创建 Task 和用户 Message，然后返回 `task_id`。

### 4.2 查询任务

输入：`task_id`。

输出：

```text
task_id
status
cur_step
latest_message_id
artifact_available
product_document_available
result_url
failure_reason
```

`product_document_available` 仅表示当前 `product_docs` 已产生可审批的 draft。`waiting_user` 且该值为 `false` 时，前端展示问答输入；为 `true` 时展示产品文档预览和批准／退回操作。

任务不存在时返回明确的 `task_not_found`。

### 4.3 提交用户事件

输入：

```text
task_id
type
data
```

API 校验基本结构并创建 `pending` Event。`document_approval` 的 `data` 至少包含：

```json
{
  "document_type": "product",
  "document_version": 1,
  "approved": true,
  "feedback": ""
}
```

文档类型、版本或任务状态不匹配时，由 Worker 将 Event 标记为 `rejected`。

### 4.4 获取消息

输入：

```text
task_id
after_id
```

输出 `id > after_id` 的有序消息和 `latest_message_id`。前端保存最大 Message ID 作为下一次查询游标。

### 4.5 获取产物

允许任务状态：

```text
waiting_acceptance
succeeded
failed
```

返回已有的：

```text
README 内容或路径
result_url
测试报告路径
失败报告路径
其他产物索引
```

`failed` 状态可以读取已有产物和失败证据，但不表示软件可验收。

### 4.6 提交验收结果

验收通过时创建 `acceptance_result` Event，Worker 将任务从 `waiting_acceptance` 更新为 `succeeded`。

用户报告问题时：

1. 用户只提交问题描述，不选择问题类型。
2. Worker 调用 Kimi 对照正式需求、架构、Dev Design 与验证证据分类，并由程序校验固定枚举和目标阶段。
3. 需求、架构或 Dev Design 问题返回最早失效阶段并生成新版本文档；实现问题返回 `develop`，将反馈加入 DeepSeek 返修上下文。
4. 低置信度或证据不足时进入 `waiting_user`，用户补充后重新分类；不得直接重跑旧测试并再次宣称验证通过。

### 4.6 增量查询 Trace

输入：`task_id`、可选 `after_sequence`，默认 0。输出按 `sequence` 升序返回 Trace 索引，不包含完整大文本，并返回本批次最新序号。

### 4.7 查询 Trace 详情

输入：`task_id`、`sequence`。API 只能读取该任务已登记且位于该任务 `traces/` 目录内的详情文件。记录不存在返回 `trace_not_found`；索引存在但文件缺失或损坏返回 `trace_detail_unavailable`。

### 4.8 Trace 写入协议

模型响应记录 Provider 实际返回的 usage，并在调用详情展示输入、输出、总 Token 及可用缓存用量。缺失用量标为未返回，不按零处理、不估算费用、不补写历史。DeepSeek 请求流式 usage；Kimi 保留现有协议并解析其返回用量。精确列举的 Token 计数字段仅在值为非负整数时免于敏感字段脱敏，token 凭据及其他敏感字段仍脱敏。

请求配置 `max_completion_tokens` 的非负整数值同样保留，表示输出上限而非凭据；其他类型继续脱敏。旧 Trace 已脱敏的数据不倒填。

详情 JSON 至少包含 `type`、`status`、`title`、`summary`、`payload` 和时间信息。写入顺序为：计算下一个任务序号、敏感字段过滤、原子创建详情文件、创建 TraceRecord、提交事务。

流式文本仅用于实时展示，不生成 `model_stream_delta` Trace，也不永久保存 Provider 原始分片数组。Worker 在系统临时目录按任务维护一份原子覆盖的当前回答快照（含 request_id、文本、更新时间），最多每 250ms 更新一次；API 通过 `GET /api/tasks/{task_id}/live-response` 提供快照，超过 15 秒未更新视为过期，响应禁止缓存。每次传输结束清空快照，重试不拼接上一次失败输出。该快照不是审计记录，不保证进程崩溃后的恢复。最终响应保存合并文本、工具调用及 Provider 元信息；传输或协议失败保存截至失败时的部分响应和错误，不保存原始分片。

`artifact` 保存成功写入文件的工作区相对路径、文件名、工具调用 ID 和 SHA-256。模型请求与响应 Trace 的 metadata 都保存同一个 `request_id`。

任务页每 750ms 增量查询消息、Trace 和当前回答快照。左栏按 `created_at` 合并消息和 Trace 摘要，将快照文本显示在对应模型请求下方；收到最终响应后以正式 assistant 消息为准。历史 model_stream_delta 文件保留但不再用于实时展示。右栏展示模型输入、合并响应、工具参数／返回值或文件内容。

`GET /api/tasks/{task_id}/files?path={workspace_relative_path}` 只允许读取该任务工作区内不超过 1MiB 的普通文件。绝对路径、目录和越出工作区的路径一律拒绝。

```text
traces/{step}/{attempt}/{sequence}-{type}.json
```

已存在目标路径时禁止覆盖。敏感键至少覆盖 `authorization`、`api_key`、`token`、`password`、`secret`，匹配不区分大小写。模型请求只记录发送给模型的 messages、tools 和非认证参数，不记录认证头。

记录类型至少包括 `step`、`model_request`、`model_response`、`model_retry`、`tool_call`、`validation`、`user_event`、`state_transition` 和 `warning`；状态包括 `running`、`succeeded`、`failed`、`waiting` 和 `info`。

## 5．Event 消费

FastAPI 不运行事件分发线程，也不寻找对应 Worker。严格单 Worker 同时轮询待执行 Task 和 `pending` Event。

应用 Event 时，以下操作在一个数据库事务中完成：

```text
校验 Event 与当前任务状态
写入对应用户 Message
更新 Task 状态
将 Event 标记为 consumed
```

事务提交前 Worker 退出，所有修改一起回滚，Event 保持 `pending`；事务提交后 Event 已经成功应用。无效 Event 标记为 `rejected` 并记录原因，因此不需要恢复 `processing` 状态。

## 6．Model Runtime

Model Runtime 实现 DeepSeek 与 Kimi 两个 Provider。Worker 创建 Runtime 时必须传入当前 Step，并按下表路由；不允许因调用失败自动切换 Provider，也不同时调用两个 Provider。`SIMULATOR_MODEL_PROVIDER` 仅保留给脱离正式 Worker 流程的模型探针和调试调用。

| Step | Provider | 默认模型 |
| --- | --- | --- |
| `product_docs` | Kimi | `kimi-for-coding` |
| `architecture_docs` | Kimi | `kimi-for-coding` |
| `dev_design` | Kimi | `kimi-for-coding` |
| `develop` | DeepSeek | `deepseek-flash` |
| `test` | DeepSeek | `deepseek-flash` |
| `start_product` | DeepSeek | `deepseek-flash` |
| `verify_product` | DeepSeek | `deepseek-flash` |

测试、启动或浏览器验证失败后将 Task 退回 `develop`，因此返修调用仍由 DeepSeek 执行。同一个 StepRun 内的 `author_agent`、`reviewer_agent`、多轮问答及工具循环不得改变 Provider。

DeepSeek 默认模型为 `deepseek-flash`，请求地址为 `SIMULATOR_DEEPSEEK_BASE_URL/chat/completions`。Kimi 使用 Kimi Code Key，默认模型为自动升级别名 `kimi-for-coding`，默认端点为 `https://api.kimi.com/coding/v1`，请求地址为 `SIMULATOR_KIMI_BASE_URL/chat/completions`。端点和模型 ID 可通过启动配置覆盖；真实调用前必须先通过 Kimi Code `/models` 核验当前可用模型。两个 Provider 分别读取独立的、被 Git 忽略的密钥文件。认证头不进入 Trace。

两者共享 `ModelRequest`、`ModelResult`、消息历史和工具调用映射。Provider 各自构造请求 payload，禁止把某一 Provider 的专属字段无条件发送给另一 Provider。DeepSeek 传输超时为 60 秒，Kimi 长文档传输超时为 180 秒；Kimi 单次最大输出为 8192 Token，防止无界长响应阻塞持久化。两者仍遵循最多 3 次传输重试。Trace 的模型请求、响应和重试元数据必须包含实际 `provider` 与 `model`。

### 6.1 请求

```text
ModelRequest
- instructions
- input
- context
- tools
- request_id
```

模型 API 无状态。每次调用需要的历史消息、文档、工具结果和检查点由程序放入 `context`。

### 6.2 结果

```text
ModelResult
- request_id
- message_id
- text
- actions: List<Action>
- finish_reason
```

`finish_reason`：

```text
completed
tool_calls
failed
```

`message_id` 是本次模型输出写入 Message 表后产生的 ID。一次返回多个 Action 时由 Tool Runtime 按顺序串行执行。

模型 API 返回 HTTP 成功但 `tool_calls` 缺字段或 `function.arguments` 不是合法 JSON 时，属于模型协议错误，不得当作传输错误重发同一次逻辑调用，也不得直接结束整个 Task。程序保存脱敏后的原始响应与失败 Trace，将该次计入 `model_call_count`，随后在单 Step 100 次上限内发起下一次逻辑调用。协议错误耗尽调用上限时，Task 才以 `model_call_limit_exceeded` 失败。

v1 不记录 token usage，不设置 token 或金额预算；单个 Step 的逻辑模型调用次数仍受 100 次硬限制。一次逻辑调用因连接失败、HTTP 429 或 5xx 产生的传输重试使用独立的最多 3 次额度和短退避，不重复增加 `model_call_count`。Kimi 的传输重试耗尽、非重试型 HTTP 错误、凭据／配置调用错误或响应协议错误触发一次 DeepSeek 技术降级；复用同一逻辑调用编号、指令、输入、上下文和工具定义。业务输出的低置信度、澄清、Review 或校验失败不降级。DeepSeek 失败时保留最终错误并终止，不再次切换。

## 7．Tool Runtime

### 7.1 通用协议

```text
ToolCall
- call_id
- tool_name
- parameters
```

```text
ToolResult
- call_id
- tool_name
- status
- output
- error
```

`status` 只能是 `succeeded` 或 `failed`。模型不能直接调用未注册工具。

### 7.2 read

```text
parameters:
- path

output:
- path
- content
- truncated
```

- `path` 必须是当前 Task Workspace 内的相对路径。
- 单次最多返回 100 KB，超出后截断并返回 `truncated=true`。
- 拒绝绝对路径、路径穿越和工作区外目标。

### 7.3 write

```text
parameters:
- path
- content
- overwrite

output:
- path
- bytes_written
```

- `path` 必须是当前 Task Workspace 内的相对路径。
- 新文件要求 `overwrite=false`；修改已有文件要求 `overwrite=true`。
- 采用临时文件写入后原子替换目标文件，随后重新校验文件。
- v1 不提供独立的 update 或 delete 工具。

### 7.4 exec

```text
parameters:
- action
- command
- process_id
```

`action`：

```text
run
start
stop
status
```

- `run` 等待普通命令执行结束。
- `start` 启动后台软件并返回 `process_id`。
- `stop` 根据已记录的 `process_id` 停止后台进程，此时不传 `command`。
- `status` 检查已记录进程是否运行。
- 工作目录由 Tool Runtime 固定为当前任务的 `product/`，模型不得传入工作目录。
- 单条命令最长执行 60 秒，最多保留 100 KB 输出。

输出：

```text
exit_code
stdout
stderr
timed_out
truncated
process_id
running
```

后台进程必须记录 PID、启动命令、产品目录和端口。只有这些信息均能核实属于当前任务时才可停止；端口被未知进程占用时不得停止该进程，应返回 `port_conflict`。

上述约束只是最小隔离，不能阻止命令主动访问工作目录之外的系统资源。v1 不宣称具备安全执行不可信代码的能力。

## 8．Task Workspace 与检查点

```text
workspace/{task_id}/
├─ messages/
├─ docs/
├─ evidence/
└─ product/
```

MySQL 保存运行状态和路径索引，Workspace 保存文档、代码、报告、消息快照和 Step 检查点。

每次 ModelResult、ToolCall 和 ToolResult 先写入 `checkpoint_path` 指向的检查点文件；Action 成功并持久化后，再更新 `last_completed_action_index`。Worker 重启时从最近一次已持久化成功的 Action 继续。同一个 StepRun 内含 Draft、Review、Formal 等独立模型阶段时，每条检查点记录必须带 `history_key`；恢复和构造模型上下文时只加载当前阶段同一 `history_key` 的工具历史，禁止把上一角色／阶段的工具调用伪装成当前模型历史。

## 9．各 Step 流程

### 9.0 工具执行摘要与按需查询（2026-09-17 用户授权）

2026-09-18 用户确认调整（当前有效，覆盖下述先提交后测试约定）：开发先通过 run_unit_tests 自测，再 submit_unit_for_test 交接。自测无命令或范围参数，由程序固定运行当前单元及已完成单元的 Node 测试；结果绑定全部测试范围的文件版本，返回真实输出和通过状态。未测试、测试失败、文件缺失、测试中版本变化或测试后版本过期均拒绝提交。开发模型根据结果在文件所有权和正式设计内修复并重测，不因修改而推断通过。自测证据可从检查点恢复，但必须与当前范围和版本一致；旧无自测证明的提交不能恢复。后续程序仍独立测试、集成验证和浏览器验证；自测通过不能替代后续验证。交接提示优先使用当前自测状态，旧失败明确标记版本是否仍适用，修改后提示自测而非继续认定旧错误存在。调用预算和无进展上限不增加。

2026-09-18 用户确认开发交接与返修路由：单元开发必须调用 submit_unit_for_test，程序校验该单元全部交付文件存在后记录绑定文件哈希的提交，提交必须为该批最后动作；普通结束文本不能替代提交，BLOCKED 仍可回设计。当前／已完成单元测试由程序执行，恢复仅复用版本一致的显式提交；旧中断开发也必须重新提交，不再因文件齐备直接测试。连续 4 次模型调用没有文件版本变化提示提交或说明阻塞，8 次有界停止；若第 8 批刚取得与当前文件版本一致的真实自测通过证据，允许且只允许下一批立即提交，不能在提交前继续读取或诊断。逻辑及 HTTP 总预算不增加。

最终集成失败先有一次无写权限、有界诊断，输入需求、契约、各单元设计、文件所有权、当前代码和实际失败，输出 implementation_error、test_script_error、cross_unit_error、design_conflict 或 unclear，目标单元、问题依据、修复目标和置信度。结果及版本快照保存为该开发 Run 的证据，恢复需版本一致。只有置信度至少 0.8、目标存在且非空、理由和修复目标非空的明确实现／测试问题可修复；普通实现／测试错误必须恰好一个责任单元，跨单元错误至少两个，不能增加所有权或改需求／测试预期。设计冲突、责任不明或非法输出回设计澄清。仅责任单元接收全局失败；其他单元版本匹配时复用，受影响依赖版本变化后照常复验，全单元结束仍执行全量和浏览器验证。诊断不自动修改接口、授权越权或宣布成功。

每次逻辑模型请求沿用 request_id 作为 model_call_id，响应的一批工具调用均关联该 ID；传输重试和 Provider 技术降级复用 ID，下一次续写使用新 ID。系统直接发起的工具调用 parent_model_call_id=null、history_key=system。

2026-09-17 用户确认更新：自动工具上下文复用原账本，按当前 StepRun／history_key 聚合每文件最近一次读取和写入，核对当前 SHA-256，明确读取是否完整且版本仍有效；重复操作不累积。最多提供最近更新的 20 个文件状态，省略数单列；原始记录仍可查询。取消最近一批完整 assistant/tool 历史；仅模型当前请求的读取／查询结果作为 current_requested_data 返回，与当前快照相同的读取全文改为快照引用。无摘要或无证据的旧检查点仍保留原交互，不静默丢失信息；账本不可用保持原回退。未解决失败及执行版本继续提供。单元开发另附已完成单元测试（含依赖）的版本状态、当前缺失文件、当前测试状态和交接提示；文件齐备不等于测试通过，程序仍在模型结束后执行测试，不新增自动推进或循环保护规则。此条覆盖此前最近一批完整交互与逐条摘要窗口约定。

逐工具执行后，程序在任务工作区 evidence/tool-summaries.jsonl 原子保存摘要：summary_id、parent_model_call_id、tool_call_id、step_run_id、history_key、sequence、tool_name、description、status、result_summary、evidence_ref。description 是模型通过工具参数提供的操作目的（最多 200 字符，旧调用缺省用工具名），result_summary 由程序依据真实结果生成；不额外调用摘要模型。write 附工作区相对 file_path、operation、hash_algorithm=sha256、before_hash、after_hash、changed、bytes_written；read 附读取哈希和截断标记；exec 附 action、command、退出码、超时、进程信息。run 时记录产品代码文件哈希，成功验证后文件变化标记旧版本结果过期，不将成功执行等同业务修复。

摘要 ID 由阶段执行、父模型调用及工具调用 ID 确定，同一执行补记不会重复追加。完整原始调用及结果保留现有 Trace 和检查点；摘要写入失败不丢工具结果、不重执行操作，下一轮保留未取得摘要的原始交互。旧任务不批量回填，缺摘要的旧检查点保持完整上下文。账本不是恢复检查点，不提供版本回滚，也不声称覆盖 exec/人工写文件；文件历史返回当前哈希和最后记录是否一致。

新增三个当前任务范围的只读工具：get_file_change_history(file_path,cursor?) 返回成功 write 记录，从新到旧，每页最多 20 条；get_model_call_summaries(model_call_id,cursor?) 返回该模型调用的摘要，按执行顺序，每页最多 20 条；get_tool_execution_detail(summary_id,section=result|call|all,cursor?) 返回原始证据，默认 result，序列化文本每页最多 8,000 字符，使用 next_cursor 继续。游标为非负位置，不接受任务 ID、任意证据路径或绝对文件路径；详情仅从当前任务 traces 读取。查询自身保存短摘要，不复制其大段查询结果到账本。

旧约定（已由本节 2026-09-17 用户确认更新覆盖）：模型上下文只保留同一 StepRun/history_key 最近一批完整 assistant/tool 配对，较早交互由摘要替代。额外提供该循环最近 20 条较早摘要、较早条数、未解决失败的简短错误及证据 ID；完整详情可查询。当前产品文件清单和 SHA-256 每次逻辑调用前刷新；已有修订文件快照刷新为最新版本，近期工具交互已经完整携带当前版本全文时快照不重复携带。旧 write/read 不伪装为当前文件版本。read、exec、write 原始配对不能拆散；仅查询或仅 write 的文档阶段保持原工具权限，不为了压缩而放宽文档生成工具，新增查询工具只加入已有 read/exec 的执行阶段。旧任务返修仍提供完整产品快照，新单元开发按 9.3.1 持续提供范围内当前文件；无工具 Planner 保持无工具。调用预算、Provider 路由及产品存储约束不变。

### 9.1 product_docs

产品门径返回 `READY` 后按三个相互隔离的 history 执行：

1. `product_draft`：写入 `docs/product-vN-draft.md`。
2. `product_review`：独立 Reviewer 对照用户消息、上一版正式 `product.md`、最新验收分类证据和本轮 Draft，只写入 `docs/product-vN-review.md`；报告必须分为“阻塞问题、普通问题、建议”，没有内容的分类明确写“无”。若分类为需求变更而 Draft 仍保留被反馈推翻的旧约束，必须列为阻塞问题。
3. `product_candidate`：Author 根据 Draft 与 Review 写入 `docs/product-vN-candidate.md`，解决阻塞问题并保持用户决策边界。

前端预览和 `document_approval` 只使用 `product-vN-candidate.md`。批准后将候选版原子覆盖为 `product.md`；Draft、Review 和候选版均保留。旧任务只有 Draft 时允许只读回退展示，但新的产品 Step 不得跳过 Review 和候选版。

1. 程序先判断是否已有正式 `product.md`，且本轮验收分类为高置信度 `requirement_change`、一致性校验通过、无澄清问题、每条变更均有明确的现状、期望和可执行例子。满足时，用户本轮反馈覆盖旧文档中冲突的行为，产品门径直接视为 `READY`，不得再次询问反馈是否要实施；后续 Draft、Review 和 Candidate 仍须逐条核对覆盖情况。不满足时执行独立的无工具产品门径判断调用。`author_agent` 根据初始需求、完整问答历史和验收分类判断是否仍有真正未决的产品问题，只能返回 `BLOCKED` 加面向用户的问题，或在无阻塞问题时严格返回 `READY`。产品名称、品类惯例和模型常识不视为用户授权。只有会改变核心功能范围、主要交互形态或导致验收结果无法判定的未决事项才算阻塞；主输入方式、用户触发动作、单次／连续操作方式不得作为默认假设。布局、视觉样式等不改变控件和行为且易于修改的细节可以采用最小默认值，并在 Draft 中明确标为默认假设。
2. 返回值不是严格的 `READY` 时，程序一律按仍有阻塞问题处理；由于该调用没有 `write` 工具，模型无法在判断阶段生成 draft。每轮最多询问三个问题，每个编号只包含一个需要用户决定的事项，不得把多个子问题打包在同一编号。程序保存模型消息，将当前 StepRun 与 Task 置为 `waiting_user`。
3. 用户通过 `user_message` 回答后，程序把同一个 StepRun 恢复为 `running`；模型结合完整用户与助手消息历史再次判断。该循环受单 Step 最多 100 次模型调用限制。
4. 只有门径判断严格返回 `READY` 后，程序才发起第二次、上下文隔离的 Draft 生成调用，并仅在该调用中提供 `write`，生成 `product-v*-draft.md`。判断与生成不再由同一次模型调用完成。
5. 程序验证 draft 文件存在后，将任务置为 `waiting_user`，并通过 `product_document_available=true` 指示前端展示预览和批准／退回操作。
6. 用户拒绝 draft 时，根据反馈创建下一次 Product StepRun 并生成新版候选；模型仍需先判断反馈是否引入新的阻塞问题。
7. 用户批准时，程序将已批准 draft 原子复制为正式 `product.md`，不重新调用模型生成。
8. 程序校验正式文件后，将 StepRun 标记为 `succeeded`，进入 `architecture_docs`。

### 9.2 architecture_docs

1. 首次执行时，`author_agent` 根据正式产品文档生成架构 Draft，再完成 Review 和正式文档。
2. 返工时先保存旧架构正式版本，再生成新旧产品需求差异，并把产品需求 V1、产品需求 V2、需求差异和架构 V1 交给 Transition Planner。
3. Planner 返回 `reuse` 时，程序保存影响判断并沿用旧架构；返回 `revise` 时，Author 以旧架构为基线，只修改 `affected_sections`，生成版本化 Draft、Review 和正式架构；返回 `clarify` 时等待用户。
4. Reviewer 检查需求差异是否完整覆盖、无关架构是否被改动、旧约束是否意外丢失，以及是否引入无需求依据的设计。
5. 当前有效副本为 `architecture.md`，历史正式版本保存为 `architecture-vN.md`。

### 9.3 dev_design

旧单份设计任务保留原有 Transition Planner 及版本化修订流程。已有 `development-plan.json` 的任务继续按 9.3.1 恢复，不批量转换。新生成架构从 2026-09-19 起按 9.3.2 使用逐业务切片流程。

### 9.2.1 架构代码骨架（2026-09-19 用户确认）

新架构正式化后、进入 Dev Design 前，程序在同一个 `architecture_docs` StepRun 内调用一次受限 Scaffolder。输入只包含正式需求、正式架构和固定实现约束；输出为结构化 JSON，声明模块 id、公共接口、实现文件、独立测试文件及全部初始文件内容。程序只接受 `product/` 下的规范相对路径，要求每个模块至少一个实现文件和唯一测试文件，并要求固定入口 `index.html`、`verify_product.py`、`implementation.md` 存在。

骨架只建立模块导出、依赖方向、应用启动和页面区域，不实现业务规则。每个模块测试文件用 Node 内置测试框架声明与架构接口对应的 `test.todo`；todo 是明确的未完成账本，骨架结构验证允许存在，但业务切片验证不允许当前测试文件保留 todo／skip。程序保存 `docs/scaffold-contract.json`，绑定产品与架构哈希、模块文件及初始 todo 数量，并执行 HTML 本地引用检查、JavaScript 语法检查和 Node 测试发现。任一文件缺失、引用越界、语法错误、零测试或模块没有 todo 时阻止进入 Dev Design。

Slice Planner 接收骨架契约和剩余 todo，只能选择仍有未完成测试的业务模块或跨模块用户结果。Developer 必须在当前切片内实现业务代码并把对应 todo 改成真实断言；程序除检查进程退出码和测试数量外，还检查本切片测试文件不存在 todo／skip。Planner 只有在骨架 todo 全部清零、固定入口齐全且全部需求有真实测试证据时才能返回 complete。骨架只用于首轮新建且 `product/` 仍为空的任务；已有产品的架构返工保留当前实现并由后续切片增量修改，不覆盖代码。历史任务、已跳过架构任务和旧 `development-plan` 任务不自动转换。

后续切片引用已通过模块的公共接口时，该模块默认作为只读依赖，只在 `required_interfaces` 中声明，不重复加入 owners、implementation_files 或 test_files。只有当前 acceptance 明确要求改变该模块已经交付的行为，Planner 才可把它列入 `rework_delivered_modules`，并为每个模块提供与 acceptance 对应的 `rework_reasons`；程序拒绝无重做声明的已通过模块整包重复纳入。Developer 的预载源码只包含当前可写实现和测试文件，已通过依赖仅开放按需读取；全量历史测试仍由程序执行，不因此复制到当前卡或模型上下文。

### 9.3.2 AI 原生逐业务切片闭环（2026-09-19 用户确认）

2026-09-20 用户确认增量：普通 Developer 完整重复读取被拒后，下一批首次违反推进约束即结束原对话，由 Runtime 切换到独立的受限实现调用。每张卡每次开发尝试最多切换一次，切换原因、历史标识、实现轮次及调用预算持久化；Worker 恢复不得重新进入旧对话或重置额度。

Runtime 根据 required_interfaces、骨架契约及已通过切片确认接口—文件映射，提供当前 owned_files 和必要只读依赖的完整内容及哈希，不携带旧工具对话。映射未知、歧义、依赖未交付或文件缺失时明确阻塞，不能猜路径。受限调用只开放 write、replace 与结构化重规划，实际工具入口同样拒绝 read 和越权写入。一个响应中的相关写入全部处理后，Runtime 直接执行当前及所有前置切片自测；无实际修改则停止，失败才携带新证据进入下一次独立修复，通过后 Runtime 调用既有提交校验，再进入原独立回归。当前切片 todo／skip 不得视为成功。该分支覆盖此前要求模型自主发起自测／提交的规定，旧 Developer 分支保持原协议。

独立实现及修复合计最多四次逻辑调用，共用原 Step 总额度；每次调用前持久化预留额度，异常或进程退出不能返还额度。局部真实验证仅运行 materials 当前切片一次，总 HTTP 上限十二次（含传输重试），不自动增加样本或扩大到全流程。先验证机制，再分别记录真实模型交付、Node 回归及未执行的产品验收，完成度优先于 Token。

架构阶段只固定模块边界、数据／状态所有者、公共接口、关键跨模块流程及需要用户决定的业务规则，不生成全部开发单元、文件所有权和逐单元 Dev Design。架构正式化后创建 `docs/delivery-plan.json`，绑定需求与架构哈希并声明 `workflow=slice-v1`；不预判切片总数。

Slice Planner 每次只返回 `implement`、`complete` 或 `clarify`。`implement` 必须生成一张结构化执行卡，包含目标、涉及的数据所有者、使用的公共接口、当前需要修改的实现文件和测试文件、可执行验收条件。程序校验路径、测试命名、字段完整性、切片标识和上限；测试、说明文档和验证脚本必须并入产生相应业务结果的切片，不能独立成片。`complete` 只在全部需求已由已通过切片覆盖、固定入口已规划且没有未完成卡片时有效。`clarify` 仅用于缺少会改变产品行为的用户决定。

Dev Design 阶段只生成第一张执行卡并写入 `docs/slices/`，`docs/dev-design.md` 为切片索引和恢复入口，不生成共享契约及全部单元长文档。Develop 对当前卡片实现、自测并由程序独立执行当前及此前切片测试；通过后把真实文件和测试结果交给 Planner，再决定下一张卡片。后续计划以当前代码、已通过验收和实际文件清单为依据。每张卡片使用同一 Step 的总模型调用预算，不按切片重置。

业务切片自测失败后进入受限修复状态。模型可以读取失败位置及必要依赖；同一文件哈希未变化时，后续 `read` 与失败后已经成功读取的行区间发生重叠，程序返回 `self_test_repeated_read_requires_change`，要求下一步只能实际修改、结构化重规划或说明设计阻塞。失败后的某批工具实际执行 `write`／`replace` 后，下一次模型调用只允许 `run_unit_tests`；读取、继续诊断、提交或跨批继续修改均返回 `unit_change_requires_self_test`。复测失败后才重新开放必要诊断，复测通过后只允许提交。测试实现若没有正确表达执行卡 acceptance，可以修正回调对象、夹具、数量计算或环境假设；只要业务语义和覆盖强度不降低，就不属于删除、绕过或削弱测试。

集成或浏览器失败只交给拥有失败入口文件的已交付切片，不继承 Develop 阶段剩余的全部 100 次额度。返修采用事务式执行：同一失败证据最多两次模型调用，用于一次必要诊断和一次实际修改；没有文件变化立即失败，不以相同证据重试。修改后程序立即复跑原失败验证，只有真实验证输出变化才允许开启第二轮，整个返修最多两轮、四次模型调用，预算跨 Worker 恢复累计。浏览器验证失败时先核对 `verify_product.py` 的前序操作、数量断言和浏览器存储语义，再决定修改验证脚本还是产品代码；已有 Node 回归通过不能证明验证脚本自身正确。超过 200 行的文件默认只返回前 200 行预览，模型必须按行读取必要片段，并使用唯一精确片段替换完成小范围修改。

返修模型请求只预载失败报告、当前执行卡／验收、文件路径及 SHA-256 清单，不预载 `current_product_files` 全文。模型只能在责任切片的可读范围内，围绕错误位置用 `read` 获取必要行；原始工具执行详情查询在返修中关闭，避免历史整文件写入参数再次进入上下文。文件修改后程序立即复跑原失败验证，新的请求只接收最新结果和当前文件版本。

内部文件清单、实现顺序、非公共内部接口和对既有文件的修改范围可以在当前切片开始开发前或收到结构化阻塞后有界重规划。改变用户需求、数据所有者、公共接口语义、业务规则或验收标准时必须停止并等待用户。独立 Reviewer 默认不调用；只有数据所有权／公共接口变化、实现与架构冲突或真实测试指向上游设计缺陷时才升级设计问题。程序校验和真实测试不能被模型自述替代。

`evidence/slice-progress.json` 保存需求／架构哈希、切片卡、状态、真实测试报告和文件版本。恢复时只复用哈希仍匹配的通过结果；失败及修改中的切片重新验证。全部切片通过后仍进入原全量 Node 测试、HTTP 启动、真实浏览器验证和用户验收。

### 9.3.1 模块／功能设计与逐单元测试闭环（2026-09-17 用户确认）

架构正式化后，模型依据正式需求与架构输出 `docs/development-plan-vN.json`，当前副本为 `docs/development-plan.json`。记录 product_hash、architecture_hash、version、modules 和 units。模块含 id、responsibility、public_interfaces；单元含 id、module_id、kind（module 或 feature）、name、scope、depends_on、implementation_files、test_files、acceptance_criteria。`kind=module` 明确表示整个模块只有这一个开发单元；同一模块有两个及以上单元时，全部单元必须为 `feature`。模型若把一个模块的核心单元标为 module、其他单元标为 feature，程序将其规范化为全部 feature；该规范化只修正调度类型，不改变职责、文件、依赖、接口或验收，并记录在正式计划中，不消耗额外模型调用。

开发单元以数据所有权和业务边界为首要拆分依据，默认一个业务模块形成一个单元。只有候选部分拥有独立数据／状态生命周期、不可由现有所有者承载的独立公共接口，或必须独立交付和验证的跨模块业务结果时才继续拆分。搜索、筛选、校验、删除保护、测试文件、文档和页面控件等功能名称不能单独构成拆分依据；它们归入拥有相关数据和业务规则的单元。共享存储、应用装配只有在拥有独立跨模块职责时才能成为单元，否则作为业务所有者的交付文件分配。规划器返回前合并数据所有者相同、接口重叠或能在同一生命周期内完成的候选单元，并在 scope 中说明保留拆分的边界依据。逐单元设计和评审不得重新扩大计划职责或产生第二数据所有者；发现重复所有权、功能名拆分或无独立边界时必须 revise，在当前单元内通过委托既有所有者收敛。

共享基础与最终装配仍须有明确所有者。程序校验标识、模块归属、唯一文件所有权、产品内路径、测试命名、依赖存在和无环；同一模块内，验收标准显式引用的同一个公共操作只能归一个单元，避免两个实现同时拥有 `remove()` 等行为。其他无效计划反馈具体字段、冲突模块／单元和允许的修正方式，要求保留正确部分，仅纠正失败项，不回传整份旧响应。现有当前计划校验失败时保留版本文件并生成下一版，不在逐单元设计中反复修补错误所有权。缺完整产品入口、重复归属或设计不一致时阻止推进，不擅自猜补业务规则、路径或验收。计划不接受自由命令，程序从 test_files 构造 Node 命令。

产品审批后的用户澄清是后续设计的正式输入。设计门径缓存除产品和架构文档哈希外，同时绑定审批后澄清消息哈希；新增回答使旧 clarify 决定失效。架构／Dev Design 的 Draft、Review 和正式化都接收这些澄清，最新明确回答覆盖正式上游文档中残留的「待确认」旧表述，避免 Planner 已知而 Author 未知。只传审批后的增量回答，不重复携带已经固化进 `product.md` 的初始需求和早期问答。

任务生成目录约定：`docs/dev-design/vN/shared-contract*.md` 保存共享契约及候选，`docs/dev-design/vN/{unit_id}*.md` 保存单元设计及修订候选，评审 JSON 与文件一起保存。`docs/dev-design.md` 和 `docs/dev-design-vN.md` 仅为计划、共享契约与逐单元设计路径／哈希索引，不拼接全文，供原有 API／Planner 读取。共享契约明确数据所有权、公共接口输入输出、错误语义、不变量和跨模块协作；每份单元设计引用契约并定义当前功能内部接口、数据、状态、关键流程、失败处理、正常／边界及错误恢复测试。先评审共享契约，再按依赖顺序评审逐单元设计；不允许单元重定义其他模块接口。独立只读 Reviewer 返回 ready、revise 或 clarify 与 issues；ready 才正式化，最多生成五次候选，clarify 仅用于已批准产品需求仍缺少用户业务决定。内部接口冲突按「已批准需求、开发计划中的单元验收与文件所有权、共享契约、已正式化依赖设计」的顺序裁决；共享契约或依赖设计越界增加了属于其他计划单元的接口时，该越界段落不取得所有权，由真正所有者在当前设计中明确最终出口。Reviewer 若把这些内部文本的取舍作为问题交给用户，程序将其规范化为 revise。后续候选必须保持依赖单元在其计划职责内的接口，以当前单元内部委托、适配或收窄重复实现来消解责任冲突，不能要求回改依赖设计；内部职责冲突不得转交用户。Reviewer 输出必须是简短完整 JSON，revise 最多列三项当前阻塞；JSON 截断或协议字段非法时在同一候选上有界重试一次，不生成新候选、不直接终止整个任务。不修改已确认业务范围。

单份 Dev Design 候选正文不超过 5000 个字符，只保留实施所需契约和验收映射。工具参数截断或非法时，下一次逻辑调用显式收到协议错误与压缩指令，不能原样重试。

有计划的任务不跳过逐单元 Dev Design。单元设计上下文含正式需求、共享契约、当前单元、直接依赖接口与计划摘要，不携带全部其他单元设计。发展计划与正式输入哈希不一致时必须回设计阶段，不能按文件已存在复用。

Develop 按拓扑顺序执行每个单元：开发当前 implementation_files 和 test_files → 程序检查文件齐备及至少一条测试被实际执行 → 程序执行当前与已完成单元测试 → 失败结果反馈当前开发单元 → 修复并重新测试。开发模型只提供 read、write 与历史查询，程序负责测试；写入限制为当前单元声明文件，依赖文件只读。上下文每调用刷新当前单元与依赖范围文件内容，近期完整工具已携带的同版本内容不重复；不加载整份产品代码或所有单元设计。测试反馈含命令、实际输出、期望依据、失败单元及执行前后文件哈希，无法建立测试环境同样不算通过；退出 0 但零测试、skip、todo 或执行中代码变化均不得通过。最多初次开发加两次修复，共用当前 StepRun 的逻辑模型调用上限，不为每个单元重置预算；重试仍无变化或预算耗尽时失败。设计缺口等待用户，不能削弱验收条件或越权修改依赖；模块接口变更须回设计。

`evidence/development-progress.json` 保存计划／需求／契约／单元设计哈希、单元状态、测试报告引用和所验证文件哈希；`evidence/units/{unit_id}-attempt-N.json` 保存每次真实测试结果。通过且所有依据／文件哈希仍匹配才可恢复跳过；失败及修复中的单元重启后先重测已有文件，再反馈最新失败，不能把历史成功套到新版本。历史失败和完整 Trace 保留。各单元全部通过后才形成实现血缘并进入原 test 全量集成测试，之后仍须 HTTP 启动、真实浏览器完整流程及人工验收。全局失败返修时重新检查单元与整体失败证据，不按旧通过状态直接略过；正常／边界测试覆盖同一功能行为，而不是仅依赖实现自称完成。

现有已经采用单份 Dev Design 或明确跳过设计的任务保留已有执行入口，不批量转换或续跑。新架构生成开发计划，多模块计划不得跳过设计；小任务经原门径明确跳过设计时保持原流程。正式限制仅将「强制单模块」改为「按确认架构拆分模块／功能」；数据存储、产品依赖、Provider 路由、100 次 Step 预算和人工验收边界不因本次修改放宽。

### 9.4 develop

2026-09-17 用户确认的通用入口契约：固定必需文件仅为 `product/index.html`、`product/verify_product.py` 和 `product/implementation.md`。JS、CSS 路径服从正式设计，不要求根目录 app.js 或 styles.css；程序解析 index.html 的本地 script src 和 stylesheet href，校验引用文件存在且位于产品目录，忽略 query 与 fragment。模块内部依赖由 Node 和真实浏览器验证，不静态猜测 JavaScript import。至少提供一个 `*.test.js`、`*.test.cjs` 或 `*.test.mjs` 测试文件（可在子目录），所有 Node 验证统一执行 `node --test` 自动发现。开发须完成设计规定的全部文件后主动结束，不能因几个入口文件齐全而提前停止工具循环。文件齐全恢复必须已有匹配当前设计的实现血缘。开发／返修每轮快照包含实际全部产品文件，新增文件也纳入变更判断；需求变更仍需实现和测试均产生实际修改。此更新不改变正式单模块、禁止数据存储、Provider 路由及预算约束。

v2.2 将已有产品的所有不通过验收反馈统一交给 Next Action Planner，不再先调用独立分类模型。程序读取并提供正式需求、架构、Dev Design、最近失败报告及当前产品文件清单。正式文档和用户明确变更已足以判断需求或设计影响时，Planner 可直接提议对应更新；要判断实现缺陷，必须先从清单选择相关代码文件，由程序校验并实际读取。同一个 Planner 也可继续调查，最多读取三个不同文件，或只提出一个澄清问题。程序将行动映射到原有阶段，并核对置信度、需求变更契约和解释一致性。`inspect` 不能重复无效读取，候选文档仍须用户审批，模型不能自行改变阶段状态。正式文档缺失或反馈歧义时只能澄清。现有分类字段由程序从行动导出，供下游版本返工兼容；此调查与下面 Develop 返修是独立行动，返修模型仍按原规则接收上下文。新建任务仍沿用原始入口，不新增数据库表。

v2.2 的下一小步只接管分类为 `implementation_defect` 的 Bug 闭环。每次 Worker 准备执行当前行动时，Planner 接收正式文档、验收分类、最近 StepRun 的真实结果、失败报告、代码文件哈希和剩余预算，从程序计算的可选集合中提议一个行动。`develop` 可检查证据、澄清或修改；修改后在 `test` 可继续检查或运行正式测试，必须先取得测试结果，不能在旧失败报告上重复改代码；测试失败再按 v2.1 预算返回修改。测试通过才能启动，健康检查通过才能浏览器验证，浏览器验证通过才能提出 `finish`。程序校验行动、文件清单、重复读取和最多三次额外调查；所有行动及结果记录在现有 StepRun／Trace 中，恢复时以数据库状态和实际文件为准，不新增表。测试／启动／浏览器失败仍按 v2.1 返修预算处理；`finish` 只提交人工验收，用户批准后任务才 `succeeded`。其他任务继续现有七阶段流程。

v2.2 将这条行动闭环扩展到已有产品的非 Bug 变更。已验收任务可提交 `change_request`（非空 `feedback`），在同一 Task 中保存用户请求并进入统一验收 Planner；新建任务入口仍独立。需求更新只生成候选，须用户批准后才替换正式 `product.md`。批准后，架构阶段 Planner 根据新旧需求差异提议 `update_architecture` 或 `update_dev_design`（表示架构经证据核对可复用）；Dev Design 阶段提议 `update_dev_design` 或 `modify_code`（表示 Dev Design 可复用）。若验收反馈明确判定该阶段缺陷，程序不允许复用该阶段。复用也保存正式版本与影响判断，不跳过血缘记录。到开发阶段后，已有产品的所有已确认变更均进入动态检查／修改／测试／启动／验证／`finish` 行动；即使设计文本未变化，非 Bug 变更仍须实际更新受影响代码或测试，其中新增小功能须同时更新代码和测试，且继续经真实浏览器验证和人工验收。无新表；新建任务继续原七阶段流水线作为回归。

v2.2 新建任务在产品 Candidate 获批准后也由 Next Action Planner 判断设计门径。程序先提供正式产品需求、项目固定约束和当前已存在的正式设计，Planner 在架构节点只能选 `update_architecture`、`update_dev_design`（跳过架构）、`modify_code`（两份设计均不必要）或 `clarify`；在 Dev Design 节点只能选 `update_dev_design`、`modify_code`（跳过 Dev Design）或 `clarify`。判断标准是是否仍有模块边界、接口、数据、状态、关键流程或失败处理等必须在编码前明确的决定，而不是软件名称或描述长短。跳过必须说明正式需求中已确认的具体依据、剩余关键决定为空且置信度至少 0.7；证据不足就澄清，不由模型补用户未确认的业务规则。程序保存判断、输入文档哈希和跳过原因到任务工作区 Trace／evidence，不创建空的架构或 Dev Design 文件；开发从已批准需求、现存设计及项目固定实现约束构造实现依据并记录来源。跳过设计不跳过需求审批、代码测试、HTTP／浏览器验证和人工验收。后续验收反馈可使用正式需求与保存的跳过依据继续规划，若新问题表明需要设计，再生成缺失文档；原有已确认文档和历史版本保留。无数据库 schema 变更。

`docs/product.md` 已由程序在用户批准后原子复制为正式文档，即使正文保留「候选版」标题也不改变审批状态。Worker 用本地 HTTP 服务启动生成软件并执行健康检查是项目固定验证机制，不代表生成产品拥有外部接口或主动发起网络请求；Planner 不得把这两项已确定机制当成需要用户再次批准的产品选择。

1. `author_agent` 接收 Dev Design、当前产品目录和必要上下文，先生成实现计划。
2. 模型通过 `write` 顺序创建或覆盖代码文件，程序逐次校验并返回 ToolResult。
3. 模型通过 `exec` 运行代码或测试；错误信息回传模型后继续修复。
4. 模型不再提出文件或命令操作时，核对实现是否符合 Dev Design。
5. 符合后生成实现文档；程序校验代码文件和实现文档后进入 `test`。
6. 从 `test`、`start_product` 或 `verify_product` 返回的返修不得因实际产品文件已存在而跳过。程序按最近失败 Step 选择证据：`test` 使用 `test-report.md`，`verify_product` 使用 `verification-report.md`，`start_product` 使用失败 StepRun 的错误信息；同时提供正式 Dev Design、文件路径和哈希，不预载产品源码。返修提供责任范围内的 `read`、`write`、`replace`，不提供原始历史详情，必须实际修改至少一个产品文件。
7. 同一失败证据最多允许两次模型调用。返修模型结束后若实际产品文件的内容哈希均未变化，程序写入 `repair_no_change` Trace 并立即以 `repair_made_no_changes` 失败，不再用相同证据纠正。模型文本中的“已修改”声明不作为修改证据，唯一依据是工具执行后文件内容哈希变化。
8. 文件发生变化后立即由系统复跑导致返修的验证：来源为 `test` 时运行 Node 测试，来源为 `verify_product` 时使用当前 `result_url` 和 Worker 自身受控 Python 运行 Playwright 脚本。模型不得自行查找、安装或切换 Python／Playwright 环境。只有验证产生新失败输出时才允许第二轮两次调用；第二轮仍失败时以 `repair_validation_failed` 终止。
9. 同一个完全相同的工具与参数最多连续实际执行两次，第三次由程序返回 `repeated_tool_action`；返修阶段自上次成功 `write` 后最多允许五次非写工具动作，超出后返回 `repair_tool_loop_no_write`。两类阻止均写入 `tool_guard` Trace并作为 ToolResult 反馈模型，不伪装成工具成功。
10. 上游产品、架构或 Dev Design 版本发生变化时，即使 `repair_round=0` 且入口校验通过，也必须执行影响判断；当前实现没有声明基于最新 Dev Design 时不得走“文件齐全”恢复捷径。`revise` 必须把差异、旧设计、新设计和现有代码交给 DeepSeek，并至少更新与差异对应的代码或测试。

当前独立预算固定为：单 Step 最多 100 次逻辑模型调用；一次 Provider 请求最多 3 次传输尝试；一个任务最多 3 轮跨阶段返修；一份失败证据最多 2 次模型调用，一次返修最多两份连续验证证据、共 4 次调用；相同工具动作最多连续实际执行 2 次；返修阶段成功写入之间最多 5 次诊断工具动作。各预算分别计数，Provider 降级不重复计算逻辑模型调用。

### 9.8 Transition Planner 输出

```json
{
  "action": "execute | revise | reuse | clarify",
  "reason": "判断理由",
  "affected_sections": ["受影响部分"],
  "preserved_sections": ["确认沿用部分"],
  "confidence": 0.0,
  "clarifying_question": null
}
```

程序拒绝未知动作、低置信度自动跳过、缺失输入版本和越权阶段。决策保存为 `evidence/{target}-transition-vN.json` 并写入 `transition_decision` Trace。

### 9.5 test

1. 测试角色读取产品文档、Dev Design 和实现文档，生成测试用例列表。
2. 程序在最小隔离范围内依次执行用例并保存结果。
3. 普通功能失败不阻止其他互不依赖的用例；依赖已失败前置能力的用例跳过并记录原因。
4. 软件无法启动或测试环境无法建立时，立即停止本轮测试。
5. 全部结果写入测试报告。
6. 测试通过则进入 `start_product`；失败则在返修限制内进入 `develop`，否则任务失败。

### 9.6 start_product

1. 动态选择空闲本地端口。
2. 通过 Python 静态 HTTP 服务启动 `product/`。
3. 记录端口、PID、启动命令、产品目录和访问地址。
4. 执行 HTTP 健康检查；成功后进入 `verify_product`，失败则按返修规则处理。

### 9.7 verify_product

Context 第一阶段优化：正式需求在 input 中只传一次，context 用来源与内容哈希标识；成对问答保持完整，仅额外携带未配对且未作为 input 的用户请求。无旧 Dev Design 时不生成全文式差异；Planner 的 input 已为差异时不在 context 重复差异。开发／返修附带文档来源、当前轮开始时的文件哈希和失败证据归属。历史报告未记录验证时文件哈希的，明确标为未知，不用当前文件推定历史版本。本阶段不压缩工具历史，不改变工具权限或执行预算。

验证脚本读取命令行传入的当前产品 URL，不自行启动 HTTP 服务或绑定固定端口。返修纠正每轮刷新实际文件内容；受控复验失败后，最新真实输出持续保留，不能被最初失败报告覆盖。最后未写入且此前复验失败时，终止原因保留 `repair_made_no_changes:latest_validation_failed`，具体结果见返修 Trace。

1. 使用 Python Playwright 在真实浏览器环境验证加、减、乘、除和异常输入。
2. 使用 JavaScript 单元测试验证计算逻辑。
3. 验证通过后生成或更新 README，写入运行方式和访问地址。
4. 程序校验 README 和验证证据后进入 `waiting_acceptance`。
5. 验证失败则保存证据，并按返修规则进入 `develop` 或 `failed`。

## 9.1 提示词版本与调用身份

素材管理全链路的开发单元规划、单元设计生成、独立设计评审、集成失败归因和单元开发提示词由根目录 `prompts/registry.json` 选择激活版本，正文保存在 `prompts/<name>/vN.md`。已参与测试的版本文件不可覆盖；调整正文必须新增版本文件并更新注册表中的激活版本及 SHA-256。运行时在模型调用前校验模板哈希，文件缺失、变量不匹配或哈希不一致时停止调用。

动态值只允许通过模板中显式的 `{{variable}}` 渲染。每条 `model_request` Trace 的 metadata 记录 `prompt_name`、`prompt_version`、`prompt_template_sha256`、`prompt_rendered_sha256` 和 `runtime_context_sha256`。模板哈希用于比较提示词版本，渲染哈希用于确认实际指令，运行上下文哈希用于区分相同提示词在不同任务输入下的调用。尚未迁移的旧调用统一标记为 `legacy-inline / unversioned`，不得据此宣称完成全流程提示词对比。

## 10．异常恢复

### 10.1 模型调用期间退出

Worker 使用已持久化的 instructions、input、context 和 tools 重新调用模型。重新调用仍计入当前 Step 的 100 次限制；尚未持久化的模型结果不作为恢复依据。

### 10.2 文件写入期间退出

重启后使用已保存的 ToolCall 检查目标文件。内容与预期一致时补记成功；否则按相同参数重新原子写入，不能重新调用模型生成另一份内容后覆盖。

### 10.3 命令执行期间退出

- 普通命令重新执行。
- 已记录后台进程仍存在且 PID、命令和产品目录匹配时，停止该进程后重新启动。
- 已记录进程不存在且端口空闲时重新启动。
- 已记录进程不存在但端口由未知进程占用时，不停止未知进程，当前 Step 以 `port_conflict` 失败。

### 10.4 Event 与 Step 恢复

- Event 依靠数据库事务保持 `pending` 或完整转为 `consumed`，不恢复中间态。
- `running` StepRun 根据 `checkpoint_path` 和 `last_completed_action_index` 从最近一次成功 Action 继续。
- 无法读取或验证检查点时，不猜测执行进度，将 Step 和 Task 标记为 `failed` 并保存原因。

## 11．限制与完成判断

### 11.1 人工验收问题分类与路由

- `acceptance_result.approved=false` 时，前端只提交用户原始 `feedback`，不要求用户选择问题类型。
- Worker 使用 Kimi，输入当前 `product.md`、`architecture.md`、`dev-design.md`、产品文件清单、最近验证报告和用户反馈。
- 模型必须只返回 JSON：`classification`、`target_step`、`reason`、`evidence`、`changes`、`confidence`、`clarifying_question`。`changes` 中每项包含 `current_behavior`、`expected_behavior` 和非空 `acceptance_examples`。
- `classification` 仅允许 `requirement_change`、`architecture_defect`、`dev_design_defect`、`implementation_defect`、`unclear`；目标 Step 由程序固定映射，忽略模型提供的越权目标。
- `requirement_change` 必须至少有一条合法变更契约；模型无法从省略主语或冲突表述中区分现状与期望时按 `unclear` 处理并询问用户。
- 初步分类必须逐条处理编号意见，并由第二次无工具 Kimi 调用返回 `consistent`、`contradictions`、`clarifying_question`。若“作为问题提交”与推导出的期望行为不自洽、任一条意见方向存在两种合理解释，或总体路由没有选择所有条目中的最早失效阶段，程序强制改为 `unclear`。
- 每个验收 Event 创建独立的 `verify_product` StepRun 和最多 100 次模型调用预算；同一 Event 因 Worker 恢复时可复用该 Run，不得跨多个验收意见累计并耗尽旧验证 Step 的预算。
- `conversation-turns.json` 以问答为条目：`turn_id`、`question`、`answer`、`status`、`step_run_id`、`actions`。只有成对问答进入产品门径上下文；未回答问题保留为 `open`。
- `artifacts.json` 以成功写入为条目：`tool_call_id`、`requested_path`、`resolved_path`、`name`、`operation`、`bytes_written`、`sha256`、`step_run_id`、`turn_id`。工具返回成功且文件真实存在后才记录。
- JSON 无法解析、证据文件不存在、反馈为空或置信度不足时按 `unclear` 处理，不猜测路由。

固定路由如下：

| 分类 | 目标状态／阶段 | 行为 |
| --- | --- | --- |
| `requirement_change` | `running / product_docs` | Kimi 基于正式需求和反馈生成新版本产品候选，等待用户批准后重跑下游阶段 |
| `architecture_defect` | `running / architecture_docs` | Kimi 生成新版本架构候选、评审和正式文档，再重跑下游阶段 |
| `dev_design_defect` | `running / dev_design` | Kimi 生成新版本 Dev Design 候选、评审和正式文档，再进入开发 |
| `implementation_defect` | `running / develop` | DeepSeek 在返修上下文中同时获得原始反馈、分类依据、正式设计、现有代码和测试，先补回归覆盖再修实现 |
| `unclear` | `waiting_user / verify_product` | 保存澄清问题，等待用户补充后重新分类，不运行旧测试冒充问题已处理 |

文档修订规则：

- `product_docs` 第 N 次 attempt 写 `product-vN-draft.md`，批准后原子覆盖 `product.md`。
- `architecture_docs` 和 `dev_design` 的返工 attempt 写带版本号的候选与评审文件；正式文件允许在返工时覆盖，首轮仍禁止覆盖。
- 下游已有正式文件不能作为返工捷径。只有首轮且文件已由同一 attempt 完成时才允许恢复式跳过。
- 分类结果写入 `evidence/acceptance-triage-{event_id}.json`，并通过 `acceptance_triage` Trace 展示完整输入、输出和程序最终路由。
- Product Draft、Review 和 Candidate 都接收同一份变更契约；Candidate 完成后 Kimi 只读返回逐条 `covered` 判断，结果写入 `evidence/product-vN-change-coverage.json`。存在未覆盖项时程序以 `product_change_coverage_failed` 阻止进入审批。

- 单个 Step 最多调用模型 100 次，超过后 Task 进入 `failed`。
- 测试、启动或真实验证失败后累计最多返回开发阶段 3 轮，超过后 Task 进入 `failed`。
- 单条命令最长 60 秒，命令输出及单次读取最多保留 100 KB。
- 生成软件固定为原生 HTML、CSS、JavaScript；不允许模型更换产品技术栈。
- 自动测试和真实浏览器验证通过后只能进入 `waiting_acceptance`；用户明确验收通过后才能进入 `succeeded`。
- Fake 或模型自述不能替代文件检查、命令结果、HTTP 健康检查、Playwright 验证及用户验收。
