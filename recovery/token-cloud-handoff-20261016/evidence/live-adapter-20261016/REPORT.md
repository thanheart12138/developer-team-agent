# 显式官方直连适配器（2026-10-16 UTC）

## 结果和范围

新增 backend/app/runtime/live_token_transport.py 的 call_approved_direct 入口，复用 controlled_transport 的同一 payload、预约、响应保全、结算和正常结果消费链。真实适配代码已实现；默认未注册生产调用者、授权核验器或凭据加载器，当前未执行任何真实HTTP。没有修改旧来源账、原实验、配置或凭据，无外部模型、用户Codex、容器、安装、Git提交/推送。

受控旧入口仍仅允许 mock_only + 精确 MockTransport；仅设置 live / live_explicit 或传普通HTTPTransport不能通过旧生产入口。新显式入口只接受 direct，精确端点 api.deepseek.com/chat/completions + deepseek-flash，或 openrouter.ai/api/v1/chat/completions + openai/gpt-6-luna。没有Go、Kimi、OR DeepSeek、回退或自动重试。真实连接由必需的open_approved_client工厂沿用已核准网络策略；network_policy_id进入授权核验范围。没有默认真实客户端或强制直连，缺网络策略/工厂就拒绝。请求显式follow_redirects=False。

## 授权与连续性边界

核验器为受信任应用代码回调，不是防恶意Python的安全边界；没有“不可伪造许可对象”或自制权限系统。普通JSON/布尔不能作为回调核验成功。真正权限来自获准操作者和平台；测试lambda不可以充当生产许可。核验器必须验证当前授权、唯一路由/模型/cap、最终payload摘要、最新完整跨环境及分供应商账、子账摘要、未知/保留量以及单写入者条件。此上层集成尚缺，不宣称真实就绪。

旧offline_only合同不变，仅用其经过审核的连续记账算法；不修改live_authorized标志、不把离线合同升级为许可。上层核验在认证前及发送前分别执行，并检查其间子账是否改变。输出cap只能收窄已有子账；未初始化/重置历史余额。失败可能已发送则记录尝试并保留unknown/pending，不能记作零；已知失败仍结算。最终payload扫描认证值，响应用同一认证值扫描，扫描前不输出增量。

## 实测（全部离线）

使用既有隔离.venv，env -i清空环境、test-guard禁止socket/DNS/容器，内存SQLite及临时合成账。新入口测试在HTTPX Client构造处替换为MockTransport，初版断言原参数是标准真实传输（transport=None）、禁环境代理/重定向；独审后改为验证必需的获准网络工厂/策略，未再对真实分支强制禁环境代理。所有版本均无真实连接。测试生成的route.json中live_explicit/attempted字段仅为接线fixture，不是实际HTTP账本。

1. 首次：65通过、1失败、130警告。失败是合成回显fixture用裸字节ok替换，连tokens键内的ok也被改坏，导致usage未知。保留first.log，修为只替换JSON字符串"ok"，不改产品usage规则。
2. 扩展后：70通过、138既有SQLAlchemy弃用警告；包含新24项及旧46项，second.log。
3. 预算/连续账/响应保全/运输合并回归：160通过、178警告，regression.log。70是160的子集，不能合计230。未运行全套，历史654通过/4环境失败仍是修改前记录。

覆盖两供应商正例、路由/模型/cap非法、Go拒绝、默认无核验器、JSON/布尔伪许可、认证缺失、发送前撤权、认证期间子账变化、配置实际路由偏离、请求秘密拦截、响应回显保留已知usage但拒绝执行、未知阻断下一次、连接失败不重试、302不跟随。

## 当前真实阻塞（存在性检查，未读取凭据内容）

当前候选相对配置路径secrets/deepseek_api_key和secrets/openrouter_api_key均不存在；SIMULATOR_DEEPSEEK_API_KEY / SIMULATOR_OPENROUTER_API_KEY及常见DEEPSEEK_API_KEY / OPENROUTER_API_KEY环境变量均未设置。此结论只覆盖当前候选及当前进程，不能推断用户Mac没有凭据，也未验证其他已有安全连接。

需要上层通过支持的安全连接提供上述二选一路由现有认证；不得让用户在聊天贴密钥。需要核实Mac最后保存截点后的最新完整账与供应商归属，保持原子轮边界、所有失败重试和未知。当前73HTTP/2,746,096已知（输入2,361,313，输出384,783）、3历史未知、219,060非实际保留量的原报告未改。不得从该旧截点推导今天可花余额；各供应商1000万授权不覆盖原子轮边界，也不让unknown变零。

## 下一步

由上层核对安全连接、当前完整账、供应商累计/未知处理和原子轮余额，安装真实的授权核验器与认证加载器后，显式调用call_approved_direct完成既有547773失败修复的针对性真实验证。当前仅接线和离线机制验证，15项产品验收未执行，完整同范围同质量≤100万Token未证明。没有旧baseline重发或节省率宣称。

## 独立审查后的修复（07:44–07:45 UTC）

独审发现初版真实分支强制trust_env=False，可能忽略现有获准代理/证书路线。已去掉真实分支的默认HTTPX构造，要求上层open_approved_client(endpoint,timeout)复用已核网络策略，network_policy_id也进入scope；缺工厂/策略拒绝。工厂属于受信任上层，必须核TLS/代理/证书、零重试及不绕开网络限制；单纯声明ID不是网络已核证据。Mock分支继续忽略环境以隔离测试。初版报告副本保留于REPORT.pre-review.md。

独审另发现既有settle先写Token账而在未知/超额时抛出，导致第二HTTP账未保存结果。改为try/finally，确保HTTP账保存同一usage/status，仍传播停止异常。两账并非跨文件事务；崩溃/写盘故障仍需保留pending并对账，不宣称原子双账。新测试实际同时初始化临时repair-runtime和Token账，未知及已知10003超额均验证两账落盘、只一HTTP且停止。

新增4项后定向回归164通过、186既有警告（含先前160，不能相加）。日志review-fixes.log。实际命令：

从mainline-low-candidate运行：env -i PATH=/usr/bin:/bin HOME=/tmp PYTHONPATH=/workspace/scratch/fde72c226373/token-recovery-20261015/test-guard:. ../.venv/bin/python -m pytest -q tests/test_live_token_transport.py tests/test_controlled_transport.py tests/test_token_offline_runner.py tests/test_task_budget.py tests/test_token_lineage.py tests/test_token_response_evidence.py tests/test_token_transport.py

网络守卫是上述PYTHONPATH加载的test-guard/sitecustomize.py，不是测试文件自身建立。它的审计钩子拒绝socket.connect、socket.getaddrinfo及容器Popen。测试中Client另外被Mock替换。所有合成route记录不并入真实73HTTP原账。

最终独立只读复核确认网络策略与双账两项修复成立、164通过日志及外部禁网守卫命令可核，未见新增适配器阻断缺陷。仍没有生产工厂/网络策略、真实完整账核验器，默认关闭；这不是实际调用放行。

164项组成（只收集核对，没有再执行测试）：新live适配28、controlled_transport38、offline_runner8、task_budget35、token_lineage14、response_evidence27、token_transport14。
