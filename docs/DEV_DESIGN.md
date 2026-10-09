# 开发团队模拟器——Dev Design v2

## 2026-10-09 提交调查后确认的最小修正

真实对照第7、12轮接力均 recent_changes 为空，因修改与自测分属工具批次；模型反复怀疑修改、测试先后和「前一个会话」。修正接力修改摘要为上一有效边界之后到当前完整批次结束的成功修改，不仅当前自测批次；保留可核对调用ID与当前诊断事实。已知旧边界不完整时不猜测或切断协议。对新返修明确逻辑任务连续、独立模型上下文不是重开任务，当前版本通过由完整产品哈希及真实命令证据判定，不因接力失效。普通历史成功不能替代当前证据的提示应与此区分。

必要新调查、回归测试及继续修改保持允许；不修正未覆盖源码范围为伪全文、不自动推断计划完成、不自动提交。计划状态更新不是交接前置条件；若模型确需更新，可按现有steps／reason工具契约与提交同批，提交仍必须最后。本轮只机制及原Trace离线验证，不追加真实HTTP、不预先承诺降低真实请求数。

## 2026-10-09 用户确认的自测成本修正

依据素材笔记检索真实实验与用户确认，仅新 repair-v1 连续返修执行会话改变自测返回及提示，不改旧卡、独立验证或明确提交门禁。完整自测结果保留 Trace／检查点；模型首次收到及后续续传的自测工具结果使用同一确定性摘要，包含命令、passed、版本、测试计数、退出／超时状态、失败详情及可查询原日志的模型调用引用。成功结果不附全量 TAP，失败详情有界，截断明确标注；思考和工具调用配对完整保留，不修改原始审计。

同一全产品文件集合与内容版本已有真实通过自测时，run_unit_tests 复用该证据并明确 reused；不再次执行命令。失败证据、文件修改／新增／缺失、测试或命令变化不能复用。独立流水线仍重新测试冻结提交版本，不复用开发自测。跨阶段验证失败后的原恢复边界保持，不能凭旧通过结果跳过返修。

当前版本已通过且模型判断原缺陷修复、没有未完成修改时，明确提示 submit_unit_for_test，并告知程序负责后续浏览器及目标审查；仍允许必要阅读和继续修改，不自动提交、不强行结束。修改使通过证据失效。验证以日志可追溯、缓存失效、失败诊断可读、原协议完整及显式提交为准；本次不追加真实模型请求，不能把离线字节缩减称为真实 Token 收益。

## 2026-10-09 搜索与上下文当前状态

2026-10-09 第三批已实现及验证：新主会话增加授权范围字面搜索、50 条分页与版本校验、默认 200 行读取、实际可见范围去重及稳定完整批次接力。全套 399 项通过后再完成两项读取门禁修正，最终相关 53 项通过；固定模型驱动真实 Docker／HTTP／Chromium 合成链路到待验收。离线同视图请求字节 21,790→12,391，不是实测 Token 收益。真实模型新架构返修仍未验证。详见 [第三批验证](evidence/repair-search-context-validation-20261009.md) 。


## 2026-10-09 第三批搜索与有效上下文实施约定

按用户已确认第三批设计实施。仅新连续返修会话增加字面文本 search，搜索当前产品、批准文档及明确授权的失败证据，不接受 shell、regex 或宿主 glob。默认每页最多 50 条，片段及整体输出有界；续查携带游标与文件集合版本，版本变化拒绝沿用旧游标。二进制／非 UTF-8 文件明确跳过，不伪称没有匹配。

read 默认 200 行，显式范围可继续读取，单次沿用已有字节上限。检查点登记实际返回内容、哈希与完整行范围；截断／搜索片段不证明全文。只在当前请求仍包含同版本同范围正文时拒绝重复读，已省略、未覆盖或变化的正文允许恢复。

复用既有接力机制，不额外调用摘要模型。任务级接力记录按原 Event／history_key 稳定保存；仅在完整工具批次完成、实际修改后取得模型主动全量自测的当前版本结果时建立独立模型上下文。逻辑任务 session、原始协议检查点、Trace 与预算不删改；新上下文包含原目标、计划、决定、当前文件正文范围和适用结果，边界之后的思考与 tool 配对完整续传。不能在未完成批次或未知结果处截断；无有效边界依据时保持完整历史。

当前请求只保留最新适用失败引用和自测状态；完整失败及原始目标仍可只读查询。离线请求字节比较不冒充实测 Token 或稳定成功率，真实模型实验仍需独立范围与预算授权。

## 2026-10-09 连续会话当前状态

2026-10-09 第二批已实现：新返修直接进入任务级连续主会话，任务 product 范围写权限、计划／决定状态、成对回答、跨阶段协议恢复和测试 Diff 审查。全套 388 项通过，真实 Docker／Chrome 合成集成到待验收，执行及审查为固定响应；真实模型返修与成本收益未验证。详见 [第二批验证](evidence/repair-session-validation-20261009.md) 。下一批是受控搜索与有效上下文。


## 2026-10-09 连续返修会话第二批实施

按已确认返修设计实施：新 repair_request 直接保存原目标并进入 develop，主要会话不依赖旧卡片。`evidence/repair-session-<task_id>-<event_id>-checkpoint.json` 保存同尝试完整工具协议；runtime 的 session 保存固定 Provider／模型／提示词指纹、计划和成对决定。阶段 Run 继续审计，验证失败恢复原 session，不重置实际请求预算。恢复发现无结果的工具意图时停止，不推测或重放。

