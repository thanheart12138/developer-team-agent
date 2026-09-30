# OpenRouter GPT-6 Luna 真实调用探针（2026-09-24）

## 范围与预期

- 用户自行放入真实 OpenRouter Key；探针只通过 Runtime 的受控密钥读取函数传给 HTTP 认证头，不输出密钥。
- 模型为 `openai/gpt-6-luna`，推理强度 `high`，地址为 `https://openrouter.ai/api/v1/chat/completions`。
- 一次流式工具调用探针，最多 512 个完成 Token；工具只供模型返回参数，不执行任何文件操作。若失败，再用一次最多 128 个完成 Token 的非流式短请求读取服务端错误正文。
- 预期：HTTP 成功、流式响应能解析出一次 `probe(code="OK")`；诊断请求仅用于定位失败。

## 实际结果

1. 2026-09-24，流式请求到达 OpenRouter 后返回 HTTP 403；未获得模型内容、工具调用或 usage。现有流式 HTTP 错误路径没有读取错误正文，因此该次请求本身没有可用的详细原因。
2. 同一 Key、模型、推理强度和地址的非流式诊断请求仍返回 HTTP 403。服务端 JSON 错误码为 `403`，消息为 `This model is not available in your region.`；未获得模型结果或 usage。
3. 总计两次 HTTP 请求，没有执行模型工具、写入生成产品或修改正式 Worker 路由。认证内容未写入源代码、Trace 或本证据。
4. 用户要求重试后，又发起一次非流式短请求：同一 Key、模型 `openai/gpt-6-luna`、推理强度 `high`，最大完成 Token 512，预期只回复 `OK`。仍返回 HTTP 403、错误码 `403` 和 `This model is not available in your region.`；`model`、`choices`、`usage` 均未返回。本次只增加这一次 HTTP 请求，总计三次。
5. 用户提出本地代理 `http://127.0.0.1:7890` 后，沙箱外 `curl -x` 请求 OpenRouter 首页返回 HTTP 200。随后使用同一 Key、模型和推理强度，通过显式 `httpx` 代理发送一次非流式短请求，最大完成 Token 512，返回 HTTP 200、模型 `openai/gpt-6-luna`、`finish_reason=stop`、内容严格为 `OK`。服务端 usage 为输入 31、输出 26（其中 reasoning 19）、总计 57 Token，报告成本 0.0000161 美元。没有传工具定义或执行工具。
6. 用户授权 OpenRouter Runtime 读取环境代理后，先将 `trust_env=True` 用于 OpenRouter；真实探针在创建 HTTPX 客户端时遇到本机另设的 SOCKS `all_proxy`，因缺少可选 `socksio` 而抛出 `ImportError`，请求未发出。随后改为优先从当前进程的 `https_proxy`／`HTTPS_PROXY` 取代理地址并显式传给 HTTPX，仍启用 `trust_env=True`；无 HTTPS 代理时退回直连并关闭环境代理读取，不新增依赖。DeepSeek 与 Kimi 保持 `trust_env=False`。
7. 修正后用新 Runtime 在当前 `https_proxy=http://127.0.0.1:7890` 环境中真实执行一次流式工具调用，最大完成 Token 512。返回模型 `openai/gpt-6-luna`、`finish_reason=tool_calls`，程序解析到唯一 `probe(code="OK")`；没有实际执行工具。usage 为输入 80、输出 18、总计 98 Token，服务端报告成本 0.000017 美元。模型 Runtime 单测 16 项、全量后端 213 项通过。

## 结论与限制

- 显式代理下，真实 Luna high 最小文本请求通过；先前三次直连均因地区不可用返回 403。对照结果支持请求出口路径是阻塞因素，但服务端没有披露具体地区判定规则。
- OpenRouter Runtime 现已通过当前进程的 HTTPS 环境代理完成真实流式工具调用并解析参数；DeepSeek／Kimi 的代理行为未变。运行 OpenRouter 的新进程必须带有相应环境变量，现有已启动进程不会自动继承终端后来设置的变量。
- 多轮工具续传、正式返修和生成软件验收仍未验证。先前三次 403 未返回 usage，仍不能据此断言其费用。

协议参考：[OpenRouter Chat Completions 文档](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion) 。
