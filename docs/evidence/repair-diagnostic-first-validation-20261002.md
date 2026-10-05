# 切片返修先诊断：机制与真实调用验证

## 确认范围

用户「继续」确认此前建议：已有产物返修前，先由程序生成当前版本真实测试报告，再交给模型按错误修复。程序诊断仅提供反馈，不自动结束开发或替模型提交。先应用于切片返修；从零开发与普通单元入口不增加预先测试。

## 实现与机制验证

- 固定执行责任卡的 Node 测试，保存命令、真实结果和前后文件版本到 `evidence/slice-repair-diagnostic-{run.id}.json`，原始命令过程留存 Trace。
- 同一 Run、命令及完整版本一致时复用诊断；修改或缺文件不复用。模型默认收到失败摘要，可按需只读完整报告。
- 当前任务焦点优先采用模型自测，其次程序诊断，再其次旧集成报告；每轮标注版本是否适用，原报告和原始验收目标均保留。
- 诊断不设置 `UnitTools.self_test`，通过后仍需模型主动自测和显式提交。后续独立验证及目标闭合不变。
- Developer v11 增加诊断用途与边界，保留 v10。

定向命令：`.venv/bin/python -m pytest -q tests/test_slice_workflow.py tests/test_worker_events.py tests/test_unit_workflow.py tests/test_tool_summaries.py tests/test_prompt_registry.py --disable-warnings --tb=short`，190 项通过，29.32 秒。覆盖真实 Node 失败进入首轮、完整报告可读、原失败保留、诊断通过不允许提交、同版本恢复复用、修改使证据过期并重新诊断。模型入口观察使用 Fake，不能替代真实模型能力证据。

检查正式库 0 待处理事件／0 运行中任务后，重启 Worker：92956 → 5243，日志 `/private/tmp/ai-agent-worker-repair-diagnostic-20261002.log`。没有续跑旧任务。

## 一次真实小范围实验

源产物 `/private/tmp/repair-objectives-completion-deepseek-20260930`，20 个产品文件原样复制，SQLite 只读备份。隔离根目录 `/private/tmp/repair-diagnostic-deepseek-20261002-r94q4iem`。当前代码与 Developer v11，真实 `deepseek-flash` thinking enabled，调用实际 `slice_workflow.handle_repair`，新 StepRun 19／attempt 6。最多 12 次 HTTP，重试也计数；到真实自测与显式提交停止，不执行后续独立集成或目标关闭审查。

程序首轮真实 Node 退出 1，报告包含旧自建服务断言、旧 `--serve` 要求和浏览器成功输出的日志匹配失败。实际发送请求的 `current_task.latest_evidence` 为 `unit_diagnostic / failed / matches_current_files=true`，原 E4-1 保留，`needs_current_self_test=true`。原始集成报告同时存在。

## 真实结果与成本

| 项目 | 本次结果 |
|---|---:|
| HTTP／有 usage 响应 | 12／12 |
| 输入／输出 Token | 598,120／23,228 |
| 总 Token | 621,348 |
| 输入缓存命中／未命中 | 161,152／436,968 |
| read／replace | 16／4 |
| 成功工具动作／重复拦截 | 20／0 |
| 模型自测／提交 | 0／0 |
| 修改产品文件 | 2 |
| 耗时 | 109.94 秒 |

终态 `failed / develop / model_call_limit_exceeded`，outcome=`not_completed`。原 E4-1 仍 open，目标审查未执行，未完成开发交接或全流程。用量仅汇总 Trace ID 大于 933 的本次新增响应，不混入复制前成本，Provider 未报告美元金额。

前九次响应仅读取 16 个新范围；首轮准确读到 product.test.js 的 600—800、860—990 行和验证脚本首尾，之后仍逐段读完整验证脚本、main.js、装配、测试、说明。第十次才开始替换，第十至十二次共四次成功替换，修改 `product/verify_product.py` 与 `product/product.test.js`。请求十一、十二均正确显示诊断 stale、next_action=run_unit_tests，模型继续修改而未自测。没有被读取保护或错误版本状态拒绝修复。

修改方向是取消旧自建服务要求，并用调用方提供非产品页面的测试代替旧 `--serve` 测试。**这是未完成、未验证的中间产物**：静态复核发现模型删除 `SERVE_OPTION_KEYS` 定义但脚本第 691 行仍引用它；新增 Node 夹具用同一进程 HTTP 服务配合同步 `spawnSync`，存在阻塞服务响应的风险；日志匹配要求仍未全部对齐。未执行修改后产品测试，不能称三项错误已修复；助手没有继续修改该产物或额外执行测试来替代模型交接。

源产物 20 文件哈希复核未变化，正式任务未改变，正式 Worker 日志为空。与 10 月 1 日同起点、同 12 HTTP、同模型实验相比，从零修改变成四次替换，但总 Token 532,706 → 621,348，增加 16.6％。这是两次实际样本差异，不能证明单一措施的因果收益或稳定效果。当前诊断有助于进入修改的迹象，尚未解决先通读、迟修改、未自测交接；不能宣称完成能力或成本优化成功，也不能仅凭上限内失败判定模型永远无法完成。

## 原始证据

隔离目录保存 `probe.py`、`baseline.json`、`run-baseline.json`、`run.log`、`result.json`、`call-count.json`、`sent-requests/001.json` 至 `012.json`，以及 `workspace/1/evidence/slice-repair-diagnostic-19.json`、`small-probe-checkpoint.json` 和 `traces/develop/6/`。仅临时留存，不复制完整上下文、思考或认证信息进 Git；临时目录可能失效。测试到调用上限停止，没有追加真实调用、扩大预算或代模型提交。