文件权限由已核对产品目录建立：可读批准 docs、当前产品和当前失败证据，可写该 product 的实现／测试及相关新增普通文件；拒绝链接、特殊文件、凭据与治理文件。全量自测固定 `node --test`，整个产品文件集合及字节变化使旧自测失效。保留 submit_unit_for_test 作为显式提交工具；提交必须为批次最后动作，不因测试通过自动交接。

新增 update_plan 和 request_decision 工具仅写程序状态。提问保存具体问题／影响／提议和产物版本；user_message 必须携带当前 decision_id 才能恢复同会话，回答作为事实保存，不自动修改正式设计或增加预算。涉及未更新正式设计的产品大改动仍暂停，模型无权自行批准。旧任务与旧事件路径保持。

## 2026-10-09 当前实现与运行状态

2026-10-09，Sandbox v1 真实隔离探针与合成集成通过，全套 376 项通过。profile 绑定当前源码、镜像、Docker 环境和原始证据，检查通过后新 repair-v1 入口可用；环境或证据变化则关闭。正式空闲 API／Worker 已加载，原任务、schema、产品和旧调用计数保持。真实模型返修未验证；第二批连续会话／任务范围写权限状态见当前实施记录。详见 [真实验证记录](evidence/sandbox-isolation-real-20261009.md) 。


## 2026-10-08 Sandbox 接口增量已确认

2026-10-09 实施核对：真实 Chromium sandbox 在 cap-drop ALL 下 chroot 失败，官方 profile 的 chroot 规则按初始 CAP_SYS_CHROOT 纳入。按已确认「最小浏览器必要 seccomp 权限」范围，仅将 chroot syscall 加入 namespace 沙箱规则，不增加 capabilities，不关闭 Chromium sandbox；2026-10-09 实际兼容及隔离回归通过。Linux capability 检查仍由内核执行，不能以允许 syscall 推导宿主 chroot 权限。

用户明确确认统一 sandbox 契约并授权实施，首版复用 Docker Runner。提供 `create`、`execute`、`inspect`、`stop`，仅可信程序调用，固定测试动作、冻结版本、宿主结果及未知副作用停止；不新增数据库表或宿主执行兜底。具体输入、结果、失败分类与验收见 [Sandbox 增量契约](SANDBOX_V1_AI_DRAFT.md) 。已接入新模式的固定命令与可信预览，真实探针及合成完整集成通过，入口仍以当前匹配 profile 为前提；真实模型集成未验证。

## 文档状态

- 版本：v2
- 状态：当前有效
- 确认日期：2026-09-10
- v2 确认日期：2026-09-11
- 依据：当前产品需求文档与 `docs/ARCHITECTURE.md`

### 2026-10-03 用户确认：Planner 跨阶段证据复用与具体纠错

用户在后续真实验证失败分析后回复「可以」，授权以下局部修正；覆盖下述精简规则中调查正文的恢复方式，其他路由、开发交接及真实验证门禁保持。

- 仍使用现有 `inspect`。在 test／start_product／verify_product 新 Run 中，可选择此前同事件已保存、当前文件版本仍一致的调查路径；程序从原 Trace 恢复完整正文，绝不再次调用文件 read。引用包含实际 Trace 路径、原 SHA、当前适用性及是否可恢复。每个 Run 的同版本路径最多调查一次；正文只随紧接的下一次决定提供，之后保留可恢复引用。
- 缓存正文必须与 Trace 的路径／SHA／当前文件 SHA 一致；缺失、损坏或过期证据不作为当前正文。文件变化后按原候选规则重新读取新版本。新读取与缓存恢复共同遵守原三次调查上限、十二次行动上限，缓存不扩权、不重置额度，也不视为已通过验证。
- 简单流程明确原反馈为最初验收目标，当前执行事实来自实际阶段、最近开发 Run 与测试／验证哈希。给出当前门禁任务和建议行动；只有正常程序版本门禁允许时才建议 finish，模型仍需选择行动，程序仍执行独立测试／目标审查及人工验收门禁。
- 非法决定最多纠正一次，返回具体字段、错误码与原因；包括 JSON 对象、action、reason、inspect path、非 inspect 的非空 path，以及澄清问题。非法路径若有当前有效的已存调查正文，纠错可直接恢复这份正文供模型重新判断，不执行该非法行动、不重复读取产品文件。仍非法则按原流程失败，不自动选行动或追加调用。
- 验证须覆盖跨阶段合法缓存恢复零重复 read、正文按需省略、改变／缺失／损坏版本拒绝复用、调查额度、具体路径纠错及仍非法时失败；同时核对原目标、已存 Trace 和 finish 版本门禁。真实模型收敛及完整 Token 收益另行有界验证，本次修复不自动续跑失败任务。

状态：已实现并完成机制验证。相关集合首次 96 通过／1 个新夹具失败，修正断言后单项通过；真实旧 Trace 零 HTTP／零 read 工具调用恢复核对通过，空闲 Worker 73713→27466，正式及隔离状态保持。未追加真实模型调用或续跑失败任务，收敛及完整成本仍未证明。详见 `docs/evidence/planner-evidence-reuse-validation-20261003.md`；历史失败及成本保留于 `docs/evidence/context-slimming-delivery-real-20261003.md`。

后续验证状态（2026-10-03 16：13，不改变设计）：用户已批准六次上限并开始真实续测，最后可见启动／测试通过及第三次目标复审开始；现在原断点及原平台临时目录缺失、旧服务未运行，最终目标闭合／finish／Token 未确认。前段零调用为修复阶段历史，不代表后续从未调用。当前只读恢复检查零新增 HTTP，先找备份、不重置预算、不伪造状态，详见 `docs/evidence/planner-evidence-reuse-interrupted-20261003.md`。

### 2026-10-02 用户授权：请求上下文瘦身

