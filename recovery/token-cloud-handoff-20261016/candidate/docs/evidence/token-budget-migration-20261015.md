# Token跨渠道最小预算适配（2026-10-15，实施前设计）

父任务明确授权本阶段通用跨模块离线开发。范围为5a9b7307＋既有low补丁的独立副本，不改原仓库或实验。

- 显式已启用task-token-budget-v1任务使用原持久账本和完整原计数；无标记的既有任务保持兼容，不自动初始化或视为受1M保护。真实实验仍须另行批准、绑定来源和剩余预算，不能由代码默认生成新预算。
- 复用旧task_budget的锁、原子落盘、usage校验、未知阻断与预算拒绝。每次真实网络尝试（Go重试/官方回退/Luna Responses）均单独预约最终发送payload的UTF8字节加输出cap，保守估计不当精确tokens。
- payload cap取现有渠道cap与任务cap更小值，不提高模型cap、不改low。Chat和Responses共同结算prompt+completion/total；reasoning不另加。
- 成功和带有效usage的失败均累计；无usage、损坏usage、超额、持久化失败不得触发渠道重试或回退。任务预算异常与普通RuntimeError严格区分。无usage不能补零，即使HTTP401/503。
- 原返修HTTP门保留。先过原HTTP门，再预约Token；Token拒绝可能已占原HTTP门的保守发送计数，但不计成实际网络请求。跨两账不能伪装原子提交，不返还不确定计数；证据区分实际发送和持久预约。
- 不迁移旧reasoning_details去重：新版只续传reasoning_content，无双表示。保留完整思考、工具调用/结果配对。
- 不在本阶段发模型、取认证、启动容器、改冻结账，或声称完整任务≤1M已达成。累计73HTTP/2746096 known/3 unknown/219060非actual占额保持。

验证冻结：真实MockTransport穿过生产入口，覆盖Go Chat、原渠道回退、Responses、已知失败结算、未知阻断、预约拒绝、额度/原账身份保持；旧task_budget全套原测试原样复跑。既有模型/Go/Worker回归必须保持。

## 已实施及验证（06:22 UTC）

实现文件：task_budget.py（从已测旧支线复用，新增锁内expected_budget_id核验）、token_transport.py、model.py、opencode.py、contracts.py、worker.py。代码不创建真实账，原累计历史未迁入新空账。显式实验入口call_experiment要求既有budget_id；普通未启用任务保持旧协议。

已复跑专项205 passed、全套581 passed/4 failed，四项为修改前同样的离线网络/浏览器环境限制。原低配置主线全套530 passed/4 failed作为前置基线保留。35个持久预算测试包含并发预约、未知恢复、损坏/落盘失败；新增真实MockTransport测试含Go/官方回退/Responses、usage含reasoning、不清旧消费、无账/换账/消失、取消unknown、Worker不得换模型。

失败记录：首轮199专项通过后加身份核验时误将expected_budget_id代码插入report，导致13测试失败；已移除该无关插入，原失败日志保留。独审发现require_bound后第二load返回None可降legacy，已改显式绑定不得早退并加入该竞态反例。0621冻结版继续独审；作者通过不等于已验收。

限制：原HTTP返修计数和Token账不能跨文件原子提交，原HTTP门先记数而Token门拒绝时会保留保守原HTTP占额；不会因此真实发HTTP或回退，但计数不能称精确已发送量。Token未知即停，取消保留send_unknown，不能回收为0。实际供应商若超约束仍如实记账并停，不能以预约字节当精确tokenizer。

尚未实施：旧上下文控制自动压缩与源码工作集迁移、研究总账连续性审批合同、强制完整响应保全及安全执行隔离。真实外发Go及其官方回退尚无本阶段授权；OpenRouter旧许可不能自动移用。
