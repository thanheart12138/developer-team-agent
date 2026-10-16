# 当前启动与交付入口

核对日期：2026-10-10。从项目根目录执行命令，按用途选择入口，不运行实验run.py来打开网站。

## 入口

| 用途 | 入口 | 依赖 |
|---|---|---|
| 系统任务界面 | http://127.0.0.1:5173/ | 本地React前端与API |
| API健康检查 | http://127.0.0.1:8001/health | FastAPI，正式数据库已有配置 |
| 固定面试演示 | http://127.0.0.1:51881/ | 已冻结素材平台与可信静态服务，不调用模型 |
| 最新范围搜索返修结果 | http://127.0.0.1:53155/ | 本轮冻结快照服务；重启后地址可能失效 |

以上四项本次GET200。正式API61615／Worker61616的命令与工作目录核对匹配，正式队列空闲；不依赖PID作为未来启动条件。8000由其他项目使用，不占用或终止它。详细状态和历史结果见ROADMAP。

## 优先启动固定演示

前置：项目已有Python依赖与原实验目录。无需模型密钥、MySQL或Docker来浏览固定快照；验证生成代码仍走Docker。先只读核对原预算／提交，不恢复任务：

```bash
PYTHONPATH=. .venv/bin/python workspace/experiments/material-cross-module-repair-20261009/demo.py check
```

本次成功：awaiting_acceptance，13／30HTTP，sqlite_read_only=true，task_resumed=false，model_http_calls=0，提交匹配当前文件。

51881无服务时再运行：

```bash
PYTHONPATH=. .venv/bin/python workspace/experiments/material-cross-module-repair-20261009/demo.py serve --port 51881
```

终端保持打开，结束本次前台服务用Ctrl+C。端口已占用先核对服务，不重复启动或终止不明进程；缺原实验文件就停止，不能建空数据库冒充恢复。固定演示是历史双缺陷案例，最新53155是另一轮单缺陷，不能混成一次运行。

## 正式系统运行

已有服务可用时直接访问，无需重启。手工启动要求Python3.12、前端现有Node依赖、已有MySQL dev_team_simulator数据库，以及通过受控环境提供的SIMULATOR_DATABASE_URL和workspace位置；不要把密码写入命令日志或提交。普通应用启动不是允许创建schema／迁移的授权。

确认任务空闲、数据库连接配置正确、没有第二个Worker且端口空闲后，在各自终端运行：

```bash
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

```bash
.venv/bin/python -m backend.app.runtime.worker
```

前端在frontend目录运行：

```bash
VITE_BACKEND_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5173
```

这些是启动命令，不是本次执行记录；本次沿用已运行实例，未启动新Worker、提交事件或调用模型。Worker会处理正式待执行任务，队列不空闲时不能把启动当无副作用操作。停止自己启动的前台进程用Ctrl+C；正式进程重启先检查任务及身份，遵守AGENTS约束。

## 数据与能力

正式任务在workspace/<task_id>/，独立实验在workspace/experiments/，本机备份在workspace/experiments/artifact-backup-20261010/。workspace被Git忽略，源码推送不包含这些产物。用户决定保留一份本机备份，没有异地副本。

当前新返修：连续主会话调查修改、主动自测、显式版本提交、固定全量测试／启动／实际浏览器、用户验收。执行生成Python／Node需要有效Docker sandbox profile；模型测试必须单独确认范围与HTTP上限。最新单例343,838Token，成本仍高，不保证任意软件任务。旧尝试保留原审查契约，两份更早未知提示词绑定不支持恢复；不要运行旧脚本尝试绕过。

本轮已委托技术验收，系统仍待用户批准事件，目标台账未自动关闭。面试操作和对应历史证据见 [DEMO_GUIDE](DEMO_GUIDE.md) ，最新真实记录见 [范围搜索返修](evidence/material-task-detail-scoped-search-deepseek-real-20261010.md) 。

## 提示词管理与只读成本分析

页面入口：`http://127.0.0.1:5173/?view=prompts`。可创建候选、维护案例、离线评测和查看真实历史结果；候选不自动激活。当前真实报告`ab8e7aa98f2c4e3da8ffb2f6c604311b`有未执行／局部观察重要案例，禁止激活。管理页没有付费批次启动按钮；真实调用使用批准的持久隔离运行器，不把离线导入标为真实。

```bash
.venv/bin/python -m backend.app.runtime.prompt_registry
.venv/bin/python -m backend.app.runtime.execution_cost --task-root workspace/experiments/prompt-real-baseline-20261010/normal
```

以上均已实际执行，零模型请求。提示词评测CLI需提供案例、捕获响应和可选人工判断；检查器示例只验证机制。不要重新运行已结束实验的run.py或probes.py；已有数据库拒绝重新初始化，重跑需要新的范围及预算授权。证据见 [真实基线与平台](evidence/prompt-platform-real-baseline-20261010.md) 。

### 固定输入的真实评测入口

CLI可准备一个登记案例的单次输出／首批行为评测，prepare不发送请求、不批准外发。实际执行过：

```bash
.venv/bin/python -m backend.app.runtime.prompt_real_evaluation prepare --name repair-executor --version v5 --case business-change --http-cap 1
```

准备结果在workspace/prompt-evaluations/real-runs/<ID>/，README约定各文件用途。管理员核对input.json并获得明确用户授权后，才写匹配输入身份、目的地、provider、预算与授权来源的approval.json；页面不能创建或扩展该授权。页面展示固定案例并提供执行按钮，无批准时后端拒绝；已有结果再次点击只打开原结果。中断库或账本不重置，需要单独恢复核查。本入口不执行工具、不证明完整软件修复；完整任务仍用已有Worker／Docker。当前待审批ID没有调用额度批准，不复用上一轮剩余额度。

## 离线评测的版本与输入身份

`backend.app.runtime.prompt_evaluation` 的 `--prompt` 与 `--version` 必须一起提供；绑定时核对真实模板渲染及消费角色组件。不指定时 `template_binding` 为 null，不能据此宣称某版本已验证。报告含实际输入文件的 SHA-256、逐例依据与禁止行为；缺响应返回未执行并退出码１。命令不发送模型请求、不执行工具、不创建正式评测报告。

```sh
.venv/bin/python -m backend.app.runtime.prompt_evaluation --cases prompts/cases/design-author.json --observations workspace/experiments/prompt-platform-20261010/empty-observations.json --prompt design-author --version v1
```

以上空观察文件用于复现未执行与版本身份；需要评测响应时另准备按当前案例ID对应的观察文件。实际缺响应验证报告见 `workspace/experiments/prompt-platform-20261010/bound-cli-report.json`。
