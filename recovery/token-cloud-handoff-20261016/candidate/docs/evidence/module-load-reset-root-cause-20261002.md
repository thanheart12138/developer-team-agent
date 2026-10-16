# 2026-10-02：模块连接重置定位与启动修复候选

后续用户已确认实施，Worker 启动修复及当前服务定向复验通过；见 [修复验证记录](static-server-backlog-fix-validation-20261002.md) 。以下定位过程和候选阶段的原始状态保留。

## 结论与当前决定

用户「继续」对应上一轮验收失败后的原因定位。本轮证据指向当前 Python 静态服务的监听队列上限 5：浏览器并发建立模块连接时，实际内核队列达到 5，随后 TCP 建连报 `errno 54 / ERR_CONNECTION_RESET`。没有进入该模块的 HTTP 响应或 JavaScript 执行，失败连接直连本机，没有经过代理。

已用最小 TCP 实验验证队列满会产生相同错误，并用真实 ToolRuntime 启动具体修复候选：队列 128 时，观测到实际排队 6 个连接，八次限定首次加载全部通过。修复位置应为 Worker 的静态服务启动实现，不应让 DeepSeek 修改业务功能或给浏览器测试增加等待来绕过。

**开发助手建议、待用户确认实施**：仅修改 `backend/app/runtime/worker.py` 的 `handle_start` 启动命令，在启动标准库 `http.server` 前将服务监听队列设为 128。沿用 Python 静态服务、动态端口、原健康检查与浏览器验收契约。临时实验已验证候选命令；正式 Runtime 及当前隔离服务尚未修改，因此原总体验收未通过结论保持。

## 范围与证据目录

- 当前服务：PID 69130，地址 http://127.0.0.1:61626 。
- 当前产物：`/private/tmp/objective-review-continuation-20261002-L3L7mW/workspace/1/product`。
- 本轮原始证据：`/private/tmp/module-reset-diagnosis-20261002-qvyszlx4`；README.md 保存目录约定，诊断脚本与结果按实验名保存。
- 全程零模型 HTTP／零模型 Token；只检查模块加载与 TCP 链路，没有重跑 Node 或 42 条业务验收。

## 定位过程，含未能证明原因的对照

### １．当前服务限定首次加载再次失败

`startup-probe.py` 最多八次，遇到首次失败停止。前七次通过，第八次 `src/workbench/workbench.js` 加载失败，应用未初始化。CDP 与 Chrome NetLog 显示：

```text
PROXY_RESOLUTION_SERVICE_RESOLVED_PROXY_LIST: DIRECT
TCP_CONNECT_ATTEMPT: 127.0.0.1:61626
TCP_CONNECT_ATTEMPT end: os_error=54
TCP_CONNECT end: net_error=-101
```

模块尚未收到 HTTP 响应，因此不是该模块业务代码执行错误。当前监听进程仍存活；模块路径不同于上一轮验收失败的 app.orchestrator.js，说明不能只修那个文件。定位文件为 `startup-result.json`、`chrome-netlog-8.json`、`startup-failure-8.png`。

服务由实际 Worker 命令 `python -m http.server ... --bind 127.0.0.1` 启动；Python 3.12.13 的标准库服务继承监听队列 5。当前 `netstat -L` 实际显示 `0/0/5`。后台 stdout／stderr 为 DEVNULL，历史服务日志不能回溯；没有捏造服务端报错。

### ２．只改变队列的临时浏览器对照没有复现

`queue-comparison.py` 使用同端口、同产物、同 Python 标准库处理器，按 5／128／5／128 四个区段各执行六次首次加载，临时服务保存 stderr。队列 5 与 128 各 12 次均通过。该对照本身不能证明根因或修复效果；服务启动方式和日志输出也不同于当前实际 ToolRuntime，不能用它覆盖真实失败。

因此停止继续靠次数猜测，改为核对官方实现和实际服务的内核队列。全局 TCP 溢出计数未增长，也不作为队列满的直接证明。

### ３．实际失败时间与内核队列满对齐

使用已安装 macOS SDK 的 `proc_pidfdinfo / PROC_PIDFDSOCKETINFO`，只读当前服务 PID 69130、监听 FD 3 的 `soi_qlen / soi_incqlen / soi_qlimit`。采样最多二十秒，不调整系统设置或停止当前服务。`observed-startup-probe.py` 仍最多八次、失败即停止；再次前七次通过，第八次 app.orchestrator.js 建连失败。

关键时间：

| 事件 | 浏览器单调时间，秒 | 实际结果 |
|---|---|---|
| TCP 建连开始 | 762612.815 | 目标为 127.0.0.1:61626 |
| 服务监听队列采样 | 约 762612.816413 | qlen＝5、incqlen＝0、qlimit＝5 |
| TCP 建连返回 | 762612.816 | os_error＝54，随后 net_error＝-101 |

