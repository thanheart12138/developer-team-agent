# 原始目标保持：真实 DeepSeek 有界返修

## 范围与起点

用户确认最多 20 次真实调用，从旧内容工作台编辑缺陷断点隔离续测，不从头生成、不改变正式任务。本次保留旧产物与失败历史，复制到 `/private/tmp/repair-objectives-deepseek-20260930`；仅在隔离 SQLite 中创建新的开发执行记录，重置该实验返修轮次为 1，以新会话执行。复制来源为 `/private/tmp/content-workbench-optimized-deepseek-20260926` 的最终失败产物，不是旧从零任务的再次无人干预成功。

测试使用 DeepSeek thinking，实际 HTTP 请求上限与阶段逻辑调用上限均为 20，包含规划、开发、重试与审查。正式 Worker、数据库和旧产物均未改动。预览地址 `http://127.0.0.1:60843`，仅为本地实验服务，存活时间不保证。

## 步骤与结果

1．初始独立 Chrome 在新增素材后确认 `material_edit_entry_missing`。
2．按正式返修路径执行，规划器选择 `modify_code`；原始反馈进入 `repair-objectives.json`。旧分类的 `changes` 为空，因此账本保留原始用户反馈，不额外编造结构化期望。
3．模型修改素材和选题视图、相应测试及 `verify_product.py`，新增列表行内编辑。它没有完成交接，20 次调用后终止于 `failed / develop / model_call_limit_exceeded`。原始目标 E4-1 仍为 open，未进入独立目标审查，不能声称真实模型关闭门禁已通过。
4．独立 Node 首次用系统 Python，脚本检查因缺少 Playwright 失败；在项目既有 `.venv/bin` PATH 下复跑，102 项通过、0 失败。没有安装依赖或修改生成软件以适配环境。
5．旧独立编辑脚本首次在创建输入框等待可见性时超时，后续只读检查显示表单及输入可见，未证明是产品回归。再次执行可创建记录并进入编辑，但脚本仍向新增表单填值，得到 `material_edit_not_saved`。生成软件已经改为行内编辑，旧脚本选择器不匹配，不能据此断言编辑未实现。
6．仅在临时独立验收脚本中调整行内编辑选择器，增加页面初始化等待和优先级刷新断言，业务预期不变。最终真实 Chrome：素材笔记编辑保存、按新笔记检索、记录不重复、刷新保留；选题角度及高优先级编辑保存、记录不重复、刷新保留；页面异常 0。输出 `MATERIAL_AND_TOPIC_EDIT_ACCEPTANCE_PASSED`。没有改产品实现或追加模型调用。

## 调用与成本

| 项目 | 本次新增 |
| --- | ---: |
| 实际 HTTP 请求／有 usage 的响应 | 20／20 |
| 输入 Token | 3,401,601 |
| 输出 Token | 83,167 |
| 总 Token | 3,484,768 |
| 缓存命中／未命中输入 | 349,056／3,052,545 |

汇总只读取隔离库 Trace ID 大于 662 的新增响应，没有把复制的历史 usage 算入本次；Provider 未报告美元费用。测试基准原 `summary.json` 含历史 usage，不作为本次成本依据，以 `experiment-result.json` 为准。

## 已核对的阻塞与边界

- 第 2 次请求 context 的 `current_product_files` 约 261,545 字符，是 289,586 字符 context 的主要部分，原始目标约 836 字符。完整产品文件反复随请求发送，加上工具历史增长，造成高输入成本；不是目标账本本身占主要体积。后续请求同样很大，真实 Token 汇总确认本次输入占主要成本。
- 自测工具调用状态 succeeded 仅表示工具运行完成，其内部 Node `exit_code` 曾为 1，不能视为测试通过。最终 102 项通过来自独立复跑。
- 第 18 至 20 次请求期间有 8 个动作被 `repair_tool_loop_no_write` 拒绝，包含 `replace` 与自测。程序统计成功 `replace` 会重置计数，但门禁达到阈值时只豁免工具名 `write`，因此会拦截可以恢复写入进展的 `replace`。部分修改请求只是加注释，不能证明每个被拦截动作都必要；拦截确实发生，修正候选尚未实施，不能据此保证修正后模型会及时交接。
- 没有匹配的旧机制对照实验，不能把本次编辑实现成功完全归因于目标账本，也不能以新会话与 20 次上限证明稳定完成率。

## 结论与证据位置

原编辑缺陷的限定操作独立验证通过；自动交接、目标审查与最终完成未通过。未验证素材标题／来源链接等其他字段编辑、完整工作台全部需求、服务重启持久化和用户本人验收。不扩大调用预算或恢复失败任务。

原始证据在实验目录：`experiment-baseline.json`、`experiment-result.json`、`run.log`、`test.db`、`sent-requests/`、`workspace/1/traces/`、`initial-edit-check.txt`、`final-edit-check.txt`、`final-edit-recheck.txt`、`final-node-venv-check.txt`、`independent-inline-edit.py` 与 `independent-inline-edit.txt`。临时文件不保证长期保留，不复制完整模型输入到 Git。
