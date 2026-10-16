# 新返修取消独立模型审查验证

## 用户确认的决定

仅新 repair-v1 尝试采用 `validation_policy=tests_and_browser`。模型显式提交后，程序冻结版本，执行全量测试、启动和实际浏览器验证，通过后等待用户验收。取消独立模型目标／覆盖审查及其调用预留，总 HTTP 上限保持不变。

原始目标在验证通过后仍为 open；只有用户批准匹配提交／版本时，才以 `verification_source=user_acceptance` 和验收事件 ID 记录关闭依据。不生成虚假的模型覆盖结论。旧尝试、原授权文件、审查记录和绑定提示词保留，不自动迁移或续跑。

## 实现与验证

- repair_runtime：新策略和零审查预留，三阶段验证直接到 awaiting_acceptance；旧尝试保留原审查契约。
- repair_session：新提示词移除独立审查承诺，当前事实只列测试和浏览器验证；旧提示词按哈希绑定恢复。
- repair_objectives／worker：校验用户批准的提交及版本后，记录用户验收关闭原目标；拒绝不关闭。
- 五组相关回归最终 117 项通过，18.82 秒。命令：`.venv/bin/python -m pytest tests/test_repair_runtime.py tests/test_repair_session.py tests/test_model_runtime.py tests/test_context_relay.py tests/test_tool_summaries.py -q --disable-warnings`。
- 真实 Node／本地 HTTP／Chrome 合成夹具通过，审查调用被设置为一旦发生即失败；目标在待验收时仍 open，用户批准后才关闭。验证总预算可用到上限且超限拒绝、新策略 reviewing 阶段禁止模型调用、旧预留和旧审查行为保持。
- 首次受限环境两项监听测试遭权限拒绝；在允许本地监听的环境复验通过，没有绕过断言。
- 原三个跨模块断点只读核查：13／25／11 次计数及 runtime 字节不变，原提示词绑定可恢复。报告：`workspace/experiments/material-cross-module-progress-comparison-20261009/no-model-review-binding-check.json`。

## 本地服务加载

先核对任务空闲及原进程身份，再加载 API 96441／Worker 96442，health 成功。正式状态、schema、文件状态、产品哈希及旧实验计数五项指纹不变；旧 Task26 未迁移。

控制与前后快照位于 `workspace/experiments/formal-service-recovery-20261003-4caius6l/`，文件前缀 `repair-v1-`、后缀 `20261009-no-model-review.json`；控制脚本为 `no-model-review-reload-20261009.py`。

## 边界

本次新增模型 HTTP 调用为零。验证的是流程、预算、历史兼容及实际本地浏览器机制，不是新策略下真实 DeepSeek 的成功率或 Token 收益。历史七轮实验均包含模型审查，数字不重算；上一轮审查 53,111 Token 不能直接当未来必省金额。取消审查后，需求是否完整由固定验证证据及用户验收判断，测试通过不会自动关闭业务目标。未代用户验收，没有提交或推送代码。
