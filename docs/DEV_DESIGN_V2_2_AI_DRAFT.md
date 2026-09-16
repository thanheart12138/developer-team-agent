# 开发团队模拟器 v2.2 Dev Design（AI 草案）

## 文档状态

- 状态：**AI 草案，待用户评审和确认；不替代当前有效的 `docs/DEV_DESIGN.md`**。
- 已确认并实施的验收统一 Planner 与 Bug 闭环增量规则，以 `docs/DEV_DESIGN.md` 为准；下文完整行动／持久化方案仍为待确认草案。
- 日期：2026-09-15。
- 依据：`ROADMAP.md` 的 v2.2 目标、当前有效的产品需求／架构／Dev Design、现有七阶段 Worker 与 Transition Planner。
- 本草案提出的数据库结构和状态转换均未实施。产品需求与架构尚未更新为 v2.2 有效版本，文末列出需用户确认的关键决定。

## 1．目标、范围和边界

v2.2 的动态 Planner 首批只覆盖两类已有任务：修复生成软件的 Bug、给已有生成软件增加一个小功能。新建软件暂沿用现有完整链路，仍经过产品候选审批、必要的架构和 Dev Design、开发、测试、启动、真实浏览器验证及人工验收；它用于检查 v2.2 改动没有破坏原流程。Planner 选择当前目标所需的下一行动，程序执行并验证，不允许模型直接修改 `Task`／`StepRun` 状态、跳过审批或凭文本宣布完成。

Planner 的动作枚举固定为 `inspect`、`clarify`、`update_requirement`、`update_architecture`、`update_dev_design`、`modify_code`、`run_test`、`start_product`、`verify_product`、`finish`。v2.2 不引入任意动作、动态工具注册、多 Worker 或技术栈切换。v2.3 的结构化记忆、v2.4 的大规模文件上下文选择与 Token 可视化，以及此前暂停的安全防护，均不在本版实施范围内。v2.2 的 `inspect` 用于继续取得缺失证据，不承诺本版已解决大量代码文件的上下文成本。

## 2．职责与权威来源

- **程序**根据当前有效文档版本、任务状态、用户审批、实际文件哈希、测试／启动／浏览器结果和预算，计算可选动作；校验 Planner 输出并执行动作；更新数据库状态。MySQL 中的 `Task`、`StepRun`、`Event` 和下述 `ActionRun` 是运行状态的权威来源。
- **Planner 模型**只从程序提供的可选集合提议一个动作，说明使用的证据和预计获得的结果。Planner 请求不提供工具定义，不产生文件写入或命令执行。
- **动作执行器**复用现有产品 Draft／Review／Candidate、Transition Planner、Develop、Node 测试、HTTP 启动和 Playwright 验证逻辑。执行结果必须由程序产生并保存，随后再请求下一次规划。
- **用户**确认正式产品需求和人工验收；模型不能把文档候选自行批准，也不能将 `waiting_acceptance` 直接改为 `succeeded`。

现有 `Step` 七个枚举继续表示治理阶段与 Provider 路由；`ActionRun` 表示阶段内或阶段之间一次具体行动。`Task.cur_step` 由程序根据行动目标维护，不由 Planner 输出决定。架构和 Dev Design 的现有 Transition Planner 仍负责各自的 `revise`／`reuse`／`clarify` 判断；Next Action Planner 不替代它，也不能仅凭自己的判断复用旧正式文档。

## 3．数据与持久化（建议方案）

建议新增 `ActionRun`，使一次规划、执行和恢复有独立的数据库记录；此项**待用户确认**，后续实施涉及数据库 schema 变更，须另行取得授权。现有 `Task`、`StepRun`、`Event`、`Message`、`TraceRecord` 字段语义保持不变。

