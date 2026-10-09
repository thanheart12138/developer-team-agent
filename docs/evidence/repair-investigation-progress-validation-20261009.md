# 新返修调查推进规则：实现与机制验证

日期：2026-10-09。用户确认 [规则方案](repair-investigation-progress-review-20261009.md) 后实施，先更新有效Dev Design。本次零新增模型HTTP，不声称真实行为或成本优化成功。

## 修改

仅新返修主会话提示词增加：调查description说明具体未决问题及其影响；原因、批准接口和可实施方案有依据且无相关未决问题时优先修改自测；无关已有疑点先记录，有交付影响／设计冲突时继续调查或request_decision；独立读取与已确定参数的修改尽量合批，有结果依赖时分批。

保留必要调查、已知正文连续性、精确去重、预算、全量自测、固定独立浏览器／目标审查和模型显式提交。不新增读取次数门禁、description自然语言拒绝、自动提交、强制计划、模型摘要调用或schema。既有update_plan可选字段与正常动作合批使用，不作为完成前置。

repair_session.py保留原v2全文为PREVIOUS_PROMPT，旧legacy也保持。新会话选择新PROMPT，已建立会话仅按其原prompt_hash和context_contract选择已知原提示词；未知绑定或契约不匹配仍拒绝，不修改旧运行记录。原id／provider绑定检查继续执行。

## 验证

- 最终repair_session／context_relay／model_runtime／tool_summaries相关83项通过。实际固定响应主循环分别覆盖新提示词、原v2绑定及legacy：必要读取、自测复用和显式提交均仍可完成，没有强制进度调用；未知／错误契约提示词拒绝。
- 只读核查原跨模块和成本对照两份真实runtime，分别13／25次计数保持，原v2提示词哈希匹配并恢复PREVIOUS_PROMPT，原runtime字节不变；空会话选择新PROMPT。未恢复模型执行。
- 留存 `workspace/experiments/material-cross-module-cost-comparison-20261009/investigation-progress-binding-check.json`，新提示词SHA256为 `f3027aad7a5bfa0585a3fd4976a86210cc8b634a6e9ad73bd29fe8c74fade4cc`。
- 任务空闲及进程身份核对后API71674／Worker71675加载，health通过。正式任务状态、schema、文件状态、产品哈希及旧素材调用计数五项指纹保持，旧Task26未迁移。记录 `workspace/experiments/formal-service-recovery-20261003-4caius6l/repair-v1-reload-result-20261009-investigation-progress.json`。

机制测试中的响应是固定夹具，只证明新规则被提供、旧绑定不破坏、必要行为仍允许。模型是否遵循规则、定位到修改的轮数、补读、Token与真实交付成功率尚未验证。旧719,905Token成本倒退记录保持，不将提示词部署记为已解决。

未改产品、数据库schema、密钥或预算，未续跑旧任务、提交／推送；用户未最终验收。
