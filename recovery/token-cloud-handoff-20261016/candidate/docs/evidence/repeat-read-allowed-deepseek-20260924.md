# 放开重复读取的真实 DeepSeek 实验

日期：2026-09-24。目的：检验允许同一开发循环重复读取同版本文件后，真实模型能否继续完成素材管理任务。

## 范围与方法

- 在 `/private/tmp/content-workbench-repeat-read-20260924` 的独立 SQLite／工作区，从上轮保存的架构骨架阶段产物重建首片 `materials-core` 开发前状态。该起点不是全新任务从产品阶段开始；测试控制构造恢复状态。
- 仅在本次测试进程中令 `worker.duplicate_read_error` 返回 `None`，其余正式代码、提示词和无进展停止机制保持原样。实际调用 DeepSeek，整轮 HTTP 上限 100、单 Step 上限 100；没有修改正式 Worker 或原任务。
- 输入和产物保存在上述工作区；调用摘要为 `summary.json`，工具轨迹为 `workspace/1/traces/develop/1/`，动作及文件版本为 `workspace/1/evidence/develop-1-checkpoint.json`，切片结果为 `workspace/1/evidence/slice-progress.json`。

## 结果

- `materials-core` 写入实现及真实断言后，Node `11 pass / 0 fail / 0 todo`，切片通过。该片有 4 次同路径、同 SHA-256 的成功重复读取。
- `topics-core` 写入 `topics.js` 与 `topics.test.js` 后，Node `22 pass / 1 fail / 0 todo`。失败项为「getTopicMaterials 解析已删除素材时自动消失」，实际长度 1，期望 0。测试辅助函数只直接操作 `globalThis.localStorage`，而本次 Node 环境没有可用 `localStorage`，`storage.js` 使用内存回退；因此辅助函数没有删除内存集合中的素材。这是本次失败断言的直接原因，未修复生成代码。
- 失败后模型对未变化的 `product/js/topics.test.js` 连续成功读取 7 次，没有再次写入或重新运行测试，最终触发 `unit_development_no_progress`。两片合计 20 次成功读取，其中 11 次为同路径、同 SHA-256 重读；本次没有 `duplicate_read` 拦截。
- 总计 19 次 DeepSeek HTTP，输入 288,602 Token、输出 10,504 Token、合计 299,106 Token。最终 Task 为 `failed / develop`；没有完成其余切片、全量测试、启动、浏览器验证或用户验收。

## 判断边界

允许重复读取没有让本样本完成任务；在第二片的一项测试失败后，模型回到重复读取而未修复。首片成功说明允许重读不必然立即停滞，不能据单次样本证明重读拦截是先前四片通过的唯一原因。先前带拦截的续测使用不同恢复状态与模型轨迹，Token 数和通过片数不构成严格 A／B 成本或因果比较。本实验只改变测试进程，正式重复读取规则仍有效。