```text
ActionRun
- id：主键
- task_id：所属任务
- step_run_id：所属治理阶段执行；规划前先创建或恢复对应 StepRun，不允许为空
- sequence：任务内单调递增，(task_id, sequence) 唯一
- action：固定动作枚举
- status：planned | running | waiting_user | succeeded | failed
- request_id：Planner 模型请求 ID；程序强制动作可为空
- decision_json：经程序校验的提议、目标、理由和证据引用
- input_fingerprint：规划时正式文档版本、失败证据与相关文件哈希的摘要
- result_json：实际动作结果、文件哈希及测试／验证证据引用
- error：失败代码和简述
- started_at、finished_at
```

Planner 原始请求／响应、动作校验、执行和结果分别追加 `planner_request`、`planner_response`、`planner_validation`、`action_start`、`action_result` Trace。详情仍保存在当前任务的 `traces/` 中。`ActionRun` 只保存结构化摘要和证据引用，不重复存储模型长文本；现有任务工作区检查点继续记录工具调用和恢复所需参数。Trace 是审计证据，不作为唯一的任务状态依据。

## 4．Planner 请求与响应契约

程序每次规划前构造输入：当前目标及任务类型、用户确认的需求／架构／Dev Design 版本、最近行动及其实际结果、最新失败及未解决问题、可用工具摘要、剩余模型调用／返修／工具预算、程序算出的 `allowed_actions`。程序不把未经批准的候选文档当成正式依据。

Planner 只返回一个 JSON 对象：

```json
{
  "action": "inspect",
  "targets": ["product/app.js"],
  "reason": "清除后显示异常，尚未确认状态重置逻辑",
  "evidence_refs": ["acceptance-triage-55", "product.md#清除行为"],
  "expected_result": "确认清除逻辑和显示常量是否偏离正式需求"
}
```

`action` 必须属于固定枚举和本次 `allowed_actions`；`targets` 必须是与动作对应的工作区相对路径、文档版本或测试范围，程序解析并校验，不能是任意外部路径；`reason`、`evidence_refs`、`expected_result` 不得为空。`run_test` 的 `targets` 指明 `original_failure` 或 `regression`，`clarify` 的 `targets` 提供一个待用户回答的问题。模型返回的路径、阶段、通过标志和完成声明都只是提议，程序独立核验。非法 JSON、未知动作、缺失必需字段或越权目标写入失败 Trace，最多允许两次新的逻辑调用纠正；仍无有效提议时以 `planner_protocol_failed` 明确失败，不执行猜测动作。

Planner 的 Provider 沿用当前治理阶段的固定路由和现有技术降级规则。Planner 调用计入所属 `StepRun.model_call_count`；技术降级不重复计逻辑调用。Planner 调用不提供 `read`／`write`／`exec` 工具定义。

## 5．可选动作与程序前置条件

程序先计算可选动作，模型不能通过理由扩大集合。对新建任务，产品审批及必要设计门径由程序强制；对已有任务，验收分类和已确认文档版本决定可从哪一阶段开始。表中的「完成证据」由程序检查，不接受模型自述。

