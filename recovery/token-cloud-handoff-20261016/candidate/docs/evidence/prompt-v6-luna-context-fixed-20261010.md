# Luna工具历史修复后真实验证

## 范围

用户要求先试Luna，新最多8HTTP含失败重试。同一50输入文件hash与原缺陷起点、最新v6 hash 8d31af0339453d8cb7d383ad417f4c5809cbade2aea98ab7b54b2137c04bc7ef、相同工具和原固定验收。已有OpenRouter适配器model=openai/gpt-6-luna、reasoning medium，显式进程代理7890。仅隔离供应商初始化／绑定及运行时替换，正式路由与预算逻辑保持；本轮使用已修复通用历史传递。原预检沿用来源并核对hash，不冒充重新预检。

## 已执行结果

实际7／8HTTP、159,402Token、未知用量0，成本核对一致，52.4秒包含系统流水线及独立复测，无人工干预。第1固定全量自测失败并搜索；第2搜索；第3—4读取必要正文；第5同批update_plan与两处replace；第6固定全量自测150项通过；第7主动verify_and_submit显式提交，系统到awaiting_acceptance。原目标需用户验收，不自动认定软件全部需求完成。

独立副本恢复原固定Node测试及原verify_product.py，Node150／150通过，真实浏览器exit0、ok true、problems为空，包含编辑保存、列表更新与重新打开三字段断言及其他模块回归。只改topics.js与verify_product.py，baseline保持。真实调用预算、SQLite、检查点、Trace、成本、独立复测和结果均保存workspace/experiments/prompt-v6-luna-context-fixed-20261010。剩余1HTTP不挪用、不追加。

## 上下文与判断

逐份实际发送体核对模型与medium参数，所有assistant工具调用ID和tool结果成对，后续请求有历史工具消息，无DeepSeek思考字段，context-audit.json保存计数来源。这证明上下文修复实际生效，不只是离线夹具。

原Luna缺历史样本8请求（1未知）0修改；本轮第5修改、第7提交。先前样本有中断及用户重试，本轮无干预，不能称严格A/B或精确归因，但实际完整信息下Luna可以完成此断点。不能再用旧缺历史失败证明Luna执行能力不足。

本轮159,402Token高于此前DeepSeek成功样本120,180，也高于DeepSeek最新未提交样本142,245；模型／协议不同、完成状态不同，不据此宣布哪个模型更省成本。先守住完成，再评估冗余往返。单样本不证明稳定成功率，Kimi修复后未真实测试、v5未重跑，正式active仍v5、v6未激活；012整体仍待版本评测／验收。
