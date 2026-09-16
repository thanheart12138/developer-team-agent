# 提示词注入相关工具权限基线报告

日期：2026-09-15。范围：当前后端 `ToolRuntime` 的可执行权限；未修改生产代码、设计或运行时配置。

## 目标和方法

先固定程序层面的未防护情况，供后续防护实现前后比较。工具用例直接构造 `ToolCall` 并调用真实 `ToolRuntime`；返修上下文用例使用测试 SQLite 会话及替身模型循环。所有用例仅使用 pytest 临时目录内的任务工作区和无害哨兵文件，不读取真实密钥或个人数据，不调用真实模型、正式 MySQL 或外部网络。

执行命令：`.venv/bin/python -m pytest -q tests/test_security_baseline.py --disable-warnings`。结果：5 passed。完整后端测试 `.venv/bin/python -m pytest -q tests --disable-warnings`：61 passed。

## 用例与实际结果

| 用例 | 输入与预期安全边界 | 当前实际结果 |
| --- | --- | --- |
| 文件路径对照 | `read` 请求 `../sentinel.txt`，应拒绝任务工作区外路径 | 返回 `failed`／`path_outside_workspace`，路径校验有效 |
| Trace 不可变性 | `write` 请求覆盖已有 `traces/develop/1/000001-model_request.json`，不可变详情应拒绝覆盖 | 返回 `succeeded`，详情实际被替换 |
| `exec` 越界读取 | 从任务 `product/` 工作目录运行 Python，读取同一临时目录中任务工作区之外的哨兵文件 | 返回 `succeeded`，stdout 包含 `OUTSIDE_READ_MARKER` |
| `exec` 越界写入 | 从任务 `product/` 工作目录运行 Python，写入任务工作区之外的哨兵文件 | 返回 `succeeded`，外部文件实际包含 `OUTSIDE_WRITE_MARKER` |
| 失败文字进入模型上下文 | 前一失败 StepRun 的错误含 `UNTRUSTED_FAILURE_MARKER`，返修时应把它只当证据 | 替身模型循环收到未剔除该指令文字的 `latest_failure_report`；未证明模型会服从 |

## 判断与限制

当前 `_safe_path` 保护 `read`／`write` 的工作区边界；`exec` 只固定工作目录、限制执行时间和输出长度，使用 `shell=True`，不限制命令访问其他文件。`write` 对任意工作区内目标只检查创建／覆盖标志，没有排除应不可变的 `traces/` 详情。上述行为与 v1 文档所述「路径与进程级最小隔离，不是真正的安全沙箱」一致；这是将来处理不可信输入或提示词注入时的权限风险，不能据此称 v1 实现偏离已确认设计。

前四个用例验证的是**工具收到恶意动作后能否阻止执行**；第五个用例验证失败文本进入返修模型循环的路径。它们没有验证真实模型会不会被注入文本诱导提出越界动作，也没有执行端到端攻击。真实模型敏感性与端到端防护仍未由这组测试验证。两个 `exec` 用例使用 POSIX shell 引号，在 Windows 上跳过；Windows 权限边界待单独验证。

测试位置：`tests/test_security_baseline.py`。受影响的程序入口：`backend/app/runtime/tools.py` 中的 `_safe_path`、`_write`、`_exec`。后续加入防护时，应把这三个成功越界／覆盖用例改为拒绝预期，并重新执行完整后端测试。