NetLog 时间精度为毫秒；macOS C CLOCK_MONOTONIC 与浏览器时钟存在固定偏移，采样后与 Python monotonic 核对并换算。上述时间不能当作微秒级先后关系或逐包内核调用追踪，但失败窗口的队列满已经实际观测，不再只是配置推测。原始记录为 `observed-queue.log`、`observed-chrome-netlog-8.json`、`observed-startup-result.json`、`diagnosis-summary.json`。

只读 sysctl 显示 `kern.ipc.soqlimitcompat=1`、`soqlencomp=0`、`somaxconn=128`。[Apple XNU socket 实现](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/uipc_socket2.c) 中，新连接受监听队列上限约束；开启兼容模式时以 qlimit 为上限。该源码用于核对机制，未把仓库 main 当作本机精确内核版本。

### ４．本机最小 TCP 实验独立验证拒绝机制

临时监听 socket 不执行 accept，让队列自然填满；每个队列最多建立七个连接，完成后关闭全部临时 socket：

| 队列上限 | 第１～５个连接 | 第６、７个连接 |
|---|---|---|
| 5 | 全部成功 | 均立即报 errno 54：Connection reset by peer |
| 128 | 全部成功 | 全部成功 |

该实验不涉及 HTML、JavaScript、代理或模型，证明本机队列满可直接产生当前浏览器记录的 TCP 错误。结果见 `kernel-capacity-result.json`。结合实际失败窗口 qlen＝qlimit 和候选服务排队 6 个仍成功，可定位这次复现的启动问题；不能据此追溯断言此前缺少网络证据的两次导航超时一定同因。

## 具体修复候选及验证

仍由 Python 标准库托管静态文件，在子进程启动前设置队列；以下仅为临时实验的实际候选命令，不是正式代码已实施：

```text
python -c "import runpy,socketserver,sys;socketserver.TCPServer.request_queue_size=128;sys.argv=['http.server','<port>','--bind','127.0.0.1'];runpy.run_module('http.server',run_name='__main__')"
```

端口来自当前受控整数，命令代码固定，没有用户内容插值。选择 128 对应本机 SOMAXCONN，不新增依赖或系统参数，不依赖某个生成产品的模块数量。[Python 官方 socketserver 说明](https://docs.python.org/3.12/library/socketserver.html#socketserver.TCPServer.request_queue_size) 允许服务覆盖监听队列大小，并解释队列满时后续连接会被拒绝。

`proposed-start-command.py` 使用当前真实 ToolRuntime、实际产品 cwd 和默认 DEVNULL 输出启动临时服务，仅检查默认工作台初始化和素材导航入口，未写业务数据：

- 内核实际 qlimit＝128，最高 qlen＝6，大于原队列上限。
- 八次首次加载 8／8 通过，无模块请求失败或页面异常。
- 临时服务和采样进程均已关闭，当前 61626 服务保持。
- 产品 20 文件哈希保持，未代模型修改产品。

首个候选验证探针在浏览器启动前因 netstat 未匹配到监听行而触发过严断言，清理后对空采样求 max 又报错；临时服务已关闭，保存 `proposed-start-command-attempt1.py` 与错误记录。修正为直接保留探针失败并读取 libproc 实际队列后，得到上述结果。未把首次探针失败算成产品失败或隐去。候选验证见 `proposed-start-command-result.json`、`proposed-queue.log` 与 `proposed-netlog-*.json`。

本轮合计 48 次限定首次加载观测：当前服务两组共 16 次，临时队列对照 24 次，候选命令 8 次。均有次数上限，目的为同一模块加载阻塞；不是模型测试或业务全套复跑。有限成功不证明任意并发下稳定，Windows 仍未验证。

## 隔离核对与下一步

最终只读 `audit.py / audit-summary.json / formal-after.json` 核对：产品 20 文件与原目标账本保持，E4-1 closed；隔离 Task 1 仍 `waiting_acceptance / verify_product / version 53 / PID 69130`。正式 24 任务／16,908 Trace 快照一致，pending 0、running 0，正式 Worker PID 2573 与日志 0 字节保持。本轮没有任何正式或隔离任务状态／PID 修改。

待确认实施范围：修改 Worker 一处静态服务启动命令，做队列容量与真实页面加载的定向验证；正式 Worker 空闲重启以加载实现，当前隔离服务同地址重启并同步真实 PID 元数据。保留所有原验收失败，不重跑产品定义、规划或模型开发；实施后再报告启动修复验证与软件验收结论，当前尚未放行。

临时诊断的日志、NetLog 与图片尚未永久归档，可能失效；本文件保留关键事实、无效对照、探针错误、候选命令及验证边界。
