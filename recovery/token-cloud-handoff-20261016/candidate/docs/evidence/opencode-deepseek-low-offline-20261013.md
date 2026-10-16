# 后续DeepSeek low：项目配置与离线验证（2026-10-13）

用户明确要求「后续改成 low 吧」。仅独立Token副本checkout-local修改，HEAD仍5a9b7307a435e5a83a3a505a7a2c6bd6f0e91563，变更未提交／未推送。

配置位置backend/app/config.py：deepseek_reasoning_effort默认low，Settings允许low／high，按已有启动机制可使用SIMULATOR_DEEPSEEK_REASONING_EFFORT覆盖。未修改.env、认证、安全设置、全局配置或Fast；原仓库、旧Token实验及账本不动。OpenCode Go DeepSeek build_payload使用此配置，实际Mock发送reasoning_effort=low；不再硬编码high。官方默认deepseek-flash及已核deepseek-v4-pro回退采用同一字段，thinking仍enabled。Luna medium、Kimi、模型选择、预算、Go max_tokens32768及原渠道现有cap策略保持。

[DeepSeek官方Chat API](https://api-docs.deepseek.com/api/create-chat-completion/) 明确reasoning_effort支持low／high／max等，low仍启用thinking，故已核官方模型直接使用low，无需猜测映射。当前[OpenCode Go官方文档](https://opencode.ai/v2/docs/console/go/) 列出DeepSeek V4.1 Flash；未用真实API确认其low服务端接受性与效果，只验证实际构造／Mock发送字段。未知自定义或旧模型ID不注入未经核对字段，保持原thinking，不能承诺为low。

必要离线集合tests/test_opencode.py＋tests/test_model_runtime.py：37 passed／66既有datetime warnings／0.44s。新增3项覆盖项目默认、环境覆盖与非法值拒绝、Go／官方支持模型及未知模型边界、真实Mock跨渠道发送体。无真实模型HTTP、未启动产品、未重启正式服务，不把离线配置生效说成当前正式运行实例加载或真实思考Token收益。

同步时clean状态保留为历史，当前因本low变更为dirty，见low-git-evidence.json及low-change.patch；没有自动提交。原8HTTP／新增1M／累计10M历史责任保持，本阶段不花剩余额度。此前旧OpenRouter规范化补丁仍单独保留，不在本次low配置中移植。
