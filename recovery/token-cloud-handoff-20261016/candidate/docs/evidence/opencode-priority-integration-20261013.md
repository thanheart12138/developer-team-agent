# OpenCode 优先渠道接入与验证

## 范围与当前状态

用户确认 DeepSeek、Luna、Kimi 优先使用 OpenCode，技术失败回退原渠道。已实现，机制已验证；真实模型调用、正式运行实例加载及用户验收未验证。未修改凭据、`.env`、数据库结构、提示词注册表或既有实验，不提交、不部署。

参考实现来自 ai-3d-model-creater 的 tools/owned025_optimization/opencode_wire.py、opencode_credentials.py、opencode_smoke.py，以及用户指定的临时生成 HTTP 适配器。只读取源码，未复制该项目的部署／账本。已打开核对 [官方 Go 文档](https://opencode.ai/v2/docs/console/go/) 和 [模型列表](https://opencode.ai/v2/docs/console/models/) ：Go 支持三个目标模型，要求项目 User-Agent 和稳定会话头；Kimi K2.7 Code 的 ID 为 kimi-k2.7-code。官方资料与参考代码不代替本项目真实请求验证。

## 实现

- OpenCode 实际模型为 deepseek-v4.1-flash、gpt-6-luna、kimi-k2.7-code。Kimi 模型发生变化，不声称与原 kimi-for-coding 等价。
- Chat Completions 复用原流式工具解析，Go 缺少 DONE 时拒绝；Luna 使用非流式 Responses，转换函数定义、历史调用／结果与响应，保留 call_id、原响应和用量。
- 优先读取 secrets/opencode_api_key 或同名 textClipping；错误使用固定码，不输出密钥。可指定已有文件，未复制或修改真实凭据。
- 每个 OpenCode 请求带 ai-agent-product/1.0 和稳定会话标识。Worker 使用任务、StepRun、history_key，独立调用使用任务与工作区；重试保持。
- OpenCode 暂态错误最多三次，认证／配置／协议失败立即回退。外层 Worker 重试同一逻辑请求时继续原渠道，不重置 Go 的三次额度；下一逻辑调用重新优先 Go。预算耗尽直接停止，业务结果不触发回退。
- 两渠道发送均预约现有实际 HTTP 账本。实际渠道／模型／失败另存 model_transport Trace 和响应，逻辑阶段身份保持。原 Kimi→DeepSeek 降级仍保留。
- 旧固定模型返修会话和旧固定目的地评测保持原授权；新返修会话明确 channel_policy，新评测必须同时批准 OpenCode 和原渠道回退目的地。

## 验证

新增 tests/test_opencode.py 的十五项机制用例覆盖：两个 Chat 模型优先路由、稳定头、Luna 历史与函数调用映射、401／429／503 回退、预算耗尽拒绝、剪贴文件与安全错误、旧会话保持、截断流拒绝、新旧评测授权、双渠道共同计数、无凭据不发送，以及外层重试不重置 Go 额度。

最终定向命令：`.venv/bin/python -m pytest -q tests/test_opencode.py tests/test_model_runtime.py tests/test_prompt_real_evaluation.py tests/test_repair_session.py --disable-warnings`。

结果：85 项通过，1 项已有提示词案例失败。该失败在读取 contract.role 时触发；只读核对发现现有 92 份案例缺少此字段，92 份案例只有 normal，不满足另一个旧测试要求的 boundary／counterexample。两项相关测试文件与 HEAD 完全一致，本次未修改这些案例或注册表。

全量回归：525 项通过、6 项失败。四项为沙箱拒绝端口监听／服务启动（Operation not permitted），两项为上述提示词案例契约。失败项分别为 test_worker_static_server_accepts_module_connection_burst、test_all_seed_cases_are_valid_and_reference_fixtures_do_not_claim_model_success、test_all_component_payloads_use_registered_parent_and_tools、test_program_pipeline_uses_real_node_http_and_no_planner、test_real_browser_pipeline_waits_for_user_without_model_review、test_static_preview_switches_snapshot_without_changing_origin。未绕过这些测试或修改提示词案例。

网络预检：本地 8001 health 与 OpenCode models 均被当前执行环境拒绝连接，HTTPX 报 ConnectError；未发送模型生成 POST，新增真实模型 HTTP 为零。lsof 只读观察 8001 原 API PID 为 44801；ps 被沙箱拒绝，不能核对运行中任务，也不能安全重启。原服务保持，不宣称已加载新实现。

最后修正请求 Trace 保存实际首选渠道 payload 后，OpenCode／原模型协议／返修会话／Worker 事件集合 151 项全部通过；编译检查与 git diff --check 通过。历史协议测试显式关闭新渠道，仅验证原渠道；十五项新用例显式启用 OpenCode，不用旧夹具冒充 Go 证据。

## 待验证

在允许网络和进程访问的环境，核对正式任务是否空闲后重启 API／Worker；三个模型各执行至多两次 HTTP、单次输出至多 512 Token 的工具调用／结果续传验证，总上限六次，现场存放 workspace/experiments/ 下并先写目录约定与累计计数。不得恢复旧任务、重置旧预算或将连接成功当成完整软件生成能力验收。本次未创建或启动该真实实验。