以下覆盖重复正文的传递方式，不改变原始证据、状态、预算或执行权限。

- `build_messages` 核对当前实际协议中存在相同自测结果、通过状态及测试版本后，上下文 `unit_self_test` 的结果正文改为该工具消息引用，状态及版本适用性继续提供；协议 assistant／tool、思考、参数和结果逐字保持。没有匹配协议消息时保留自测正文。
- 有 `repair_task` 的切片返修将旧 `unit_test_feedback.failure_report` 改为真实报告路径、哈希及版本适用性；该报告加入现有只读权限。最新 `unit_diagnostic` 保留实际错误定位和 actual／expected。完整目标及其原始报告原地保存；开发输入按目标保留原文、期望和复现，将历史验证报告／已过期核销说明改为目标账本引用，后续独立目标审查继续使用完整账本。
- Bug Planner 在 test／start_product／verify_product 只接收当前阶段、最近执行状态、当前测试／验证哈希适用性、未闭合目标 ID、文档和报告引用、调查引用、allowed_actions 及剩余额度。正式用户反馈只在 input 保留一份；不发送正式文档／报告全文，只在一次新 inspect 后提供该次读取内容。已批准文档纳入现有 inspect 候选，三次上限和只读职责保持；develop／分类／设计入口保持原上下文。
- 源码接力只对原先实际读过／完整写过的范围进行筛选。当前自测／诊断版本有效且通过时，接力最近修改文件；失败时另接力诊断实际提及的文件，非产品业务依据继续保留。诊断不适用或失败中无法识别文件时保留原全部已知范围。其他已知源码仅提供范围和可读取引用，不臆测未读正文，不因省略而拒绝必要补读；当前协议里的正文保持，纯读取阶段不增加接力边界。
- 离线验证来源为已保存真实请求和检查点，必须检查协议及原始目标保持、旧／当前版本区分、缺文件／失败自测仍拒绝提交、缺失正文可读取、需要时仍可 inspect，以及实际请求体积变化。字符数量不冒充实际 Token 或账单收益；真实返修续测另行确定范围与调用上限。

实施记录（2026-10-03 收尾）：以上已实现，首次相关集合 225 通过／2 个新夹具失败，修正夹具及失效报告引用后最终定向 11 项通过；39 个旧请求正文离线投影减少 36.03％，所有原协议及目标事实保持。新 Planner 状态／指令开销未包括在投影中，实际 Token／真实模型效果未验证。Worker 空闲重启 92087→73713，正式状态和生成产品保持，零新模型调用。详见 `docs/evidence/request-context-slimming-validation-20261002.md`。

前轮真实交接验证（2026-10-03）：相同旧断点、20 文件及正式设计 SHA 一致，DeepSeek thinking 十一 HTTP／474,035 Token 到真实自测／提交即停，86 项通过、十五提交文件版本保持；原目标、十一请求的实际思考／工具协议及报告引用核对通过。历史同交接位置总量少 30.16％，调用／读取及输出增加。当轮未执行新副本后续门禁，源待验收实例和正式 Worker 保持，详见 `docs/evidence/context-slimming-deepseek-real-20261003.md`。

后续门禁实测（2026-10-03）：用户批准最多六次 HTTP，沿新的交接副本零模型调用恢复，真实完整浏览器及全量 Node 102 项通过。实际四次 Kimi／22,857 Token，在 start_product 重复选择非法已读 inspect 路径后 failed；目标审查与 finish 未执行，不返修或追加调用。已确认调查正文只传一次后没有合法恢复入口，以及纠错没有给出具体非法 path；阶段事实表达、已存证据复用与字段级纠错为待批准建议，本设计未据失败自动修改。完整交付成本未证明，详见 `docs/evidence/context-slimming-delivery-real-20261003.md`。

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

Model Runtime 实现 DeepSeek、Kimi 与 OpenRouter 三个 Provider。Worker 创建 Runtime 时必须传入当前 Step，并按下表路由；OpenRouter 仅供脱离正式 Worker 流程的模型探针和调试调用，由 `SIMULATOR_MODEL_PROVIDER=openrouter` 选择，不改变固定阶段路由，也不同时调用多个 Provider。

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

DeepSeek 默认模型为 `deepseek-flash`，请求地址为 `SIMULATOR_DEEPSEEK_BASE_URL/chat/completions`。DeepSeek 使用 `thinking: {type: enabled}`；带工具的多轮请求须保存流式响应的完整 `reasoning_content`，并随对应 assistant 工具调用在后续请求中续传，同一次模型响应的多个工具调用归为一条 assistant 消息。当前执行循环的工具历史不得因摘要投影丢失思考续传所需的原始调用和结果；旧检查点缺失 `reasoning_content` 时只传已有执行证据，不编造思考内容。Kimi 使用 Kimi Code Key，默认模型为自动升级别名 `kimi-for-coding`，默认端点为 `https://api.kimi.com/coding/v1`，请求地址为 `SIMULATOR_KIMI_BASE_URL/chat/completions`。端点和模型 ID 可通过启动配置覆盖；真实调用前必须先通过 Kimi Code `/models` 核验当前可用模型。DeepSeek 与 Kimi 分别读取独立的、被 Git 忽略的密钥文件。认证头不进入 Trace。

