# 受控模型传输接入：默认关闭

## 已实现范围

`ControlledTransport`是显式的实验合同。默认mode为disabled；目前唯一可执行模式是mock_only，且只接受httpx.MockTransport本身。没有live开关、凭据加载、真实连接构造或自动重定向。模拟handler是测试代码，不是运行不可信代码的沙箱。

合同绑定历史连续账的路径/hash、已有budget_id、唯一channel/provider/model/endpoint和明确输出cap。cap不能超过既有任务账。渠道只有direct和go，provider只支持deepseek/openrouter；不默认纳入Kimi或全产品链。Go是离线格式/传输测试，不代表已有发送授权。

真正调用路径为runtime.call → call_preferred的显式受控分支 → call_selected固定渠道 → ChatCompletionsRuntime或OpenCodeRuntime._call_direct的受控分支 → HTTPX内存transport → 已审响应保全 → 正常runtime._finish。没有经过默认Go重试或官方fallback。任何受控错误继承TaskBudgetError，Worker不能用换模型恢复。

## 顺序保障

- 在凭据、写入或连接前校验启用模式、传输类型、来源合同、预算身份和路由。
- 每个请求独占证据目录，不覆盖旧结果；记录明确模拟route和actual_network_http=0。
- 用生产build_payload构建并收窄cap，真实预算模块按最终JSON字节保守预约；旧repair HTTP门仍保留。
- SSE先有界完整接收/严格帧聚合；Responses有界读取并严格校验；已知usage独立结算。
- 只有保全完成、内容安全、usage明确且连续账重新验证后，才调用正常_finish写模型消息和解析动作；不在扫描前流出on_delta。
- 未知usage阻断再调用；取消保留pending；不把可能已发送的预约释放为零。所有模拟账与原始来源分离。

## 验证及未完成项

初版16项生产路径测试通过，含四条显式路由、禁用/伪live/错误endpoint或模型/超cap、坏终态保留usage无fallback、新未知、取消和非法Responses参数。与已有预算/连续链/响应保全合并114项通过。初次独审找出保全后路径重读和Responses断流丢已知usage两项缺陷，已保留失败日志并修复。消费改为同FD核根inode、当前gate持有的manifest摘要、正文摘要后直接解析该次字节；Responses断流强制不接受但保留已核usage。四路增加替换和ReadError测试，作者24项，合并既有链与4项独立反例126项通过。最终0650独审10项hash一致、受控28项与保全58项回归通过；作者全量654通过、同4项环境失败（5896警告）。根目录run-offline-validation.sh已执行135项通过，含两阶段共13个独立反例。独审报告见offline-validation/independent-controlled-transport-audit-20261015.md。普通兼容路径未全局禁网；当前受控分支通过不等于任何live授权或完整任务验收。

如果未来允许真实测试，还需设计单独的live授权与连接注入机制，核实当前实际路由和完整累计余额，并解除父任务暂停。当前代码不能因设置mode='live'或传入普通HTTPTransport就发出请求。连接、模型服务可用性和真实任务质量均未验证。


## 2026-10-16 认证扫描参数接线专项

旧缺陷：受控请求头和Chat SSE使用调用侧合成认证值，但Responses的保全函数仍固定使用离线runner模块的FIXTURE_SECRET。替换调用侧合成值后，Responses正文和原始JSON额外字段内的回显可能未被阻断。这是不同协议保全参数未贯通的机制缺口，不是已发生的真实凭据泄露；本次只使用合成值。

最小修复仅涉及controlled_transport.py、token_offline_runner.py及test_controlled_transport.py：_responses显式要求scan_secret，离线fixture传其合成标记；受控调用将同一个局部auth_secret传给认证头、SSE门和Responses保全。不新增框架、依赖或真实连接入口。

验证过程与计数：
- 修改前先加入14例并执行，6失败／8通过；6失败均为Responses回显未被拒绝。
- 修复后只运行test_controlled_transport.py及test_token_offline_runner.py：46通过，86条既有SQLAlchemy弃用警告。涵盖正文／原始实体、明文／URL编码／base64回显，保全已知usage、拒绝执行且证据不保存秘密，以及安全响应正例。
- 独立审查通过；独立运行14例是上述46中的子集，不加成60例。
- 上一节654通过／4环境失败是修改前历史全套；本次未运行全套，不宣称改后全套已通过。

新增证据保存在恢复根目录offline-validation/auth-scan-20261016/，含REPORT.md、before.log、after.log、auth-scan.patch、manifest.json及修改前三文件副本；旧日志、历史组合补丁与旧交付包未覆盖。补丁相对当前恢复候选而非原Git基线。独立审查另核原恢复ZIP与provenance一致，当前原账及enabled标记与ZIP对应条目逐字节一致；旧terminal清单是更早快照，不用于本次改动判断。

边界：测试使用已有隔离环境、清空环境变量、禁止socket／DNS／容器的守卫、内存SQLite、临时合成账和MockTransport。默认disabled、live硬拒绝、offline_only合同均保持；未读真实凭据，新增真实模型HTTP为0。仅离线机制实现与专项验证成立，真实连接、模型接受性、产品验收和完整同质量≤100万Token仍未验证。


## 2026-10-16 显式官方直连适配器追加

用户要求继续后实现live_token_transport.call_approved_direct，复用同一预算预约、响应扫描/保全和结算链。只支持DS官方deepseek-flash及OR openai/gpt-6-luna，默认无生产核验器/认证加载器；标准TLS、禁环境代理/重定向，无Go/Kimi/回退或重试。实际权限由获准操作者/平台及上层当前账核验保障，回调/Python对象不是安全边界，旧offline合同不升级为许可。最终payload及子账摘要绑定、认证前和发送前再核验，认证回显拒绝执行、已知usage仍计，未知即停。

新增24离线接线用例与旧46项共70通过；扩大预算/连续账/响应回归160通过（70为子集）。初次65通过1失败为fixture裸ok替换破坏tokens键，已保留失败并修fixture；本次未跑全套。所有HTTPX连接被内存Mock拦截，另有socket/DNS禁网守卫，真实HTTP新增0。代码/文档仅本地候选，无提交/推送。

当前候选DS/OR认证文件不存在，相关环境变量未设置；只查存在性，未读取真实凭据。安全连接及Mac保存截点后的完整账/分供应商归属、子轮预算连续性仍缺。原73HTTP、2,746,096已知、3unknown及219,060非实际保留量不变，不恢复旧余额。真实接线实现不等于真实就绪，完整同质量≤100万和15项产品验收未证明。详细证据在恢复根offline-validation/live-adapter-20261016/REPORT.md。


### 同日独审修正：获准网络路线与双账结算

初版强制禁环境代理不能证明沿用获准网络路线；现已改为真实入口必须提供open_approved_client及network_policy_id，缺任一即拒绝。由受信任上层核实并沿用现有代理/TLS/证书及零重试策略，不提供默认真实网络、不绕开访问限制；请求禁止重定向。Python回调或策略ID本身不是安全边界/授权证明。

同时修复共用settle在Token未知/已知超额抛出后跳过HTTP账结算的问题：finally仍保存同一usage/status，然后保持停止。新增两账同时存在的反例及缺网络策略测试，最终164定向通过、186既有警告，含前160项。两账不宣称跨文件原子事务，进程崩溃/存储故障仍需保留pending对账。上述初版网络描述以本段为准，失败及初版证据保留。真实HTTP仍0，无最新安全连接和完整连续账时不执行。
