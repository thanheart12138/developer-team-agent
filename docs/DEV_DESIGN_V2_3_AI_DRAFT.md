# v2.3 结构化任务记忆——Dev Design AI 草案

## 文档状态

- 版本：v2.3，草案 1。
- 日期：2026-09-16。
- 状态：用户明确委托撰写，待评审、待确认，未实施。
- 依据：ROADMAP 中 v2.3 目标，以及用户指定的「统一记忆结构、显式问答、保留确认依据、统一请求接入、产物关联调用来源」五步方案。
- 当前有效设计仍为 `docs/DEV_DESIGN.md`；本文件不能自行改变现有运行规则。
- 本文所有新增字段、接口和失败策略均为 AI 设计建议，用户确认后才纳入有效设计。

## 1．目标、范围与限制

每次 Planner、Author、Reviewer、Validator、开发和返修调用，都能读取一致的当前目标、有效决定、成对问答、文档版本和工作证据。切换 Provider、重新请求及 Worker 恢复后，关系不丢失。

保留严格单 Worker、七阶段治理边界、现有模型路由和各类预算。不新增数据库表或第三方依赖。模型只消费记忆，不能直接修改记忆或改变 Task 事实状态。

本版不实现 Token 估算、向量检索、自动摘要压缩、全代码按需选择和通用语义去重。这些留给后续版本。原有受控工具权限仍是最小隔离，本设计不解决 exec 越界问题，也不声称记忆文件已获得安全沙箱保护。

「不重复提问」是指定场景的真实模型验收目标；程序保证确认依据被提供，不承诺仅凭文本去重即可阻止所有语义重复问题。部分回答、真实冲突和尚未回答的问题仍允许澄清。

## 2．现状与变更点

现有 `conversation-turns.json` 通过扫描 Message 和问号推断问答；回答后 turn_id 会改变。`artifacts.json` 默认关联最后一条已回答问答。产品阶段使用账本，其他调用各自构造 context；产品的 unpaired_user_requests 实际还包含已配对答案。

本版改为在等待用户、消费回答、审批、实际行动和产物写入边界显式更新。统一请求入口注入记忆，原始 Message 和 Trace 继续保留。

## 3．存储与权威来源

沿用现有目录约定，增加一个文件：

```text
workspace/{task_id}/
├─ evidence/
│  ├─ task-memory.json          # 唯一权威记忆快照
│  ├─ conversation-turns.json   # 快照中 turns 的兼容投影
│  ├─ artifacts.json            # 快照中 artifacts 的兼容投影
│  └─ ...                      # 原有报告、版本血缘和检查点
├─ docs/                       # 正式文档及历史版本
├─ product/
└─ traces/                     # 请求、合并响应、工具及记忆业务事件
```

MySQL 的 Task、StepRun、Event、Message 是运行状态和消息的权威来源；正式文档和已登记验证记录是文档／验证事实来源。task-memory.json 是它们的结构化上下文投影，不能反向批准文档或放行任务。

两个兼容账本由快照生成，不再各自维护关系。读取新记忆时禁止混合三个文件取「最新值」。快照使用临时文件加原子替换；两个投影可重建，写失败不改变权威快照。无需新增 memory/ 目录或事件 JSONL。

## 4．数据契约

### 4.1 TaskMemory

```text
schema_version: 1
task_id: int
revision: int                  # 每次有效业务变化递增
updated_at: UTC datetime
applied_update_ids: list[str]   # 防止恢复时重复应用
working_state: WorkingState
turns: list[QuestionAnswerTurn]
decisions: list[Decision]
documents: list[DocumentRef]
evidence: list[EvidenceRef]
artifacts: list[ArtifactRef]
unpaired_requests: list[MessageRef]
source_cursor: {memory_trace_sequence: int}
```

所有引用必须属于当前任务。文件引用只使用工作区相对路径，读取时重新校验路径及 SHA-256；不得因记忆中记录了路径就放宽工具/API 权限。

### 4.2 WorkingState

