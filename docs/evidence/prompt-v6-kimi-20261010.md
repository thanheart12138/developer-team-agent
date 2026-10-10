# Kimi 同case真实流程与上下文差异

用户要求用Kimi走一次流程，沿用同缺陷、最新v6、工具与固定验收，新8HTTP含失败重试。50个原输入hash匹配旧预检，复用原红绿预检标明来源。隔离进程仅选择已有Kimi适配器并替换三处供应商固定值，预算预约保持；正式代码、路由、凭据与v5不变。实际model=kimi-for-coding，thinking disabled，max_completion_tokens8192，未启用未经授权的新参数。

## 实际结果

8／8HTTP、112,810Token、未知用量0、113.3秒含独立复测，无人工干预。第1主动固定自测失败，后续读取／搜索；0修改、无提交，budget_exhausted。全部50输入hash保持；独立原Node与浏览器exit1，原缺陷未修复。search的version／cursor不影响权限但反复定位同拼写错误，topics.js与verify_product.py多次重读。

## 不能据此比较模型能力：实际上下文不同

已实际打开本轮第1及第8发送体：Kimi仅system／user，没有assistant／tool历史；第8 current_requested_data仅上一批read片段，而不是所有已读正文。核对Luna最后发送体同样仅2条消息、0工具消息；同场景DeepSeek最后发送体为24消息、14工具消息。见workspace/experiments/prompt-v6-kimi-20261010/context-comparison.json。

这是复用当前框架时可复核的供应商上下文差异：同prompt／输入起点／工具不等于同信息可用性。先前仅替换模型运行时忽略此差异，不能把Luna／Kimi连续读取作为同条件模型失败；它们可能在补回没有重传的正文，需逐次检查内容后判断。DeepSeek本轮仍有完整根因与修法而继续读的证据，不被这一发现推翻。

尚未修复各Provider上下文传递、不增加调用，不倒改旧轨迹与报告。不把112,810与其他模型Token差异解释为效率提高，因为未完成且上下文不同。012仍未完成，下一步应先确认供应商上下文契约，再进行有效对照，而非继续堆提示词。
