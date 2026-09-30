# DeepSeek thinking 真实调用续测失败断点

日期：2026-09-24。目标：开启项目正式 DeepSeek Runtime 的 thinking 模式，并在与 Luna 两次实验相同的 `topics-core` 失败状态下验证实际返修能力与工具续传协议。

## 协议与实现

- [DeepSeek 官方 Thinking Mode 文档](https://api-docs.deepseek.com/guides/thinking_mode/) 明确：Chat Completions 使用 `thinking: {type: enabled}`；带 `tools` 的后续请求必须完整回传前轮 assistant 的 `reasoning_content`，即使该轮没有工具调用，否则可能返回 HTTP 400。此前 Runtime 使用 `thinking: disabled`，也没有保存或续传该字段，不能只切换请求参数。
- 先更新当前 Dev Design，再启用 DeepSeek thinking。流式 Runtime 合并 `reasoning_content`，不作为用户实时文本发布；Worker 将其随工具响应存进检查点。DeepSeek 的工具消息单独续传完整的当前循环历史，同一响应的多个工具调用归为一条 assistant 消息；现有工具摘要／文件状态投影继续作为用户上下文。旧检查点缺少思考内容时不伪造，仍从现有文件和摘要恢复。强制继续的无工具响应也保存思考内容。
- 模型契约和全量后端回归 215 项通过；差异检查通过。没有修改 DeepSeek 模型 ID、Kimi/OpenRouter 路由或密钥。

## 相同失败状态的真实测试

- 脚本 `/private/tmp/deepseek_thinking_checkpoint_probe_20260924.py` 将原 DeepSeek 任务的 SQLite 和工作区复制到 `/private/tmp/deepseek-thinking-checkpoint-probe-20260924-40b86j4c`，从原 Trace 还原失败版 `topics.test.js`，并提供原失败自测反馈。原任务、原产品和正式服务均未改动。测试前 Node 相关测试复现 22 通过／1 失败。
- 测试进程使用项目 `DeepSeekRuntime`、`deepseek-flash`、`thinking: enabled`；最多 12 次模型 HTTP，单次最大完成 8192 Token；`topics-core` 通过后停止规划下一片。沙箱内首次尝试 3 次连接均为 `ConnectError`，没有有效模型响应或 usage；经允许的沙箱外网络重跑后执行成功。
- 成功运行共 3 次真实 HTTP／3 次模型响应。Trace 中请求均为 `thinking: enabled`；第二次带回第一次 7856 字符的 `reasoning_content`，第三次带回前两次 7856／19 字符的思考内容。工具序列是写 `product/js/topics.test.js`、`run_unit_tests`、`submit_unit_for_test`，随后程序独立运行切片 Node 测试。当前切片状态 `passed`。
- DeepSeek 仅修改失败测试的夹具：增加已有 `deleteMaterial` 公共接口导入，删除素材后检查删除成功、素材不可读、关联查询为空；移除在 Node 中无效的 `globalThis.localStorage` 直接操作。`topics.js`、`storage.js`、其他产品文件未变。测试仍为 12 项，断言调用由 60 增至 62，原双选题反向查询检查保留。
- 程序复验和独立复跑相关 Node 测试均为 23 通过／0 失败／0 TODO；独立全量 `node --test js/*.test.js` 为 49 项中 23 通过、0 失败、26 TODO。其余切片、启动、浏览器和用户验收未执行；Task 停在 `running / develop`，因为测试控制在当前片完成后停止。
- 服务端 usage 合计输入 66,044、输出 3,945、总计 69,989 Token。DeepSeek 响应未提供美元成本字段，本报告不推算实际账单。逐次 usage 和完整 Trace 位于隔离副本 `deepseek-summary.json`、`workspace/1/traces/develop/2/`。

## 判断边界

开启 thinking 并按官方协议续传后，DeepSeek 在这个失败断点完成了范围更小、测试覆盖保留更完整的修复。之前 `thinking: disabled` 的 DeepSeek 曾在相同失败项后重复读取直到无进展停止；但本次是从失败文件与反馈创建的新尝试，不重放旧 7 次读取历史，而且正式实现和历史上下文不同，不能把成功单独归因于 thinking，也不能据单样本断言总体模型能力或费用优于 Luna。Luna medium 同断点为 4 次／73,240 Token，Luna high 为 3 次／61,416 Token；三者仅供本场景观察。

正式 Worker 进程仍运行旧代码。本次尝试读取正式数据库中的运行中任务数时被 MySQL 拒绝认证，无法排除重启会中断任务，因此未重启服务；测试独立进程已加载并验证新实现。