| 动作 | 允许条件与执行 | 完成证据 |
| --- | --- | --- |
| `inspect` | 存在具体未解决问题；目标在当前任务工作区，使用现有 `read`／程序查询取得证据。重复读取同一目标且内容哈希和问题均未变化时拒绝无效重复 | 读取结果、目标哈希和新增证据引用写入 `ActionRun` 与 Trace；证据不足可规划其他相关文件 |
| `clarify` | 事实不足以确定核心行为、文档影响或可执行修复；只提出一个需要用户决定的问题 | `Task` 和 `ActionRun` 进入 `waiting_user`，问题保存为 Message；用户回答后由 Event 恢复规划 |
| `update_requirement` | 已有任务的需求变更具有合法现状／期望／验收示例契约；新建任务仍由原产品门径处理 | Draft、Review、Candidate 和覆盖校验完成后等待用户批准；批准且正式文件原子写入才成功 |
| `update_architecture` | 当前正式产品需求版本尚无相应架构血缘，或既有架构被分类为最早失效产物 | 现有 Transition Planner 的 `revise`／`reuse`／`clarify` 经程序校验；只有正式架构版本与上游相符才成功 |
| `update_dev_design` | 当前正式需求和架构已有确认版本，但当前 Dev Design 不对应其血缘或被分类为失效产物 | 同上；正式 Dev Design 当前版本和上游血缘一致 |
| `modify_code` | 当前有效 Dev Design 已就绪，且存在未实现差异、真实实现缺陷或失败返修；不能因代码文件存在而跳过 | 成功 `write`、相关文件哈希真实变化；返修还须复跑原失败验证通过，否则继续诊断或在预算内修复 |
| `run_test` | 代码或测试发生变化，或上一次相关测试未通过；原失败用例优先于完整回归。原失败来源是浏览器时，使用系统受控 Python 运行对应 Playwright 检查 | 指定范围的命令退出码为 0、无跳过标记、报告完整；原失败和必要回归分别保存结果 |
| `start_product` | 当前代码版本的必要测试均通过，且没有已确认的运行服务可复用 | 进程存活、HTTP 健康检查通过，记录 URL／PID／命令 |
| `verify_product` | 当前代码版本已通过测试和健康检查 | 真实 Playwright 与必要 Node 验证通过，保存完整报告和访问方式 |
| `finish` | 当前有效需求／设计与代码血缘一致，同一代码版本的测试、启动、浏览器验证全部通过，产物可访问 | 程序将任务置于 `waiting_acceptance`；只有用户后续明确验收通过的 Event 才置为 `succeeded` |

`finish` 在本草案中表示**自动工作完成并提交人工验收**，不表示模型或程序代替用户验收。此语义待用户确认。

## 6．两类任务的关键流程

### 6.1 修复 Bug

1. 保留现有验收分类和一致性检查。明确实现缺陷从 `develop` 进入规划，不重写正式产品、架构或 Dev Design；若分类指向上游，则先修订最早失效产物。
   当前有效 Dev Design 中「返修模型不提供 `read`、直接接收全部产品文件」的规则需要在用户确认 v2.2 设计后更新；本草案的 `inspect` 是程序执行的独立行动，不要求 Planner 模型自己调用 `read`。
2. Planner 根据反馈、原失败报告、正式设计和最近行动，在 `inspect` 与 `modify_code` 等允许动作中选择；证据已足够时可直接修改，证据不足时检查相关文件。一次检查不足可继续检查其他目标，但无变化的重复检查被程序拒绝。
3. 真实写入后先复跑原失败用例，再运行必要回归；原失败仍存在时保存真实输出并回到检查／修改，不因无关测试通过而放行。
4. 必要测试通过后启动、真实浏览器验证，最后由 `finish` 进入人工验收。原有三轮跨阶段返修、两次无变化纠正、相同工具动作与连续无写保护继续生效。

### 6.2 已有产品增加小功能

1. 用户描述「新增什么、为什么、怎么算成功」；当前正式需求不覆盖新行为时进入 `update_requirement`，Candidate 必须等待用户批准。
2. 正式需求更新后，现有 Transition Planner 分别判断架构和 Dev Design 的修订、复用或澄清；Next Action Planner 不能直接宣布旧设计仍有效。程序验证每个正式版本与上游血缘。
3. Dev Design 内容变化或现有实现缺少新功能时执行 `modify_code`，提供旧设计、新设计、差异与当前代码；只修改受影响文件和测试。随后依次验证原相关用例、必要回归、运行服务和浏览器行为。
4. 通过后等待人工验收；若新增行为的验收标准尚不明确，先 `clarify`，不能先编码再让测试反推需求。

新建软件的既有完整链路作为回归场景：本版不让动态 Planner 接管新建任务，必须确认用户审批、必要设计、测试和验证门径均未被 v2.2 的 Worker 改动破坏。

## 7．状态、事件与恢复

