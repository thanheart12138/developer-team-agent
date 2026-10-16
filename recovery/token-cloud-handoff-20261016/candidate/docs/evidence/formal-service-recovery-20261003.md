# 2026-10-03 正式服务恢复与持久数据核对

## 结论与授权范围

主人，原正式 MySQL 和项目工作区数据仍在，API、前端与空闲单 Worker 已恢复并验证。本轮仅恢复运行环境，零新模型 HTTP／Token，不重建旧隔离素材平台、不创建任务、不提交验收事件，不修改 `.env`、schema 或任务状态。

用户「OK，你搞吧」批准先只读核对正式任务／调用计数／工作区，再恢复服务；新的真实 DeepSeek 返修输入、范围和预算没有获得本轮授权。先前六次续测预算不重置，缺失的最终响应／用量仍记未确认。

## 环境与入口

| 服务 | 本轮实际状态 |
|---|---|
| MySQL | 原 `id-photo-mysql` 已运行、健康；原 `deploy_mysql_data` 数据卷与 `dev_team_simulator` 可读，本轮未执行容器启动或重建 |
| API | [http://127.0.0.1:8001/health](http://127.0.0.1:8001/health) ，PID 8185 |
| 前端 | [http://127.0.0.1:5173](http://127.0.0.1:5173) ，npm 父进程 8201，监听 Node 8222 |
| Worker | 单进程 8243，启动前没有可运行任务／pending Event，恢复期间保持空闲 |

8000 已由其他项目 `id-photo-algorithm` 占用，保留该服务。前端使用已有 `VITE_BACKEND_URL` 进程环境覆盖代理目标；数据库认证仅在控制脚本内存与 API／Worker 环境中继承原容器，不进入文件、命令参数或日志，前端不继承该数据库认证。API 与 Worker 工作目录为当前项目，前端工作目录为 `frontend/`。

## 数据与文件核对

在单次只读一致性事务中读取五张已有表的计数、任务状态／版本／路径、204 个 Run 的原计数、Event 状态和 Trace 索引，记录 schema 指纹；服务恢复及浏览器读取结束后重复核对。

| 核对项 | 结果 |
|---|---|
| 表计数 | tasks 24、step_runs 204、events 60、messages 642、trace_records 16,908，与前轮永久摘要一致 |
| Task 状态 | succeeded 1、waiting_user 10、failed 9、waiting_acceptance 4；pending／running 均 0 |
| Event 状态 | consumed 60、pending 0 |
| Run 逻辑计数 | 总和 486，全部 Run 的计数前后保持；该数字不是 HTTP 次数或 Token |
| 工作区 | 24 个正式工作区和产品目录存在，共 60 个产品文件逐文件 SHA-256 前后保持 |
| Trace 详情 | 按各 Task 根目录解析后，16,908 个详情路径全部存在；代表性详情经 API 读取并解析，不称全部内容已逐一审计 |
| 检查点 | 95 个存在、109 个缺失；缺失数量与 ROADMAP 的 2026-09-24 原迁移记录一致，旧逐文件清单缺失，不能逐项证明历史保持 |
| 前后指纹 | 已核对数据库字段、schema、文件存在状态、产品哈希四项全部相同 |

正式 Task 23 当前 failed／develop／version 97，Task 24 waiting_acceptance／verify_product／78，Task 25 waiting_acceptance／verify_product／37，Task 26 failed／develop／23。修正 ROADMAP 仍把 Task 23 描述为等待产品审批的过时进度，未改数据库。

## 服务验证与保留的验证错误

最终九条只读检查通过：健康接口 200；四个已有 Task 的 API 与前端代理响应完全一致；非法 Task 返回 404 后正常 Task 仍返回 200；已有 Trace 详情 200；真实 Chrome 首页加载；真实 Chrome 查看 Task 23 状态及点击 Trace 加载详情。最后一条同时精确核对旧失败原因，没有新增页面异常、API 错误、请求失败或写请求。已检查截图，五项进程／监听／工作目录／Docker 读取命令均返回零。

交付前再次只读核对三个服务存活、健康接口 200 和四项正式指纹保持。两个控制脚本语法、机器可读 JSON、105 个本地文档链接、实验目录 Git 忽略及 `git diff --check` 均通过；差异统计包含此前未提交改动，不全部归因本轮。

首次文件核对将 `traces/...` 相对路径按项目根目录解析，错误记录为越界；对照 API 的 `task.workspace_path / detail_path` 协议修正控制脚本，保留首份错误快照，新核对全部存在，原数据库字段指纹相同。首次浏览器脚本要求 `.error` 为零，错误地否定失败任务应显示的旧失败原因；修正为与原 API `failure_reason` 精确一致，保留失败记录后复验通过。均未修改应用实现来迎合验证。

## 证据位置与限制

脱敏摘要见 [机器可读结果](formal-service-recovery-20261003.json) 。完整本轮控制脚本、前后状态快照、路径核对、原 Run 计数、进程证据、日志和截图留在项目忽略目录：

`workspace/experiments/formal-service-recovery-20261003-4caius6l/`

其中 `formal-before.json` 保留首份路径分类错误，正式比较使用 `formal-before-checked.json` 与 `formal-after.json`；`verification-first-failure.json` 保留首个界面预期误判，`service-verification.json` 是最终结果，`frontend-task23.png` 是实际截图。`call-count.json` 的零是本次无模型操作的初始计数，不代表旧实验成本清零。该目录不含新 SQLite。

正式 MySQL 的持久恢复不等于旧 `/private/tmp` 素材平台或断点恢复。本轮没有启动生成软件、验证模型新返修、证明旧目标闭合／finish、实际机器重启留存或 Windows 运行。旧生成软件地址／PID 是历史数据库字段，未在本轮更新或保证可访问。服务恢复已验证，用户最终验收未执行；旧续测最终成本仍未确认。