OpenRouter 默认模型为 `openai/gpt-6-luna`、推理强度 `medium`，使用 `https://openrouter.ai/api/v1/chat/completions` 的流式 Chat Completions 与现有工具协议。请求体使用 `reasoning: {effort: medium}` 和 `stream_options: {include_usage: true}`，不传 DeepSeek／Kimi 专属字段。密钥从独立的 `SIMULATOR_OPENROUTER_API_KEY_FILE` 指定文件读取，默认 `secrets/openrouter_api_key`，认证头不进入 Trace。OpenRouter 优先读取当前进程的 `https_proxy`／`HTTPS_PROXY` 并显式传给 HTTPX，同时启用 `trust_env=True`；未设置 HTTPS 代理时保持直连且不读取其他环境代理，避免无关 SOCKS 配置要求额外依赖。DeepSeek 与 Kimi 继续使用 `trust_env=False`。未配置密钥时明确报错；真实调用必须设置请求次数与输出上限。

三个 Provider 共享 `ModelRequest`、`ModelResult`、消息历史和工具调用映射。Provider 各自构造请求 payload，禁止把某一 Provider 的专属字段无条件发送给另一 Provider。DeepSeek 与 OpenRouter 传输超时为 60 秒，Kimi 长文档传输超时为 180 秒；Kimi 单次最大输出为 8192 Token，防止无界长响应阻塞持久化。三个 Provider 仍遵循最多 3 次传输重试。Trace 的模型请求、响应和重试元数据必须包含实际 `provider` 与 `model`。

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

2026-09-24 用户确认的开发读取规则（当前有效）：完成任务优先，允许模型按需读取更多不同文件或新行范围；同一开发循环内，文件 SHA-256 未变且读取范围相同、内容已在本次上下文中的 `read` 不再执行，返回短错误和现有内容位置，并要求继续写入、测试或报告真实阻塞。文件变化后允许重新读取；大文件允许读取此前未读的行范围。规则依检查点中的成功读取在恢复后继续生效，不改变文件写入权限、自测／提交门禁或调用预算。真实任务完成度先于 Token 消耗评价，重复读取被拦截不等于任务通过。

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

骨架 `modules[].implementation_files` 与 `test_file` 必须逐字引用 `files` 的键，均包含 `product/` 前缀。校验失败时返回模块 id、声明路径和不匹配的文件键提示；程序不悄悄改写所有权或放宽文件边界，仍在原有有界纠正次数内让 Scaffolder 重新生成。

Slice Planner 接收骨架契约和剩余 todo，只能选择仍有未完成测试的业务模块或跨模块用户结果。Developer 必须在当前切片内实现业务代码并把对应 todo 改成真实断言；程序除检查进程退出码和测试数量外，还检查本切片测试文件不存在 todo／skip。Planner 只有在骨架 todo 全部清零、固定入口齐全且全部需求有真实测试证据时才能返回 complete。骨架只用于首轮新建且 `product/` 仍为空的任务；已有产品的架构返工保留当前实现并由后续切片增量修改，不覆盖代码。历史任务、已跳过架构任务和旧 `development-plan` 任务不自动转换。

### 9.3.2 AI 原生逐业务切片闭环（2026-09-19 用户确认）

2026-09-28 内部行为验收标准（用户确认试行）：产品审批界面及正式 `product.md` 不增加测试字段。新逐切片任务在首张卡前，使用正式产品需求生成 `docs/acceptance-standard.json`，条目包含程序分配的稳定 ID、产品原文连续引用、用户动作／条件及可观察结果；提取模型不能据此新增业务规则。程序校验原文引用、字段与产品哈希，独立审查模型对照全文检查漏项、合并项和曲解；内部纠正有界，失败不伪装为已覆盖。产品版本变化使旧标准失效。技术验证手段由后续设计和实现确定，不写回产品文档。

2026-09-28 局部纠错续订（用户确认试行）：首次提取仍对完整正式产品需求做一次独立审查；审查指出问题后保留候选清单，由纠错模型仅返回新增条目和按已有 ID 替换的条目。程序只合并这些改动，未涉及条目的内容与 ID 必须逐字保持，新增条目获新 ID；继续校验全部原文引用、字段、重复项及条目上限。随后独立模型针对前次问题、局部改动和对应产品原文复查，不在纠错轮次重新生成或重新审查整份清单。审查未通过时保存候选与反馈并在总次数上限内继续，耗尽则失败；只有复查通过才保存正式标准并进入切片。此机制仅保证已审查问题的闭合，不能把模型审查解释为用户验收。

Slice Planner 接收内部标准，每张新卡声明所覆盖的条目 ID；Developer 同时接收当前卡对应条目的原文和可观察结果。`complete` 前程序要求所有条目都被已通过切片引用；独立覆盖审查再对照标准、各卡验收与已生成的浏览器脚本，检查用户可见操作是否真的有端到端验证安排。发现缺口时给 Planner 具体反馈继续规划，不能把仓储方法测试作为页面编辑的完成证据。审查本身是模型判断，仍以真实测试结果和用户最终验收为准；不自动迁移已有逐切片任务，不改变数据库 schema 或现有调用预算。

架构阶段只固定模块边界、数据／状态所有者、公共接口、关键跨模块流程及需要用户决定的业务规则，不生成全部开发单元、文件所有权和逐单元 Dev Design。架构正式化后创建 `docs/delivery-plan.json`，绑定需求与架构哈希并声明 `workflow=slice-v1`；不预判切片总数。

Slice Planner 每次只返回 `implement`、`complete` 或 `clarify`。`implement` 必须生成一张结构化执行卡，包含目标、涉及的数据所有者、使用的公共接口、当前需要修改的实现文件和测试文件、可执行验收条件。程序校验路径、测试命名、字段完整性、切片标识和上限；测试、说明文档和验证脚本必须并入产生相应业务结果的切片，不能独立成片。`complete` 只在全部需求已由已通过切片覆盖、固定入口已规划且没有未完成卡片时有效。`clarify` 仅用于缺少会改变产品行为的用户决定。