```text
goal: {text, source_event_id?, source_message_id}
active_event_id: int | null
step: 当前 Step
action: 当前行动或 null
problem: {description, source_refs, classification?} | null
last_action: {action_id, type, status, result_summary, evidence_refs} | null
pending_question_ids: list[str]
pending_approval: {document_type, version, path, sha256} | null
remaining_budget: 按现有程序规则计算的各项剩余预算
```

初始需求是初始目标；变更／失败验收反馈产生本轮目标。短回答只补充当前问题，不能把目标替换为「对的」。stage/action 由程序决定，模型结果只作为经过校验的建议。

### 4.3 QuestionAnswerTurn

```text
question_id: "question:{assistant_message_id}"  # 生命周期内不变
turn_id: 与 question_id 相同                  # 兼容旧字段
purpose: product_clarification | acceptance_clarification | design_clarification
question: {message_id, content}
answers: list[{event_id, message_id, content}]
status: open | answered_pending_review | resolved | superseded
step_run_id: 提问所属 Run
goal_event_id: 本轮事件或 null
parent_question_id: 补充澄清所依据的问题或 null
resolution: {source_request_id, evidence_refs} | null
artifact_refs: list[str]
```

一轮最多三个问题时，完整问题组与完整回答作为不可拆分条目。不按编号自动推断哪个子问题已回答。存在缺项时模型提出剩余问题并明确关联 parent_question_id；旧轮状态保持 answered_pending_review，直到后续校验认为充分。

回答进入 answered_pending_review 表示「已收到」，不等于含义已澄清。产品 READY、验收一致性通过或已有设计澄清门径通过后才 resolved。该状态仅表示可继续理解，不表示用户批准了软件或文档。

### 4.4 Decision

```text
decision_id: 稳定来源 ID，例如 "qa:{question_id}" 或 "approval:{event_id}"
kind: user_answer | approved_requirement
source_refs: 问答 ID 或已消费审批事件、消息、文档版本
statement: 原始问答／批准文档引用，不强制提取通用语义事实
interpretation: {text, source_request_id} | null  # 模型辅助解释
status: active | unresolved | superseded
superseded_by: decision_id | null
```

确认依据保留问题和全部回答原文；模型解释不能脱离来源单独传递，也不能升级为用户授权。回答未充分时 decision 为 unresolved，照样进入 pending_decisions。

正式需求获批准后，旧 approved_requirement 被新批准版本替代。旧问答不因审批一律失效；只有明确的用户改口，或新获批候选明确列出其替代关系，才替代特定旧决定。候选提交审批时附 superseded_decision_ids；Review 检查这些关系，用户批准整个候选后程序才生效。关系不明确时不得自动覆盖，保留冲突并澄清。

测试通过属于证据，不产生用户决定。模型说「用户已确认」而没有合法来源时不能创建 Decision。

### 4.5 DocumentRef 与 EvidenceRef

```text
DocumentRef:
  document_id, type, version, path, sha256
  status: current | superseded | skipped
  authority: user_approved | program_formalized | planner_skip
  source_refs, superseded_by

EvidenceRef:
  evidence_id, type, summary, path?, sha256?, trace_sequence?
  step_run_id, action_id, source_event_id?, created_at
  code_hashes?, related_document_ids
  status: current | historical | stale
```

Document authority 必须区分用户批准需求、程序正式化架构／设计、Planner 跳过依据，不能把全部正式文件称作「用户已确认」。skipped 不是空白正式文档，必须附决策引用和所依据的上游哈希。

测试证据绑定实际执行时的代码哈希。后来代码变化则 stale；新结果产生后旧结果 historical。报告路径被覆盖不代表旧结果可由该路径读取，旧完整结果从对应 Trace 获取。当前失败与旧失败显式区分，不自动取文件名排序最后一份。

### 4.6 ArtifactRef 与 RequestProvenance

```text
RequestProvenance:
  context_id: "context:{request_id}"
  memory_revision
  source_event_ids, source_message_ids, source_question_ids, source_decision_ids
  document_ids, evidence_ids

ArtifactRef:
  artifact_id: "tool:{step_run_id}:{tool_call_id}" 或 "formal:{event_id}:{document_type}"
  path, name, operation, bytes_written, sha256
  step_run_id, tool_call_id?, request_id?, context_id?
  source_refs: RequestProvenance 中实际使用的来源
  created_at
```

