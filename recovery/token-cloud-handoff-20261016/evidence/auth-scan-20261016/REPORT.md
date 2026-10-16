# 合成认证扫描接线专项（2026-10-16 UTC）

范围仅 mainline-low-candidate 的 controlled_transport.py、token_offline_runner.py、test_controlled_transport.py。旧报告与原实验不改。

旧缺陷：受控请求头与Chat SSE使用调用侧合成认证值，Responses保全仍固定离线runner模块的FIXTURE_SECRET。替换调用侧合成认证值时，Responses正文及原始JSON额外字段中的认证回显未被阻断。

实现：_responses增加必填scan_secret关键字参数；离线fixture明确传自己的FIXTURE_SECRET，受控调用让请求头、SSE及Responses保全共用同一局部auth_secret。没有真实凭据读取、live入口、额外依赖或框架。

先加入14例反例／正例，在修改生产源码前运行：6 failed、8 passed、24 deselected，见before.log。失败均为Responses的明文、URL编码、base64编码回显，分别覆盖正文和原实体额外字段。

修改后只运行tests/test_controlled_transport.py与tests/test_token_offline_runner.py：46 passed，86条SQLAlchemy既有弃用警告，见after.log。含原有disabled/live拒绝、非法合同、未知阻断及取消pending保留用例。未运行全套。

所有运行使用现有.venv、env -i清空环境、test-guard禁止真实socket/DNS及容器子进程。测试只用内存SQLite和临时合成预算、HTTPX MockTransport。新增真实模型HTTP为0，未访问用户Codex、未修改真实账本、未执行产品任务。首次版本检查命令使用错误相对解释器路径而未运行；之后使用正确既有解释器执行上述测试。

复核命令（在mainline-low-candidate目录）：
env -i PATH=/usr/bin:/bin HOME=/tmp PYTHONPATH=/workspace/scratch/fde72c226373/token-recovery-20261015/test-guard:. ../.venv/bin/python -m pytest -q tests/test_controlled_transport.py tests/test_token_offline_runner.py

默认disabled、live硬拒绝、精确MockTransport限制、offline_only合同未改。此回执仅证明离线机制专项，真实接入、真实任务质量及完整同质量≤100万目标仍未验证。

本次只生成独立auth-scan.patch及manifest，不更新历史组合补丁和旧交付包。差异必须叠加到当前恢复候选，而非原Git基线。