Dev Design 阶段只生成第一张执行卡并写入 `docs/slices/`，`docs/dev-design.md` 为切片索引和恢复入口，不生成共享契约及全部单元长文档。Develop 对当前卡片实现、自测并由程序独立执行当前及此前切片测试；通过后把真实文件和测试结果交给 Planner，再决定下一张卡片。后续计划以当前代码、已通过验收和实际文件清单为依据。每张卡片使用同一 Step 的总模型调用预算，不按切片重置。

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
6. 从 `test`、`start_product` 或 `verify_product` 返回的返修不得因实际产品文件已存在而跳过。程序按最近失败 Step 选择证据：`test` 使用 `test-report.md`，`verify_product` 使用 `verification-report.md`，`start_product` 使用失败 StepRun 的错误信息；同时提供正式 Dev Design 和全部当前产品文件内容，按 9.0 刷新并去重。返修提供 `read`、`write`、`exec` 及三个历史查询工具，必须判断是实现错误、测试错误或两者兼有，实际修改至少一个产品文件并自行运行相关测试。
7. 返修模型结束后若实际产品文件的内容哈希均未变化，程序写入 `repair_no_change` Trace，并把“本轮没有实际文件变化”、失败来源、完整失败报告及文件哈希反馈给模型进行纠正。同一 Develop StepRun 最多追加两次无变化纠正；任一次产生实际变化即继续测试，连续三次无变化才以 `repair_made_no_changes` 失败。模型文本中的“已修改”声明不作为修改证据，唯一依据是工具执行后文件内容哈希变化。
8. 文件发生变化后还必须由系统复跑导致返修的验证：来源为 `test` 时运行 Node 测试，来源为 `verify_product` 时使用当前 `result_url` 和 Worker 自身受控 Python 运行 Playwright 脚本。模型不得自行查找、安装或切换 Python／Playwright 环境。未通过时把本次真实输出反馈模型继续纠正，不能仅凭无关文件变化进入下一阶段；同一 Develop StepRun 连续三次修改后验证仍失败时以 `repair_validation_failed` 终止。
9. 同一个完全相同的工具与参数最多连续实际执行两次，第三次由程序返回 `repeated_tool_action`；返修阶段自上次成功 `write` 后最多允许五次非写工具动作，超出后返回 `repair_tool_loop_no_write`。两类阻止均写入 `tool_guard` Trace并作为 ToolResult 反馈模型，不伪装成工具成功。
10. 上游产品、架构或 Dev Design 版本发生变化时，即使 `repair_round=0` 且入口校验通过，也必须执行影响判断；当前实现没有声明基于最新 Dev Design 时不得走“文件齐全”恢复捷径。`revise` 必须把差异、旧设计、新设计和现有代码交给 DeepSeek，并至少更新与差异对应的代码或测试。

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
   - 2026-10-02 用户确认：Worker 启动子进程时显式将标准库服务监听队列设为 128，避免默认队列 5 在模块并发建连时拒绝请求；仍使用 `http.server`、仅绑定 127.0.0.1，不改系统参数、产品代码、健康检查或浏览器验收标准。
3. 记录端口、PID、启动命令、产品目录和访问地址。
4. 执行 HTTP 健康检查；成功后进入 `verify_product`，失败则按返修规则处理。

### 9.7 verify_product

Context 第一阶段优化：正式需求在 input 中只传一次，context 用来源与内容哈希标识；成对问答保持完整，仅额外携带未配对且未作为 input 的用户请求。无旧 Dev Design 时不生成全文式差异；Planner 的 input 已为差异时不在 context 重复差异。开发／返修附带文档来源、当前轮开始时的文件哈希和失败证据归属。历史报告未记录验证时文件哈希的，明确标为未知，不用当前文件推定历史版本。本阶段不压缩工具历史，不改变工具权限或执行预算。

验证脚本读取命令行传入的当前产品 URL，不自行启动 HTTP 服务或绑定固定端口。返修纠正每轮刷新实际文件内容；受控复验失败后，最新真实输出持续保留，不能被最初失败报告覆盖。最后未写入且此前复验失败时，终止原因保留 `repair_made_no_changes:latest_validation_failed`，具体结果见返修 Trace。

在首次真实浏览器验证及返修后的受控复验前，程序只检查可确定的验证脚本契约错误：脚本自行创建 HTTP 服务、使用 `argparse` 却没有接收位置 URL 且没有直接读取 `sys.argv`，或把 `sorted(实际值)` 与顺序错误的固定字符串列表比较。发现时记录脚本问题与行号，阻止该次浏览器运行，并把明确反馈交给现有有界返修；不据此判定产品实现失败或伪造浏览器通过。浏览器脚本输出 `[skip]`（不区分大小写）时，即使退出码为零也不得通过。其他断言失败仍保留真实输出，由返修根据正式需求核对脚本与产品；程序不猜测任意断言的对错。

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

