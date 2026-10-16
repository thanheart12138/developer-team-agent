# OpenRouter Luna medium 真实调用续测 DeepSeek 失败断点

日期：2026-09-24。目标：在与上次 Luna high 相同的 DeepSeek `topics-core` 失败状态下，检验 `openai/gpt-6-luna`／`reasoning.effort=medium` 的真实返修结果，重点核对修改效果和成本。

## 方法与边界

- 用 `/private/tmp/luna_medium_checkpoint_probe_20260924.py` 复制原 DeepSeek SQLite 和工作区到 `/private/tmp/luna-medium-checkpoint-probe-20260924-ynf36_uw`；从原 `000068-tool_call.json` 还原失败版 `topics.test.js`，用原 `000082-tool_result.json` 的自测失败作为新尝试反馈。调用前 Node 相关测试复现 22 通过／1 失败。
- 沿用 high 实验的 Worker 切片工具流程、代理、12 次 HTTP 上限及单次 8192 完成 Token 上限；仅推理强度为 medium。`topics-core` 通过后由测试控制停止规划下一片。两次均为相同失败文件状态的新尝试，没有重放原 DeepSeek 最后的重复读取历史；单样本不能严格衡量模型强度的因果影响。
- 正式 Worker 模型路由、原失败任务和原生成产品均未改动。所有本次修改只在隔离副本中。

## 实际结果

- Trace 的 4 个真实模型请求均为 `provider=openrouter`、`model=openai/gpt-6-luna`、`reasoning.effort=medium`。工具序列为写 `topics.test.js`、写 `topics.js`、`run_unit_tests`、`submit_unit_for_test`；程序随后独立复验。切片状态 `passed`，相关 Node 测试独立复跑 22 通过／0 失败／0 TODO。全量 `node --test js/*.test.js` 为 48 项中 22 通过、0 失败、26 TODO。
- medium 识别到原测试夹具通过 `globalThis.localStorage` 操作素材集合在 Node 中无效，把失败项改为调用已有的 `deleteMaterial` 公共接口，真正删除素材后核对 `getTopicMaterials` 返回空列表。`storage.js` 未修改。这个方向直接修正了测试环境中的错误操作。
- medium 重写了整份 `topics.test.js`：测试项从 12 项变为 11 项，断言调用从 60 次变为 66 次；多项场景被合并或改写。其中「同一素材关联两个选题后，`getTopicsByMaterial` 同时返回两个选题」的原检查没有在新测试中等价保留，新测试只核对单个选题的查询。它还把 `topics.js` 中两行的 `ids` 临时变量改为内联调用，行为不变，对本次失败没有必要。这些额外改动使结果不能简单评价为最小修复，也不能只靠通过数量认定覆盖完全不变。
- OpenRouter usage 合计：输入 67,832、输出 5,408、总计 73,240 Token；报告成本 0.010660715 美元。逐次 usage 和 Trace 保存在隔离副本 `luna-summary.json`、`workspace/1/traces/develop/2/`。相同实验控制下，high 上次为 3 次 HTTP、61,416 Token、0.010499785 美元；本次 medium 是 4 次、73,240 Token、0.010660715 美元。单次差异不能推断档位的总体费用或成功率。

## 判断

medium 完成了当前失败切片，且选择修改错误测试夹具而非为它改变共享存储层；就本断点的修改方向而言，比上次 high 更贴近已查明的失败原因。但它重写了整份测试并顺手改了行为等价的实现代码，存在测试覆盖未等价保留的问题。其余 26 项 TODO、后续切片、启动和浏览器验证均未完成；正式自动返修路由与用户验收未验证。
