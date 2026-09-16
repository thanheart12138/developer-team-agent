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

详情 JSON 至少包含 `type`、`status`、`title`、`summary`、`payload` 和时间信息。写入顺序为：计算下一个任务序号、敏感字段过滤、原子创建详情文件、创建 TraceRecord、提交事务。

新增两类展示事件：`model_stream_delta` 保存一次 Provider 文本增量及 `request_id`、顺序号；`artifact` 保存成功写入文件的工作区相对路径、文件名、工具调用 ID 和 SHA-256。模型请求与响应 Trace 的 metadata 都保存同一个 `request_id`，前端据此把流式片段、最终回答和原始返回关联为一次调用。

任务页每 750ms 增量查询消息与 Trace。左栏按 `created_at` 合并消息和 Trace 摘要，不展示 `model_stream_delta` 独立卡片，而是把同一 `request_id` 的片段拼到对应模型请求下方；收到最终响应后以正式 assistant 消息为准。右栏按所选类型分别展示模型输入、模型原始返回、工具名称／参数／返回值或文件内容，嵌套对象使用有标签的层级视图，不以 JSON dump 作为默认阅读方式。

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

流程与架构文档相同。返工输入包含新旧产品、产品差异、新旧架构、架构差异和旧 Dev Design；先判断 `reuse`、`revise` 或 `clarify`，需要修改时以旧 Dev Design 为基线进行局部修订。当前有效副本为 `dev-design.md`，历史正式版本保存为 `dev-design-vN.md`。输出额外包含是否需要模块划分及划分结果；v1 固定为单模块，不执行模块拆分或并行开发。

### 9.4 develop

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
6. 从 `test`、`start_product` 或 `verify_product` 返回的返修不得因六个必需文件已存在而跳过。程序按最近失败 Step 选择证据：`test` 使用 `test-report.md`，`verify_product` 使用 `verification-report.md`，`start_product` 使用失败 StepRun 的错误信息；同时提供正式 Dev Design 和全部当前产品文件内容。返修模型不提供 `read`，只提供 `write` 与 `exec`，必须直接判断是实现错误、测试错误或两者兼有，实际修改至少一个产品文件并自行运行相关测试。
7. 返修模型结束后若六个必需文件的内容哈希均未变化，程序写入 `repair_no_change` Trace，并把“本轮没有实际文件变化”、失败来源、完整失败报告及文件哈希反馈给模型进行纠正。同一 Develop StepRun 最多追加两次无变化纠正；任一次产生实际变化即继续测试，连续三次无变化才以 `repair_made_no_changes` 失败。模型文本中的“已修改”声明不作为修改证据，唯一依据是工具执行后文件内容哈希变化。
8. 文件发生变化后还必须由系统复跑导致返修的验证：来源为 `test` 时运行 Node 测试，来源为 `verify_product` 时使用当前 `result_url` 和 Worker 自身受控 Python 运行 Playwright 脚本。模型不得自行查找、安装或切换 Python／Playwright 环境。未通过时把本次真实输出反馈模型继续纠正，不能仅凭无关文件变化进入下一阶段；同一 Develop StepRun 连续三次修改后验证仍失败时以 `repair_validation_failed` 终止。
9. 同一个完全相同的工具与参数最多连续实际执行两次，第三次由程序返回 `repeated_tool_action`；返修阶段自上次成功 `write` 后最多允许五次非写工具动作，超出后返回 `repair_tool_loop_no_write`。两类阻止均写入 `tool_guard` Trace并作为 ToolResult 反馈模型，不伪装成工具成功。
10. 上游产品、架构或 Dev Design 版本发生变化时，即使 `repair_round=0` 且六个文件存在，也必须执行影响判断；当前实现没有声明基于最新 Dev Design 时不得走“文件齐全”恢复捷径。`revise` 必须把差异、旧设计、新设计和现有代码交给 DeepSeek，并至少更新与差异对应的代码或测试。

v2.1 独立预算固定为：单 Step 最多 100 次逻辑模型调用；一次 Provider 请求最多 3 次传输尝试；一个任务最多 3 轮跨阶段返修；一次 Develop 返修最多 2 次无变化／验证失败纠正；相同工具动作最多连续实际执行 2 次；返修阶段成功写入之间最多 5 次诊断工具动作。各预算分别计数，Provider 降级不重复计算逻辑模型调用。

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

1. 使用 Python Playwright 在真实浏览器环境验证加、减、乘、除和异常输入。
2. 使用 JavaScript 单元测试验证计算逻辑。
3. 验证通过后生成或更新 README，写入运行方式和访问地址。
4. 程序校验 README 和验证证据后进入 `waiting_acceptance`。
5. 验证失败则保存证据，并按返修规则进入 `develop` 或 `failed`。

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