- 2026-10-02 用户确认真实返修反馈修复（当前有效，补充以下接力与诊断规则）：固定 Node 诊断摘要优先保留失败测试名、文件／行号、错误与断言、actual／expected，过滤成功及应用步骤流水，完整输出仍在原报告中按需读取，不通过增加日志正文解决定位缺失。上下文接力不再把 `evidence/slice-repair-diagnostic-*.json` 的正文当作当前代码知识刷新携带；保留已读报告引用并区分边界诊断与历史报告，以 `unit_diagnostic` 为当前结果依据，原始协议与审计不变。`read` 的工具说明明确局部读取必须同时填写 start_line／end_line，保持现有后端校验和完整读取语义。每轮请求提供本 Step 的实际逻辑调用上限、包含本次的已用次数及本次之后剩余次数；恢复与接力不重置，传输重试不算逻辑调用，明确本字段不是 HTTP 次数上限，不虚报外部实验的 HTTP 剩余额度。Developer 使用新不可变版本区分从零开发与返修字段，返修不要求不存在的 card／acceptance_standard_items，不调用未开放的重规划工具。仍允许继续必要修改，程序诊断不自动自测、结束或提交；本轮只本地验证，不追加真实调用。
- 2026-10-02 上下文接力恢复补充：同开发 Run、同责任卡与同原始失败沿用检查点中的返修循环 ID，不因完成动作数增长而新建循环；不同 Run、责任卡或失败仍隔离。接力边界必须核对该次响应的全部调用 ID 及结果，缺失时不重建。
- 2026-10-02 用户确认 DeepSeek 上下文接力（当前有效）：先只应用于已有产物切片返修。一次模型工具批次全部返回、文件实际变化且程序已取得绑定新版本的诊断后，开始新的消息上下文；读取阶段继续当前工具会话，不按任意 Token 阈值切断。原始检查点、思考、工具调用和结果、进展及调用预算完整保留，未完成工具批次不得作为边界；边界按 Run／循环记录，恢复继续使用相同边界，不重执行工具或补发旧思考。新上下文持续提供原始目标、返修任务、权限、当前版本、最新诊断、自测与提交状态和最近修改摘要，保留历史中实际读过或完整写过的文件范围，重叠范围合并后按当前版本刷新，超出既有单次读取上限时标明截断，不把缺失／过期／截断内容当作完整读取。已读内容作为文件上下文提供，未完成范围仍按需读取；不增加模型摘要调用。DeepSeek 新上下文不续接旧 assistant／tool 消息，当前会话内续接则原样保留完整 reasoning_content 和成对工具消息。已在协议工具消息中提供的结果不在 current_requested_data 重复提供，仅保留消息引用；原始请求证据不改。诊断不自动结束开发或提交，所有权、显式自测／提交和独立验收门禁不变。本轮只本地验证，无新付费调用。
- 2026-10-02 用户确认返修任务聚焦与修改后诊断（当前有效，补充下条入口诊断）：已有产物的切片返修只自动发送当前失败、当前系统执行契约、原始验收目标、既有读写权限和固定测试范围；完整旧卡保存为只读证据，业务验收与接口语义按需读取，内部验收标准保留只读引用，不每轮发送整张旧卡或要求重做已完成切片。每批模型工具动作执行完后刷新诊断，固定命令及完整文件版本未变则复用；每个开发 Run 按命令与版本分别留存报告，恢复或返回已测版本不重复测试。该批模型已主动自测且证据对应同版本时，复用其真实结果，不再运行相同诊断。文件修改后新的当前诊断优先于过期自测，旧证据仍保留并标明过期。程序诊断通过也不赋予提交资格、不限制模型继续修改、不自动结束；主动自测与显式提交、后续独立核验、文件所有权、thinking 设置和调用预算不变。本轮仅实现及本地验证，不新增付费调用。
- 2026-10-02 用户确认切片返修先诊断：已有产物进入切片返修时，程序先执行当前责任卡固定的 Node 测试，保存真实命令结果、前后文件版本和完整报告，再将失败位置与错误摘要交给模型。相同开发 Run、固定命令及完整文件版本一致时复用诊断，避免恢复后重复测试；缺文件、测试期间版本变化或修改后不可复用。诊断与原始验收目标、原集成报告同时保留，摘要提供完整证据的按需读取路径。程序诊断不是开发模型的自测，不授予提交资格、不触发通过后提交提醒、不自动结束开发；模型仍须完成必要修改、主动自测并显式提交，后续独立测试和原始目标核验不变。先应用于已有产物的切片返修，不对从零开发增加预先测试或扩大调用预算。

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
- 2026-09-30 用户确认原始验收目标独立闭合：实现缺陷的原始反馈、分类产生的期望行为与复现例子、当时验证报告保存在 `evidence/repair-objectives.json`，后续验证脚本错误只作为最新阻塞追加，不覆盖原始目标。逐切片和普通返修均接收未闭合目标。浏览器真实执行通过后，独立只读审查逐项核对原始目标与脚本中的实际操作／断言，引用必须逐字存在于实际执行脚本；缺项、审查失败或脚本／产品代码版本变化均不能复用关闭结果。审核与真实成功运行同时成立才记录闭合版本，仍需用户最终验收。未结构化的旧反馈保留原文，不臆造期望和复现；无法从原文核验时审查不得通过。此机制不生成独立回归脚本，语义审查仍可能出错，不声称程序可确定性证明浏览器操作覆盖。
- Fake 或模型自述不能替代文件检查、命令结果、HTTP 健康检查、Playwright 验证及用户验收。
- 2026-10-01 用户确认必要读取进展和当前返修任务整理：成功读取同一文件版本中尚未提供的实际行范围可重置连续无有效进展计数；失败／被拦截读取、重复范围、仅修改描述或同字节写入不算进展，计数仍按模型批次，四批提醒、八批停止和总调用预算保留。读取进展只证明获取信息，不代表开发完成或允许扩大文件权限。每轮提供当前任务焦点：原始目标引用、当前有效执行卡与系统职责、最近真实证据的版本适用性、缺文件／待自测／待提交／待独立目标核验；旧卡原文和批准业务验收保持，过时的服务托管描述明确被当前契约覆盖，不用文本替换猜测或改写业务规则。提示要求围绕当前失败完成一组必要修改后尽早自测，不通读所有文件。用户补充此前通过后反复阅读的历史，本轮保留已有通过后催促显式提交及版本保护，不实施第１项取消方案、不自动替模型结束或提交，不新增真实模型调用。
- 2026-10-01 用户授权排查并修复真实失败中的实现不一致：受控命令的子进程 PATH 优先使用 Worker 解释器所在目录，使 Node 再调用 Python 时沿用项目环境，不修改系统 PATH、不由模型安装或切换环境。`replace` 沿用已有文件写入所有权，普通单元／切片与返修均提供；摘要登记替换前后真实哈希，并作为最新写入和文件修改历史。局部读取摘要保留行范围，不将未截断的局部片段标为全文件已读。`run_unit_tests` 外层工具成功仅代表调用完成，摘要是否通过由真实 `passed` 决定，失败保留内部退出码、输出及实际自测范围的版本证据。切片正文只在 `context.card` 保留一份，输入引用该卡；原始目标、反馈及 DeepSeek 必需历史不删减。保持模型显式自测／提交和程序独立验证，不以读取停滞或测试通过自动结束模型工作。
- 2026-09-30 用户确认执行控制与旧验证契约对齐：`require_unit_submission=true` 的单元／切片流程不再叠加五次非写动作门禁，仍保留重复读取、相同动作、无进展提醒／停止、实际自测与提交版本校验及总调用预算；旧无显式交接流程保留五动作保护。Planner 和单元／切片执行请求显式携带当前验证契约：Worker 负责产品服务，verify_product.py 接受命令行当前位置 URL、不得自建服务、不得跳过浏览器。旧卡／测试中仅服务启动职责及日志文字匹配与当前契约冲突时，可在既有文件权限内修正这些系统执行要求，必须保留批准产品行为与真实浏览器操作／断言；不得借此修改业务范围、降低验收或自动改变旧任务状态。本轮只做定向机制验证，不新增真实调用。
- 2026-09-30 用户确认真实返修暴露的两项修正：有 `unit_file_scope` 的单元／切片开发及返修不再自动随每次请求附带范围内全部产品全文，只刷新文件清单与哈希，按需 `read` 获取内容；原始目标、失败反馈、读取结果及 DeepSeek 协议要求的工具历史继续保留。仅当前请求实际仍含相同版本、相同范围内容时阻止重复读取，内容已省略或文件已变化时允许读取。旧显式全文快照入口保持原行为。返修无写入门禁达到阈值后允许 `write` 和 `replace` 尝试恢复进展，失败替换不重置计数，相同动作限制和既有调用预算继续有效。本轮只做机制回归，不追加真实模型实验。
# 2026-10-04 验收返修补充规则