一次调用可关联多组问答；没有问答时 source_question_ids 为空，不回退到「最近一轮」。关系表示本次调用使用了哪些输入，不能证明所有输入均已落实。需求覆盖和验证仍由原有门径负责。

程序批准复制、正式化复制也记录 ArtifactRef，来源为审批／正式化记录和源文档，不伪造模型工具调用。文件相同也可记录真实成功写入，但 change 判断仍比较前后哈希。

## 5．模块接口与职责

新增 `backend/app/runtime/memory.py`，使用现有标准库及 Pydantic 定义和校验上述结构。

```text
load_or_reconcile(db, task) -> TaskMemory
record_question(db, task, run, message, purpose, parent_question_id?) -> question_id
record_answer(db, task, event, message, question_id) -> update
resolve_question(db, task, question_id, validated_result) -> update
record_document(db, task, document_ref, artifact_ref?) -> update
record_action_result(db, task, action_result, evidence_refs) -> update
record_artifact(db, task, artifact_ref, provenance) -> update
build_request_memory(db, task, run, request_id, purpose, history_key) -> (context, provenance)
apply_committed_updates(db, task) -> TaskMemory
```

统一入口负责读取、校验、去重和投影；Worker 负责业务触发。Model Runtime 只负责传输、消息协议和 Provider，Tool Runtime 保持实际工具执行职责。API 不自行解释用户答案。

## 6．更新触发与等待状态

| 实际触发 | 记忆更新 |
| --- | --- |
| 创建任务已提交 | 初始化目标、初始未配对请求 |
| 程序决定提出问题并等待 | 显式登记问题，加入 pending_question_ids |
| 消费有效用户回答 | 追加回答，创建原始依据，保留当前目标 |
| 语义门径通过 | 解决对应问题，更新可用决定 |
| 提交文档待审批 | 登记 pending_approval，不能登记为正式需求 |
| 消费批准事件 | 更新正式文档、批准决定、明确替代关系和复制产物 |
| Planner 行动校验通过 | 更新 current action，不把建议当执行结果 |
| inspect／工具完成 | 登记真实结果与证据；失败同样登记 |
| 成功写入或正式复制 | 按本次调用／审批来源记录产物 |
| 测试、启动、浏览器完成 | 更新对应结果和代码版本证据 |
| 阶段／任务状态变化 | 重新从数据库计算工作状态和预算 |

所有等待用户的路径都必须登记问题：产品门径、验收一致性、初始设计 Planner、设计 Transition Planner、Bug Next Action Planner。

审批使用 pending_approval，不能因批准 Message 含有反馈而把它配对到问题。拒绝候选的反馈登记为修订请求，同样不伪造问答。

## 7．API 增量契约

`GET /api/tasks/{task_id}` 在原响应上增加：

```text
pending_question_id: str | null
```

仅在等待澄清时返回；等待文档审批时为 null。每个任务只允许一个当前问题组。

前端提交回答时仍使用现有 Event API：

```json
{"type":"user_message","data":{"content":"是的","question_id":"question:123"}}
```

API 登记 Event，Worker 在事务中核对 question_id。旧页面未带 ID 时，可绑定唯一已登记的开放问题组；有多个、无问题或 ID 不匹配时拒绝事件，使用 question_not_pending，不把回答绑定到最近 Message。非等待状态下 user_message 仍按原规则登记普通请求。

Task status、Event 类型、模型／工具外部协议不变。无需新增公开 memory API 或记忆管理界面；发送给模型的结构和来源可在请求 Trace 中查看。

## 8．统一模型请求接入

model_tool_loop 每次新的逻辑模型请求生成 request_id 后，调用 build_request_memory，写入保留键 context.task_memory，并把 provenance 加入 model_request Trace metadata 和工具检查点。

```text
task_memory:
  working_state
  confirmed_decisions           # 原始确认依据＋附带解释
  pending_decisions
  conversation_turns            # 保留完整问题与回答组
  unpaired_requests             # 未归入问答或审批的用户请求
  current_documents            # 当前正式版本及跳过依据
  working_evidence              # 当前失败、最近实际结果及必要引用
  related_artifacts            # 相关问答使用过的写入产物
```

