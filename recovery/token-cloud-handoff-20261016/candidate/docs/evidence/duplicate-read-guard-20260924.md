# 开发重复读取拦截验证

日期：2026-09-24。目标：完成任务优先，允许读取不同文件和新行范围，阻止同一开发循环中同版本、同范围且内容已在当前上下文的重复读取。

## 实现与机制验证

- 当前有效规则先写入 `docs/DEV_DESIGN.md`。`worker.model_tool_loop` 在执行 `read` 前核对同一 history 中成功读取的规范路径、返回范围和 SHA-256；当当前文件内容仍在 `current_product_files` 中时，对重复读取返回短错误和上下文位置，并保存 `duplicate_read` tool_guard Trace。文件变化、新行范围或当前上下文没有内容时允许读取。无新增依赖、数据库字段、工具权限或调用预算。
- 定向测试覆盖不同 description／路径写法、已读子范围、未读新范围、文件变化和上下文缺失；真实工具循环测试核对第二次读取被阻止且下一次模型请求收到反馈。完整后端回归 `208 passed`，`git diff --check` 通过。

## 真实 DeepSeek 验证

1. 从空 SQLite／工作区新建素材管理任务，使用 `/private/tmp/content-workbench-readguard-20260924`，全阶段 DeepSeek、单 Step 100／整轮 300 次上限。产品候选由测试控制核对并批准。任务在 `architecture_docs` 因 `scaffold_validation_failed` 终止：五次骨架候选中先有模块 ID 错误，两次 JSON 在 8192 输出上限处截断，最后缺必需入口文件。实际 13 HTTP、133,875 Token。未进入开发，因此该任务不能验证读取拦截或完整交付。
2. 为直接验证原失败点，保留上轮失败样本，在 `/private/tmp/content-workbench-current-network-20260924` 使用测试脚本的 `--resume-internal --reset-current-slice-attempt` 从首片重新开发；不修改生成代码或正式数据库。该恢复控制使本轮不是从零自主交付证据。首片 `materials-core`、`topics-core`、`tasks-core`、`dashboard-summary` 依次通过真实 Node 自测与程序复验；重复读取工具拦截实际记录 8 次 `duplicate_read`。随后 Planner 连续三次无法让下一张 UI 切片的 `required_interfaces` 与逐条验收映射一致，最终 `failed / develop / slice_plan_validation_failed`。
3. 恢复样本累计 59 次 HTTP、983,888 Token；其中恢复前为 25 次／227,209 Token，本次新增 34 次／756,679 Token。当前生成产品独立执行全部 Node 测试为 `54 pass / 0 fail / 6 todo`，六项 UI 测试尚未实现；未进入 HTTP 启动、浏览器验证或人工验收。两次运行的阶段和初始状态不同，不能用 Token 总量断言成本改善。

## 当前判断与边界

- 机制测试和恢复样本证明：重复读取已被程序阻止，原首片 todo 停滞在恢复样本中已越过。不能证明拦截是四片通过的唯一原因，也不能证明全新任务稳定完成。
- 新任务的骨架生成失败与恢复样本的 UI 切片规划失败是独立阻塞。前者包含输出截断与结构校验失败，后者三份候选在接口映射的缺项／多项之间变化；本轮未修改 Scaffolder 或 Planner，也未人工修正候选以推进任务。
- 正式 API／Worker 进程仍在运行。无法用当前进程的默认数据库凭据查询正式库中的活动任务，故未重启服务，以免中断未知任务；隔离测试进程已经加载本次代码。
