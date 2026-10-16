# DeepSeek 看到通过结果后的真实交接续测

日期：2026-10-02。用户确认从上次已通过的隔离产物继续，最多新增 6 次真实 HTTP（含重试），只观察主动自测及显式提交，不重跑产品和规划阶段。

## 结果

**实际 4 HTTP／163,166 Token，模型主动自测 86／86 通过，随后显式提交成功。**没有人工改产品、代调用自测或提交，交接后立即停止；原目标 E4-1 仍 open，完整任务未完成、未用户验收。

| 新增 HTTP | 实际动作与结果 | Token |
|---|---|---:|
| 1 | 读取当前通过报告与 README；重读已提供的验证脚本、实现说明范围被拒绝 | 34,772 |
| 2 | 五次 replace，纠正验证脚本两处文案和实现说明三处旧自托管服务描述；程序诊断仍通过 | 50,936 |
| 3 | 模型主动 `run_unit_tests`，真实 Node 86 passed／0 failed／0 skipped／0 todo | 33,510 |
| 4 | 模型显式 `submit_unit_for_test`，当前版本提交成功，探针停止 | 43,948 |

- 输入：144,478 Token。
- 输出：18,688 Token，其中响应 usage 报告的 reasoning_tokens 合计 17,341。
- 输入缓存命中：13,312；未命中：131,166。
- 耗时：85.27 秒。
- 四个不同请求 ID、四份实际响应用量，没有重试或 length 结束；未追加第五次调用。

源轨迹前一轮 12 HTTP／444,711 Token 加本轮为 16 HTTP／607,877 Token，到交接为止。此数字不是整软件交付成本，也不是严格同起点 A/B；本轮已从通过版本开始，不能由这次成功证明稳定成功率或把收益归为单一修复。

## 输入与隔离方式

源目录：`/private/tmp/context-relay-deepseek-20261002-_6ip7z8p`。

新目录：`/private/tmp/post-green-handoff-deepseek-20261002-zv5ar7vc`。

只读复制源 SQLite 和完整任务工作区，20 个产品文件初始哈希完全一致，无符号链接；不复制项目密钥。沿用同一 Run 19／attempt 6、21 条完整检查点和原接力边界，源 model_call_count 为 12，没有清空历史或从头新建开发会话。只在隔离副本恢复运行状态；探针允许最多新增六次 HTTP，并独立在每次 `/chat/completions` 发送前计数，重试也计入。

当前代码实际调用 `slice_workflow.handle_repair`／Worker／受控工具，Developer v13、DeepSeek flash thinking enabled。与前样本相同，探针显式设置 max_tokens=65,536，不修改正式 Runtime 或思考设置。本地逻辑上限设为 18，四次请求真实显示已用 13／14／15／16，剩余 5／4／3／2；该字段明确为逻辑次数，独立 HTTP 上限仍为本轮六次。

首轮从原完整边界接力，消息只有 system／user，提供当前版本诊断通过；本轮四次请求均为 passed=true／matches_current_files=true，原目标和权限保持。已读旧诊断不再作为代码正文携带，历史报告仍可按需查询。原思考、调用、结果作为检查点和审计完整保留，当前会话续传完整协议消息。

## 核对证据

### 真实自测与提交

模型实际调用固定命令：

```text
node --test product.test.js src/materials/materials.test.js src/topics/topics.test.js src/tasks/tasks.test.js src/workbench/workbench.test.js
```

Node 真实结果为 86／86 通过，无 skip／todo。自测绑定 20 个范围文件，前后版本一致；提交范围 15 个文件全部被自测覆盖，其哈希与自测及当前文件一致。两种范围不必相等，不能把范围较小的提交误判为版本不一致。

11 条新增检查点动作：read 成功两次、重复读取拒绝两次、replace 成功五次、实际自测及实际提交各一次。仅 `product/verify_product.py` 和 `product/implementation.md` 改变：前者改文档字符串和警告文案，后者清理剩余旧自托管描述。没有新实现页面编辑功能，不能把此前已有功能算作本轮新增。

模型仍多花了一轮读取并尝试两个重复范围，因此成功交接不等于效率问题全部解决。此次修改主要是契约说明一致性，没有发现新的业务实现缺陷。

### 源与正式任务

- 源 20 个产品文件、检查点 SHA、原目标账本保持，源 Run 仍消耗 12 次调用。
- 新检查点前 21 条与源逐项完全一致；新增内容没有覆盖原思考和结果。
- 原目标 E4-1 保持 open，账本没有被模型或探针关闭。
- 正式库的 24 条任务 ID／状态／阶段／版本和 Trace 数量在运行前后完全一致，0 pending event／0 running task。
- 正式 Worker 2573 未重启，日志 0 字节。没有正式任务续跑、产品服务重启或部署。

## 验证边界与下一步

本轮补齐了上一样本没有观察到的「当前诊断通过后，模型主动自测与提交」。这条具体真实轨迹交接成功，程序没有自动替模型结束。

探针在正式独立复验之前停止，未推进后续阶段、未执行原始目标独立关闭审查、未重新验证全部产品需求。因此机制与真实模型交接有证据，完整软件交付及稳定成本优势仍未证明。后续应从这个已提交版本推进独立验证与目标闭合，不重新生成产品或规划。

证据文件均在新目录，临时路径后续可能失效：

- `STRUCTURE.md`、`probe.py`、`baseline.json`、`run-baseline.json`。
- `run.log`、`sent-requests/001.json` 至 `004.json`、`request-stats.json`、`call-count.json`。
- `result.json`、`audit-summary.json`。
- `workspace/1/evidence/context-relay-checkpoint.json`、接力边界与版本诊断报告。
- `formal-before.json`、`formal-isolation-verification.json`。
