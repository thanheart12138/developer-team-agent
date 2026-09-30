# OpenRouter Luna high 真实调用续测 DeepSeek 失败断点

日期：2026-09-24。目标：在 DeepSeek 因 `topics-core` 自测失败后反复读取并触发 `unit_development_no_progress` 的位置，检验项目 `OpenRouterRuntime` 的 `openai/gpt-6-luna`／`high` 是否能完成当前切片。

## 起点与边界

- 原失败证据见 `docs/evidence/repeat-read-allowed-deepseek-20260924.md`。原 DeepSeek 测试根目录为 `/private/tmp/content-workbench-repeat-read-20260924`；该目录的 `topics.test.js` 已被上次定向返修改变，不能直接当作失败起点。
- 测试脚本为 `/private/tmp/luna_checkpoint_probe_20260924.py`。它复制原 SQLite 和任务工作区到 `/private/tmp/luna-checkpoint-probe-20260924-vut1kie3`，用原 Trace `000068-tool_call.json` 的写入内容还原失败版 `product/js/topics.test.js`，并以原 `000082-tool_result.json` 提供的失败自测结果作为新尝试反馈。原任务和正式服务没有改动。
- 新副本从同一失败文件版本和测试反馈继续，但创建新的 `develop` StepRun／切片尝试；没有将 DeepSeek 最后 7 次重复读取作为 Luna 的工具历史重放。因此这是失败状态的受控续测，不是原失败运行记录的原样恢复。
- 仅测试进程把 Worker 的模型创建函数指向项目 `OpenRouterRuntime`，请求体为 `openai/gpt-6-luna`、`reasoning.effort=high`。通过当前 HTTPS 代理访问 OpenRouter。最多 12 次模型 HTTP 请求、单次最大完成 8192 Token；在 `topics-core` 通过后停止规划下一片。正式 Worker 阶段路由未改变。

## 结果

- 调用前独立复现：`node --test js/storage.test.js js/materials.test.js js/topics.test.js` 退出码 1，23 项中 22 通过、1 失败；失败项仍是「getTopicMaterials 解析已删除素材时自动消失」。
- 实际 3 次 OpenRouter HTTP／3 次 Luna 模型响应。Trace 请求均记录 `provider=openrouter`、`model=openai/gpt-6-luna`、`reasoning.effort=high`；模型依次调用 `write`、`run_unit_tests`、`submit_unit_for_test`，随后程序独立执行切片 Node 测试。`topics-core` 状态为 `passed`。
- Luna 修改了生成产品的 `product/js/storage.js`：在 Node 环境里安装全局内存版 `localStorage`，让原测试夹具对全局存储的删除生效；失败版 `topics.test.js` 的 SHA-256 在调用前后均为 `ed70652f7aa9acb707e39b5606401f0669b1dfc94a1e5a4adeaf25e80b94c3ca`。相较于上次直接修正测试夹具的方法，这次改动触及共享存储层并引入 Node 全局对象副作用；测试通过不等于已确认这是更合适的长期实现。
- 程序复验及调用后独立复跑相关 Node 测试均为 23 通过、0 失败、0 TODO。独立复跑 `node --test js/*.test.js` 为 49 项中 23 通过、0 失败、26 TODO。其余业务切片、启动与浏览器验证未执行；Task 停在 `running / develop`，仅因为测试控制在当前切片通过后停止。
- OpenRouter 返回的 usage 合计：输入 52,960、输出 8,456、总计 61,416 Token；报告成本合计 0.010499785 美元。逐次 usage 与完整 Trace 在隔离副本 `luna-summary.json`、`workspace/1/traces/develop/2/`。沙箱内首次尝试在发出 3 次受限网络连接后以 `ConnectError` 失败，0 次有效模型响应；随后经允许的沙箱外代理运行得到上述结果。无证据表明首次尝试产生模型用量或费用。

## 判断

在这个明确的失败断点上，真实 Luna API 能驱动现有工具闭环完成当前切片，DeepSeek 上次没有完成。两次测试的历史上下文和读取拦截条件不同，且只有各一次样本，不能据此证明模型能力是唯一原因、Luna 的整体完成率更高，或 Token 一定更省。正式自动返修路由、多轮跨切片完成及用户验收仍未验证。