模型提示词明确有效状态含义、来源权限，以及被替代决定不可作为当前约束。不会把 Message.role=assistant 的普通解释登记成用户事实。

本版使用确定性规则：提供所有 active／unresolved 决定、未被完全替代的问答组、当前文档引用与已有阶段要求的正文、当前失败证据、最近结果；不发送全量原始 Trace。已配对回答不得再重复放入 unpaired_requests。混合新旧有效决定的问答组必须整体保留，并标明各决定状态，不拆原文。

阶段专用 context 保留，例如旧下游设计、上游差异、当前代码全文和完整失败报告。统一记忆不提前改变 v2.4 的代码选择策略；若专用字段与记忆中的文档版本／目标矛盾，程序以 context_memory_conflict 阻止调用，不默默发送两份相互冲突的输入。

同一逻辑调用的传输重试和 Kimi→DeepSeek 技术降级复用同一请求快照及 context_id。工具完成后，下一个逻辑调用使用更新记忆。原 history_key 的 assistant/tool 配对继续使用，不把别的角色历史引入当前请求。

历史调查通过显式 Trace sequence 或版本路径读取并验证，登记为 inspect 证据后供下一次调用使用；不新增通用搜索模型或无界历史回放。

## 9．事务、幂等与故障恢复

JSON 原子替换不能与 MySQL 构成一个事务。本设计使用现有 TraceRecord 事务登记作为提交凭据，新增 memory_update 业务 Trace，而不是依赖文件更新时间。

每次业务变化生成稳定 update_id，例如 question:{message_id}、answer:{event_id}、artifact:{run_id}:{call_id}、validation:{run_id}:{action_id}。payload 保存类型、来源和结构化变化；正常模型请求不额外生成记忆文件，更新不是按流式片段产生。

提交顺序：

1. 在业务事务中登记 Message／Event／状态和 memory_update Trace。
2. memory_update 必须用严格 record_trace，不能使用吞错的 safe_record_trace；写入失败则当前业务事务不提交。
3. 提交业务事务后，读取数据库已登记的更新，按 sequence 应用到快照。
4. 原子替换权威快照后更新兼容投影；update_id 已存在则跳过，不重复追加问答或产物。

Trace 文件先写成功但事务回滚时，它不是合法来源，恢复只读取有数据库索引的记录。详情路径可用性处理沿用现有 Trace 恢复规则，不把孤立文件视为已提交。

阶段中 db.commit 多个边界都须调用 apply_committed_updates；最终 Event 提交也调用。build_request_memory 总会先 reconcile，因此快照提交失败不会导致下一模型调用使用旧决定。

恢复规则：

- 快照缺失／损坏时，从合法 memory_update 和已提交初始消息重放，不自动调用模型修记忆。
- 业务提交后但快照未更新：重放新增更新。
- 问答投影／产物投影损坏：从权威快照重写。
- 已提交更新详情缺失、引用跨任务、来源不合法或同 ID 内容冲突：memory_reconciliation_failed，停止当前任务自动执行，记录具体证据。
- 记忆不可用不能退回「扫描全部消息＋猜最近回答」。没有充分来源的旧关系标 unknown，要求澄清或人工处理，不生成 confirmed。
- 对工具已实际执行但数据库未提交的窗口，先核对持久化检查点、文件哈希及工具结果；证据不充分不重复执行。后台命令不因记忆更新失败自动重跑。无法核对时按现有恢复失败策略停止。

## 10．旧任务兼容

第一版不批量迁移正式任务、不修改 Task 25 历史 Trace，也不反向认可旧 artifacts.turn_id 的因果关系。

首次继续旧任务时执行一次可重复的本地导入：加载旧问答和产物账本，保留 legacy 标记及原关系；来源 Message 属于当前任务且明确问答记录存在时保留原文，但 legacy 推断关系标 needs_review。正式需求只在能够定位已消费批准事件及匹配版本时标 user_approved；正式架构依据程序版本记录标 program_formalized。

缺少充分来源的条目仍可作为历史线索，不列为确认决定。旧账本导入登记 bootstrap:{task_id}:v1 更新后才生成新快照；以后不再每次扫描全部历史。旧 question_id 映射固定后不因回答改变。导入不能删除旧文件或发起模型调用。

