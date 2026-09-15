# v2 Trace 与实时可视化验证

## 验证范围

- Trace 顺序、不可覆盖、敏感键脱敏和任务工作区持久化。
- Trace 增量索引与单条详情 API。
- 七阶段时间线、动作流、原始详情、历史查看和刷新恢复。
- 既有后端机制回归与前端生产构建。

## 自动化验证

```text
.venv/bin/python -m pytest -q
28 passed

cd frontend && npm run build
vite build succeeded
```

新增测试覆盖：任务内递增序号、详情文件不可覆盖、嵌套敏感键脱敏、增量游标不返回旧记录、列表不携带大文本、详情按需读取和详情文件缺失错误。

## 真实浏览器验证

使用临时 SQLite 数据库启动 FastAPI `127.0.0.1:8766`，启动 Vite `127.0.0.1:5174`，通过真实浏览器执行：

1. 创建本地测试任务，页面立即显示七阶段时间线和 `创建任务` Trace。
2. 向同一任务追加 `model_request`，1.5 秒轮询后页面自动显示新动作及完整详情。
3. 选择旧动作后出现“回到当前进度”，旧详情可正常读取。
4. 使用 `?task=1` 刷新页面，任务、消息和两条 Trace 均恢复且不重复。
5. 在干净浏览器页检查控制台，错误和警告均为 0。

首次刷新验证暴露两个问题：任务 ID 只存在 React 内存中导致刷新回到创建页；React StrictMode 使首次并发轮询重复追加。已分别通过任务 URL 和按 `id`／`sequence` 合并去重修复并重新验证。

## 未验证

- Windows 正式环境及用户本人操作未验证。

## 正式 MySQL 与真实模型验证

启动现有 `id-photo-mysql` 容器后，在 `dev_team_simulator` 新增 `trace_records`，未操作 `id_photo` 数据库。结构核对结果：15 个字段、任务内序号唯一约束、`task_id`／`step_run_id` 索引和两个外键均符合设计。事务探针成功插入一条记录，回滚后探针记录为 0。

正式连接首次失败，直接证据为 PyMySQL 连接 MySQL 8 `caching_sha2_password` 时缺少 `cryptography`。补充固定版本 `cryptography==46.0.3` 后，FastAPI 使用正式 MySQL 正常启动。

真实 DeepSeek 任务 20 使用明确的本地按钮计算器需求完成：

```text
product_docs → architecture_docs → dev_design → develop
→ test 失败 → develop 自动返修 → test 通过
→ start_product → verify_product → waiting_acceptance
```

- 生成软件返修后 Node 测试 39／39 通过。
- 真实 Playwright 验证通过，无 `[SKIP]`。
- MySQL Trace：102 条，序号 1—102，去重数量 102。
- 工作区详情：102 个 JSON，总计 1,155,391 字节。
- 所有详情路径均位于 `traces/`。
- 递归检查已知敏感键，未发现未脱敏值。
- 真实页面正确展示七阶段、失败、返修、最终成功和等待人工验收；历史阶段可查看并能回到当前进度，浏览器控制台错误和警告为 0。
- 最终复核发现不可变请求记录在完成后仍显示“执行中”；前端改为只有全局最新动作保留“执行中”，较早的 `running` 事件派生显示“已发起”，不修改原始 Trace。重新构建并用真实任务验证通过。

任务 20 当前保持 `waiting_acceptance`，未代替用户提交最终验收。