- `Task.status` 仍使用 `pending`、`running`、`waiting_user`、`waiting_acceptance`、`succeeded`、`failed`。一次 `ActionRun` 只对应一个动作；程序在数据库事务中持久化合法决定和 `planned` 状态，才开始外部文件或命令操作。动作完成后保存实际结果、更新 `ActionRun` 和下一治理阶段；未产生实际结果不得记为成功。
- `clarify` 的 `user_message` Event 消费时，先定位本任务等待中的 ActionRun，把成对问题／回答保存到现有问答账本，然后恢复 `running` 并重新规划。产品候选审批继续使用现有 `document_approval` 语义；拒绝后重新生成候选，不把拒绝当作批准。
- Worker 重启时先读取 MySQL 中 `planned`／`running` 的 ActionRun 及现有检查点。尚未执行的规划可继续执行；写文件中断先比对目标内容与哈希，已完成则补记结果，否则按已持久化参数恢复；测试和启动依现有受控恢复规则处理。检查点缺失或无法核验时标记明确失败，不猜测、不跳过。
- 用户事件事务保持 `pending` 或完整消费；事件与当前任务状态、待回答问题或候选版本不匹配时拒绝。Planner 决策不能覆盖并发到来的用户批准或验收 Event。

建议每任务最多 30 次 Next Action Planner 决策、同一未解决问题最多 8 次有效 `inspect`；现有单 Step 最多 100 次逻辑模型调用、最多 3 轮返修、最多 2 次无变化纠正等预算仍分别计数。新上限及跨 Step 计数方式**待用户确认**。预算耗尽记录具体原因与最后证据，不继续无界调用。

## 8．接口和展示

建议沿用现有创建／查询任务、提交 Event、增量消息与 Trace、产物和文件接口，不增加 Planner 专用外部 API。任务页通过 `planner_request`／`planner_response`／`planner_validation`／`action_result` Trace 展示「为什么选该动作、程序是否准许、实际结果是什么」；人工审批入口仍由 `Task.status`、`cur_step` 和候选版本驱动。若界面需要直接查询当前待执行动作，是否将其加入 `TaskResponse` 待用户决定，不在草案中预设。

## 9．失败处理与验证

- 非法 Planner 输出或不在允许集合的动作：拒绝并记录原文与校验原因，按第 4 节的次数纠正，不能执行。
- `inspect` 没有新证据或连续重复无效行动：程序拒绝并返回可复核的文件哈希／结果；达到预算后进入 `clarify` 或明确失败，不能机械推进固定下一阶段。
- 工具、测试、启动或浏览器失败：保存实际失败报告，按现有返修预算再次规划；不得以模型文本、文件存在、测试数量或单项无关测试通过代替原失败验证。
- 正式文档版本、代码哈希或测试证据在验证后变化：先前通过结果失效，`start_product`、`verify_product` 或 `finish` 前重新核对；不得使用旧通过记录完成新版本。

机制测试至少覆盖动作枚举及依赖拒绝、未批准需求不得进入下游、实现缺陷跳过无关文档、重复 `inspect` 阻止、原失败验证未通过不得 `finish`、`clarify` 问答恢复、重启后 ActionRun 与文件哈希恢复，以及正式版本变化导致旧验证失效。真实 DeepSeek／Kimi 测试需预先固定任务范围和调用上限，至少验证一项明确实现缺陷、一项已确认的小功能和一项新建软件回归；保留输入、Planner 决策、工具调用、实际文件差异、Node／Playwright 结果和人工验收步骤。测试通过只代表机制及所测任务已验证，最终验收仍由用户决定。

## 10．待用户确认的关键决定

1. 是否新增 `ActionRun` 数据表作为行动状态权威，还是在现有表上设计另一种同等可恢复的状态模型。此决定影响数据库 schema、事务与 Worker 恢复。
2. `finish` 是否按本草案只表示「自动验证完成，等待人工验收」。若还代表其他阶段完成，需定义额外完成条件，避免与 `succeeded` 混淆。
3. 每任务 Planner 决策上限、同一问题 `inspect` 上限及跨 Step 计数方式是否采用第 7 节的建议值。
4. v2.2 产品需求与架构是否确认「保留七个治理 Step、增加动态 ActionRun、仅支持 Bug 和已有产品小功能」这一边界。确认后应先更新相应有效文档，再据此实施与验证。
