# GPT-6 Luna high 定向返修实验

日期：2026-09-24。用户授权在上轮失败的隔离生成产品上做一次定向返修，检验更换执行模型能否修复当前明确的测试失败。本实验不修改正式 Model Runtime、模型路由或原 Task 状态。

## 输入与执行范围

- 工作区：`/private/tmp/content-workbench-repeat-read-20260924/workspace/1/product`。上轮真实 DeepSeek 在 `topics-core` 留下 Node 23 项中 22 通过、1 失败，失败断言为 `getTopicMaterials` 在素材删除后应返回空列表。
- 协作模型调用指定 `gpt-6-luna`、`reasoning_effort=high`，只允许修复隔离产物并运行测试。该协作环境没有向代理或项目 Trace 暴露独立的实际 Provider／模型响应记录，因此模型身份只有调用配置记录，不能用本项目的 Provider Trace 再次核验；没有本次调用的 Token 或 API 费用数据。
- 本次是针对已知缺陷的独立代码返修，不是让项目现有 Worker 自动从失败 Step 恢复，也没有重跑产品生成全流程。

## 修改与验证

- 仅 `product/js/topics.test.js` 相对 DeepSeek 失败检查点发生变化。测试辅助函数原先直接访问 `globalThis.localStorage`；但 Node 环境中 `storage.js` 使用内存回退，原辅助函数实际上未删除素材。返修将辅助函数改为通过已有 `getCollection`、`setCollection` 更新 `cms.materials`，保留原断言。
- 返修后独立复跑 `node --test js/storage.test.js js/materials.test.js js/topics.test.js`：23 通过、0 失败、0 TODO。独立复跑 `node --test js/*.test.js`：49 项，其中 23 通过、0 失败、26 TODO。相关错误得到修复，但其余切片仍未实现，完整产品任务尚未完成。
- 相对失败检查点的文件 SHA-256 清单，只有 `product/js/topics.test.js` 变化；正式项目源码、设计、模型配置及运行服务未改变。

## 结论边界

指定 Luna high 的定向代理在已有失败证据和明确文件范围下完成了这一处返修，实际 Node 回归通过。这证明该缺陷可由更换执行模型并缩小任务范围解决；不能证明 Luna high 接入当前自动流程后能自主完成全部切片，也不能量化相对 DeepSeek 的成功率或 Token 收益。26 项 TODO、启动及浏览器验收仍未验证。