用户已授权实施：架构缺陷、设计缺陷与实现缺陷均保存原始验收目标，最终仍由实际浏览器执行和独立目标审查核销。逐切片项目收到设计返修时，保留旧卡与测试证据，为当前验收事件新增返修卡；同一事件恢复不重复建卡。规划上下文携带当前反馈和未核销目标；当前设计返修卡通过前不得宣布 complete，卡通过也不替代最终目标验证。验收调查大文件时使用有界分段读取，显式保留范围与截断状态，不将片段当全文，不重复读取同一范围。原调用上限不变，本次机制验证不追加真实模型调用。
# 2026-10-05 已确认返修增量：第一批

本节优先于旧返修固定步骤的 Planner 规则，依据已确认的 `REPAIR_DEV_DESIGN_V1_AI_DRAFT.md`；只对显式 `repair-v1` 尝试生效。旧任务不自动迁移。

- 新事件 `repair_request` 核对任务版本、原始反馈、完整产物及授权引用。真实入口检查当前本机隔离 profile，缺失或不匹配则返回 `repair_execution_isolation_pending`；不创建尝试、不调用模型、不修改旧任务。机制验证使用隔离夹具，不构成启用真实入口的证据。
- 程序记录 `evidence/repair-runtime-v1.json`，包含任务／事件身份、revision、阶段、授权快照及累计 HTTP 尝试预算。授权引用指向程序准备的 `evidence/repair-authorization-<id>.json`，必须明确 Provider、historical_attempts、total_limit、review_reserve 及外发范围；客户端不能直接提供额度。旧计数核对及真实授权写入仍由运行控制完成。
- 提交复用已有卡片写权限、自测和 `submit_unit_for_test`。程序核对自测版本、完整入口及当前需求，保存全产品文件清单（含新增／删除／非代码文件）、有效 docs 与授权哈希。每次提交采用独立序号文件，验证结果同提交绑定，禁止覆盖旧提交。
- 固定阶段为全量 `node --test`、托管静态服务、真实浏览器、独立原目标审查、待验收；不调用 Planner 决定这些动作。每阶段执行前保存 intent，前后核对冻结版本，结果先原子保存，再更新 Task 投影。未知副作用中断停止，不自动重放命令。
- 实现／测试／覆盖失败保存证据并回原有开发入口；第一批尚不承诺跨阶段连续会话。环境或验证器错误及版本冲突停止。待验收／验收核对 submission_id、任务版本、需求及产品版本；不得自动验收。
- Provider 实际发送前登记一次保守请求尝试，失败／重试都计数；执行不能消耗审查预留，独立审查可使用预留。`BudgetExceeded` 原样传播，不网络重试、降级或包装为传输错误。未启用模式不创建预算记录。
- 首批不扩大写权限、不增加 schema、依赖或真实模型预算。运行隔离和连续会话按后续批次实施。
# 2026-10-05 已确认 Docker 隔离增量

## 2026-10-09 已确认返修上下文契约 v2

### 2026-10-10 已确认授权内范围搜索

