# 同目标素材管理全流程：DeepSeek 与 Luna 对照

日期：2026-09-25。目的：从两个空的隔离任务工作区出发，比较产品阶段以外无人干预时，DeepSeek thinking 与 OpenRouter GPT-6 Luna medium 能否完成同一素材管理需求，以及各自的实际 Token 消耗。

## 测试设置

- 两组使用同一份 `docs/CONTENT_WORKBENCH_REQUIREMENTS_V1_AI_DRAFT.md` 和 `tests/content_workbench_baseline.py` 中相同的多模块、原生 JavaScript、localStorage 约束；激活的 8 组提示词版本及 SHA-256 相同。隔离 SQLite、工作区和 Trace 分别位于 `/private/tmp/content-workbench-comparison-deepseek-20260924` 与 `/private/tmp/content-workbench-comparison-luna-20260924`。正式 MySQL 任务与 Worker 路由未改变。
- 基准脚本增加仅供测试进程使用的 `--provider` 参数：DeepSeek 全阶段使用 `deepseek-flash`／thinking enabled；Luna 全阶段使用 `OpenRouterRuntime` 的 `openai/gpt-6-luna`／reasoning medium。Luna 经现有本机代理调用。两组实际模型 HTTP 上限各 300 次，单阶段逻辑调用上限各 100 次。HTTP 重试也计入整轮上限。
- 产品阶段允许按同一原始需求审阅并审批候选文档。DeepSeek v1 候选经核对后批准；Luna 在产品阶段提出界面细节问题，测试控制按已有相同默认回答后核对、批准 v1 候选。产品阶段之后未人工改需求、架构、设计、代码、验证脚本、任务状态或预算，也未续跑失败任务。两份产品候选不逐字相同，因此不是固定同一正式产品文档的严格 A/B。

## 结果

| 模型 | 最终状态 | 完成范围 | HTTP | 输入 Token | 输出 Token | 总 Token | Provider 费用 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| DeepSeek thinking | `failed / develop / slice_repair_validation_failed` | 产品、架构、Dev Design、5 张业务切片、全量 Node 与启动已通过；浏览器验证和自动返修未通过 | 85 | 11,113,862 | 703,903 | 11,817,765 | 响应无美元费用字段 |
| Luna medium | `failed / architecture_docs / scaffold_validation_failed` | 产品阶段通过；架构文档已生成，代码骨架校验失败，未进入 Dev Design 或开发 | 14 | 54,619 | 47,487 | 102,106 | OpenRouter 报告 0.030569825 美元 |

DeepSeek 的阶段用量：产品 4 次／25,992 Token，架构 5 次／114,309 Token，Dev Design 1 次／32,095 Token，开发及返修 75 次／11,645,369 Token。独立执行生成产品的 `node --test` 为 210 pass／0 fail／0 todo；这只能证明 Node 覆盖内的行为。任务曾启动本地 HTTP 服务，但没有到达 `waiting_acceptance`。

DeepSeek 首次 `verify_product` 失败是生成的 `verify_product.py` 只接受 `--base-url`，而正式流程按契约传入位置参数 URL。模型在自动返修中补上了位置参数支持；随后浏览器验证运行到删除素材的影响确认步骤，实际显示「选题三」「选题二」两个应受影响选题，脚本却将 `sorted(...)` 结果与固定顺序 `["选题二", "选题三"]` 比较，触发错误断言。`三` 的 Unicode 排序在 `二` 之前，故当前失败证据是验证脚本的排序断言错误，不能由此判定该处产品行为错误。返修继续失败，最终记录为 `slice_repair_validation_failed`。关键 Trace 为 `workspace/1/traces/develop/2/000498-tool_result.json`；不把独立诊断视作自动浏览器验收通过。

Luna 的架构骨架三次纠正均未让 `modules[].implementation_files`／`test_file` 与 `files` 键使用一致路径：有的声明省略了 `product/`，有的 `files` 键反而省略前缀。程序返回 `scaffold_module_file_invalid` 后只给出通用纠错提示，未点明路径集合必须完全一致。因此本轮真实失败是模型输出和系统反馈共同作用，不能单独推断 Luna 总体能力。无生成产品，也没有 Node 或浏览器验收。关键 Trace 为 `workspace/1/traces/architecture_docs/1/000048-model_request.json` 至 `000053-model_response.json`。

## 结论边界

两组均未在「产品阶段后无人干预」条件下完成最后软件；本轮不能比较成功交付的 Token 效率。Luna 消耗少，主要因为更早停止，不能解释为完成同一任务更省 Token。DeepSeek 的高消耗集中在开发和返修，且真实浏览器验收未完成。两个任务、不同模型、不同生成设计的单次结果不足以形成模型总体能力排序。完整响应 usage、阶段状态和 Trace 保存在各自隔离目录的 `summary.json`、`test.db` 与 `workspace/1/traces/`。
