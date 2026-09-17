# Context 第一步全 DeepSeek 完整链路验证

日期：2026-09-17。

## 方法与边界

临时 SQLite 与独立 Task Workspace，使用真实 Worker 阶段处理和事件消费。仅在测试进程清空 KIMI_STEPS，使文档阶段也走 DeepSeek；源码和正式配置未修改。实际传输调用总上限 30 次，返修上限两轮；实际 14 次调用、1 轮返修，无传输重试，模型请求 Trace 的 Provider 全部为 deepseek，模型为 deepseek-flash。

测试脚本：`/private/tmp/context-full-deepseek.py`；独立验收脚本：`/private/tmp/context-independent-acceptance.py`。正式 MySQL、任务及密钥文件均未修改；认证由现有 Runtime 读取受控密钥，密钥未输出或进入证据。

固定需求为按钮计算器：四则运算，单次二元计算，结果两位小数，除零显示 Error，新数字／C 恢复，禁止键盘及连续计算，无历史存储，长结果完整显示。原始输入还固定了 2+3、7-2、3*4、9/4、1.235+0、5/0 后 6+4 等验收例子。

## 完整流程

1. 产品门径直接 READY，未实际产生需求追问。DeepSeek 生成 Draft、独立 Review、Candidate。候选覆盖验收例子，但仍保留开放问题章节，属于文档质量限制，不声称无缺陷。
2. 测试用户核对候选后明确确认输入原样显示、普通 JavaScript 数字、Error 后运算符／等于无效果、长结果完整显示、不额外限制输入位数，提交 document_approval。该审批不代表真实用户验收。
3. 架构 Planner 要求架构文档，作者、评审、正式化均执行。Dev Design Planner 认为现有依据足够，保存跳过决定；没有强制伪造独立 Dev Design。
4. DeepSeek 生成六个必需产品文件，Node 35 项通过，系统启动 HTTP 服务并执行真实 Chromium 验证。
5. 首轮浏览器验证错误地把实际长结果 `999999998000000000.00` 当作失败，系统返回 develop。模型修改浏览器脚本的长结果断言，系统受控复验通过；随后再次 Node 35 项、启动和 Chromium 验证通过，进入 waiting_acceptance。
6. 独立 Chromium 按按钮操作，22 项检查通过：包括四则运算、1.235+0=1.24、除零恢复、错误／结果后非法操作无效果、新计算、小数点去重、等于前置条件、C、键盘无效、长结果和页面错误。长结果还验证了显示区不裁切，页面脚本错误为 0。
7. 测试用户提交 acceptance_result，隔离 Task 最终 succeeded。用户本人尚未验收，Windows 未验证。

测试控制脚本最初把审批事件误写为 approve_product；发现后通过正确 document_approval 在隔离库完成审批。正在运行的脚本随后提交的旧事件被系统拒绝，不改变已批准状态。脚本源文件已修正；该测试控制错误不归因于产品实现。

## 用量与结论

14 次响应合计输入 101,787 Token、输出 25,461 Token、总计 127,248 Token，来自 Provider 实际 usage。输入总量包含多次重复读取以及缓存命中，不等同于计费成本。本次未运行优化前完整链路，不能推断节省比例。

当前 context 优化未阻断该真实生成流程，也真实执行了无独立 Dev Design 的开发分支与浏览器失败后的返修。没有测试需求问答循环、设计版本增量变化或返修多轮无写入纠正，不将单任务成功推广为通用能力。

## 证据位置

临时根目录：`/var/folders/h7/z81qmxk16ks2kn3jzr21_k7m0000gn/T/context-full-deepseek-t3gv1hqp`。

- `test.db`：隔离任务、事件、消息、StepRun、Trace 索引。
- `workspace/1/traces/`：完整模型请求、合并响应、工具及状态记录；自动链路结束时 128 条，后续验收另有事件记录。
- `workspace/1/evidence/`：Node／浏览器验证、设计跳过和实现血缘。
- `summary.json`：自动链路结果及逐次 usage。
- `independent-acceptance.json`、`acceptance.png`：独立操作验收及截图。
- `final-status.json`：测试验收后的 succeeded。

临时证据可能被系统清理，本报告保留必要结果。项目后端回归 91 项通过，差异检查通过。本次无服务源码变更，无需重启正式服务。