新返修会话的 search 增加可选 path，选择授权内一个文件或目录；省略时保持全域行为。拒绝绝对路径、父目录逃逸、链接及无授权文件的范围，不扩展读取权限。分页版本同时绑定查询、范围及范围内文件版本，变更范围或文件后拒绝旧游标。新提示词指导已知位置时使用范围；旧提示词与工具schema绑定保持，不迁移历史会话。本次机制回归和原请求离线投影，零付费调用，不将正文减少当真实Token收益。

### 2026-10-09 已确认取消新返修独立模型审查

新repair-v1尝试绑定validation_policy=tests_and_browser：显式提交后固定全量测试、启动与实际浏览器验证，通过后直接等待用户验收，不再调用模型原目标／覆盖审查。HTTP总上限及历史计数保持，新尝试审查预留为0；原授权文件不改。原始目标保持open到同提交／版本的用户批准事件，以user_acceptance注明关闭依据，测试通过不得冒充需求覆盖审查。旧尝试不迁移，保留原阶段／额度与历史审查契约；不自动续跑。模型提示词更新仅新尝试生效，保留此前绑定提示词可恢复。本次机制与真实本地浏览器夹具验证，不新增付费调用。

### 2026-10-09 已确认上下文成本修正

2026-10-09 用户确认定位后推进规则，仅新返修提示词使用：调查针对影响本次修复的具体未决问题；原因、批准接口和修改方案有依据且无相关未决问题时优先修改自测；无关已有疑点先记录，影响本次交付才继续调查；参数已确定的独立读取／修改尽量合批，有先后依赖时分批。必要调查和关键决定暂停保持，可选进度非前置，不增加次数门禁或自动提交。原v2和legacy会话按绑定提示词哈希恢复，不迁移旧记录。机制验证不替代真实行为／Token证据，不追加付费调用。

2026-10-09 真实对照后，用户确认撤回返修「仅携带修改文件」筛选。本段优先于下文该项历史规则：返修接力保留此前实际读过／写过的已知范围，刷新当前正文，沿用现有截断、权限和诊断报告引用保护，不默认补充未读全文；旧单元诊断筛选保持。准确自测去重继续保留。v2累计成功修改的每项operation明确记录原tool_name（write／replace）及当时description，调用ID与query_tool仍只用于追溯，不把查询工具写成修改操作，也不将模型描述当作程序验证结论。不生成模型调查结论、不强制新增计划调用、不修改旧检查点／绑定提示词、不自动提交。本次用已有两轮记录离线核对，不追加真实模型调用。

仅返修主会话接力使用经完整产品版本与命令核对的当前自测通过证据，优先携带边界以来修改文件的已知正文范围；其他已知范围保留按需引用，允许补读。过期、失败或缺失证据不据此缩减；旧单元诊断选择保持。

v2 请求中，同一自测结果已经由实际协议工具消息提供时，当前事实仅保留状态、版本和准确工具引用，省略重复结果与失败正文。同一模型调用和工具调用的失败摘要也改为引用；其他失败、缺少身份或无法核对的结果保持。接力后没有对应工具正文时仍提供当前事实的完整自测摘要与失败详情。原思考、工具协议、检查点与审计不修改，不自动提交，不减少独立验证。本次先离线验证，不增加付费调用。

用户授权实施「程序当前事实＋模型工作进度」。仅新 repair-v1 尝试绑定 context_contract=v2；已绑定旧提示词的会话沿用原提示词、工具 schema 与投影，不迁移旧检查点。无模型摘要调用、无第二套进度数据库。

- 每轮从原 runtime、完整检查点、全产品版本生成 current_task_facts：任务身份／阶段、批准文档入口、累计成功修改及其最新写入版本适用性、唯一当前自测、最新独立验证失败、明确决定、预算及待执行验证。原反馈在 input 一份，原目标保持原文与待独立审查状态，不认定 open 等于未实现或已实现。
- 当前自测区分未测、失败、当前通过和过期，核对全文件集合、字节、命令与 validation_boundary；边界前的自测不得消除提交后的验证失败。文件缺失或未知副作用保留阻塞，不猜成功。门禁仅说明程序已知的必要条件，不代替业务判断或自动提交。
- update_plan 保持原 steps／reason，可选保存 findings、open_questions、next_action。这些都是模型判断，绑定记录时的完整产品／文档／授权版本；版本改变标记需复核，不自动核销目标、批准设计或清除失败。进度工具非提交前置条件，不增加强制调用。
- 原协议及思考配对、实际正文与行范围、权限、原审计、日志查询和显式提交继续保留。新视图不默认并列旧读摘要／多个自测状态；历史仍按原权限查询。当前未提供、截断或已变更正文仍允许补读。验证失败回同会话，原最新失败及证据入口持续可见。
- 离线回放与回归验证覆盖累计修改、失效、独立失败、决定／恢复、未知动作、正文补读、协议和旧契约；机制通过不代表真实模型行为或 Token 收益。本次不追加真实模型调用。

用户确认 `REPAIR_DOCKER_ISOLATION_V1_AI_DRAFT.md`，按其快照、白名单环境、断网回环、非 root／只读运行、独立宿主预览和未知副作用停止契约实施。不改变旧任务执行后端。隔离 profile 必须记录镜像完整 ID／digest、Runner 与镜像配置哈希及真实探针结果；当前配置与证据不一致或缺失时保持入口关闭，不能只因 Docker 可用就开门禁。

Playwright 版本沿用项目 1.55.0；新模式要求 bundled Chromium，并显式 `chromium_sandbox=True`，不隐式替换旧 channel="chrome"。镜像内 Node 使用该固定 Playwright 包自带的 Node 二进制，构建时记录实际版本并验证 Node 内置测试，不添加宿主依赖。具体运行兼容以本轮合成探针为准。