## 11．实施改动点

1. 新增 memory.py 数据契约、事件更新、快照读取与一致性校验。
2. 替换 Worker 的问号扫描和最后回答关联，接入所有 waiting_user 路径及正式复制。
3. 更新 TaskResponse 与回答提交，明确当前问题 ID。
4. 在 model_tool_loop 统一注入记忆，保留 Provider 重试／降级的快照一致性。
5. 移除产品上下文重复的已配对用户消息，其他阶段迁移公共输入；保留必要专用证据。
6. 加入兼容导入和恢复验证；确认设计生效后同步正式架构／Dev Design。

不自动提交 Git、不启动真实任务、不重新运行 Task 25；真实验证需要明确范围和调用预算。

## 12．验证与完成标准

### 12.1 机制测试

| 用例 | 预期 |
| --- | --- |
| 回答「是的」 | 模型 context 同时含原问题和回答，答案不重复进入未配对请求 |
| 普通消息含问号 | 不登记待答问题；只有程序 waiting 路径登记 |
| 问题组只回答一部分 | 不自动确认全部；补充问题关联原问题 |
| 跨 Provider／技术降级 | 同一逻辑请求的 context_id、revision 和来源完全一致 |
| 两轮问答、两次写入 | 各产物关联各次请求真实来源，不默认最后问答 |
| 批准／拒绝候选 | 不生成伪问答；批准复制记录版本和来源 |
| 新批准版本明确替代旧决定 | 旧决定失效且历史保留；含糊冲突不自动覆盖 |
| 模型伪称用户确认 | 缺少合法来源不能创建 active Decision |
| 代码变更后读旧成功报告 | 证据 stale，不能当作当前成功 |
| 提交后快照写失败／重启 | 可重放，条目及 artifact 不重复 |
| 事务回滚但 Trace 文件存在 | 文件不参与已确认记忆 |
| 快照／投影损坏 | 前者依据合法更新恢复；后者从快照恢复 |
| 提交来源缺失／跨任务引用 | 停止自动执行，不猜事实 |
| 旧任务来源不充分 | 标 needs_review，不静默确认 |

此外回归现有 Planner 依赖、审批、原失败复跑、工具历史隔离、调用和返修预算。运行前端生产构建；浏览器确认回答 ID 提交及失效问题拒绝后仍可正常操作。

### 12.2 真实模型与产品验证

先完成当前 v2.2 必要的混合模型链路验证，再使用一个未针对性调试过的新任务作为 v2.3 验收案例。明确用例和预期后运行，单次评测新增逻辑模型调用最多 30 次；预算耗尽停止，不能无界续跑。

实际序列：Kimi 提问 → 用户短指代回答 → 获批正式需求 → DeepSeek 实施 → 一次受控失败和重新调用 → Worker 重启恢复 → 再次请求 → 自动测试／HTTP／真实浏览器验证 → 用户验收。

抽查发送的 context，核对问题、回答、当前文档及产物引用；确认模型没有重复询问已明确回答的事项，并能依据上下文准确说明上一个问题、答案及实际写入文件。不得仅依据模型「我记得」的声明认定通过。

另测保留真实未回答问题以及用户明确改变决定，避免以「不重复提问」为由跳过必要澄清。软件实际启动并操作，错误处理后仍可使用。保存输入、步骤、期望、实际、请求 Trace 与报告位置及限制。

分别报告机制验证、真实模型验证、生成软件验证和用户验收。Task 状态成功不替代四类证据。

## 13．本草案需确认的关键取舍

- 一份权威快照、两份兼容投影，并以已提交 memory_update 重放恢复，不新增 MySQL schema。
- 问题组和回答保留原文；不增加通用语义提取调用；未充分答案先为 unresolved。
- 旧决定的替代关系随候选审批确认，模型不能自己取消用户决定。
- 无法核对提交来源时停止自动执行，旧任务不可靠关联只作线索。
- 本版保持专用上下文中的必要全文，Token 选择和通用重复问题防护后续处理。

这些取舍尚未确认。本次只交付设计草案，不代表 v2.3 已实现或可在正式任务启用。
