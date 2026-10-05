# 验收返修机制验证，2026-10-04

## 范围与结果

用户「修复吧」授权修复返修目标跨阶段传递、完成项目的设计返修交接和大文件调查恢复。先更新 `docs/DEV_DESIGN.md`，再修改 `repair_objectives.py`、`slice_workflow.py`、`worker.py`，保留既有工作区改动。未直接修素材平台 favicon、修改正式数据库、重置失败或预算、修改密钥、提交或推送。

## 验证

- `.venv/bin/python -m pytest -q --disable-warnings`：授权本地环境中 316 项通过，26.77 秒。测试使用 `tests/conftest.py` 设置的独立内存 SQLite，无真实模型调用。
- 最终 `.venv/bin/python -m pytest tests/test_slice_workflow.py tests/test_worker_events.py -q --disable-warnings`：113 项通过，5.26 秒。
- 新回归确认旧卡全部通过仍不能完成当前设计返修，规划携带反馈／目标，生成事件绑定新卡且恢复不重复，卡通过后原目标仍开放。
- 新回归使用真实大文件触发字节截断，确认下一段从未读行继续，保留 partial 状态并完成分类。
- 原有独立目标审查与浏览器门禁回归保持，不以模型完成声明或执行卡通过核销缺陷。

首次相关回归发现把读取契约放入初始 `protocol_error` 改变既有错误纠正顺序，已拆为独立 `inspection_contract`。首次沙箱全套还因本地 HTTP 监听权限失败，在获准环境执行后通过。保留这些验证局限，不修改旧测试期望掩盖失败。

## 服务加载

只读确认正式库 24 个任务中无 pending／running、60 个事件中无 pending，历史 Run 计数总和 486 后，重启已核对身份的 API／Worker。新 PID 为 65632／65635，健康接口返回 `{"status":"ok"}`，两进程存活；重启前后数据库状态、schema、文件状态、产品哈希四项指纹全部不变。零新增模型 HTTP，没有续跑失败任务。原服务 PID 记录保留为历史，新记录位于 `workspace/experiments/formal-service-recovery-20261003-4caius6l/mechanism-reload-20261004.json`，新日志使用同目录的 `mechanism-reload-20261004-api.log` 和 `mechanism-reload-20261004-worker.log`。

## 未验证范围

真实 DeepSeek 修复尚未重跑。原任务累计 200 次 HTTP／16,875,823 Token、失败状态和 favicon 404 事实保持，本次新增真实模型 HTTP 为零。机制测试不能证明无人干预交付、降低 Token 或实际修好 favicon；下一次真实续测需要明确的新预算，不能沿用已耗尽预算。

分段调查仍受六轮、三个文件和单次字节上限限制，超长单行可能无法取得有效代码证据。采用事件绑定执行卡防止遗漏，不代表新卡一定足够，最终仍需真实产品验证和独立目标核销。
