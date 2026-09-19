# 模块／功能设计与逐单元测试闭环验证

日期：2026-09-17。实现已接入，机制验证通过，完整真实自主设计／交付及用户验收未通过验证。

## 实现与边界

架构正式化后输出版本化 development-plan.json，校验模块／功能归属、唯一文件所有权、依赖无环、完整产品入口和非空 Node 测试清单。无效计划把具体错误反馈模型，最多三次纠正，程序不补造设计。测试方法不是新增公共接口的依据，测试与文档归属对应功能。

Dev Design 阶段先独立评审共享契约，再按依赖生成独立单元设计。单元获得共享契约、当前验收、直接依赖的正式设计与接口；旧版本修订附相应旧设计。根级 dev-design.md 只保存路径／哈希索引。评审 ready 才正式化，revise 有界修订，clarify 等待决定。用户回答恢复当前 Run 的预算；已确认设计缺陷开启新版本，不按文件已存在直接复用。

Develop 按依赖串行开发，每个单元只写自己声明的文件，依赖只读；程序生成命令执行当前与已完成单元测试，失败反馈真实输出、验收依据及代码版本，最多两次修复。当前单元和直接依赖实现每次调用刷新为最新快照，近期完整工具文本重复部分去除；其余依赖按需受限读取，不主动加载全部产品或所有设计。完整 Trace／检查点保留，progress 按设计与文件哈希恢复。设计缺口返回 dev_design，保存新设计版本后才再开发。

全部单元通过后仍执行原全量 test、HTTP 启动、真实浏览器 verify 与人工验收。保留旧单份设计和明确跳过设计的任务入口，不转换或自动续跑历史任务。未改数据库 schema、Provider 路由、100 次 Step 逻辑预算、数据存储或产品依赖限制；仅取消强制单模块。

## 机制验证

`.venv/bin/python -m pytest -q`：137 项通过，其中新增逐单元用例 22 项。日志：`/private/tmp/unit-workflow-regression.log`。新增单元测试使用 Fake 模型，但执行真实 write 和 Node：加法先出现 2+3≠5 的故障，真实测试失败后反馈并修为求和，通过后才开发平方，再完成装配。验证三次失败终止、文件外部变化后旧成功失效、非空／非 skip 计数、范围内快照刷新、依赖写入拒绝、设计问答恢复、设计缺陷新版本、无效计划的有界反馈。Fake 不代表真实自主能力。

相关后端与手动脚本 py_compile、git diff --check 通过。既有 datetime 弃用警告未改。

## 追加测试授权

用户随后授权累计实际 HTTP 上限提高到 300 次，已有 30 次计入。保留旧报告与 Trace，从隔离开发探针原检查点恢复，仅恢复因测试预算耗尽的隔离 Task／StepRun；不修改正式业务库或生成代码。正式 Step 默认逻辑预算仍为 100 次。后续结果另行记录。

## 真实 DeepSeek：共用三十次预算

入口：`tests/unit_workflow_deepseek_validation.py`。各进程沿用 prior_calls，总共最多 30 次实际 HTTP，传输重试同样计入。本次 30 次均有完整 usage：输入 121,765、输出 36,439、总量 158,204 Token。合计见 `/private/tmp/unit-workflow-validation-usage.json`。无严格对照，不宣称成本下降。

### 原规划测试：5 次

目录：`/private/tmp/unit-workflow-deepseek-20260917`；日志：`/private/tmp/unit-workflow-deepseek.log`。

从明确的合成 math／ui 需求开始，正式需求作为测试输入，架构由 DeepSeek 生成。首轮把文档单独拆成没有测试的单元，并包含不符合规则的 Node 测试路径，程序在架构完成前拒绝计划。原失败证据与状态保留。

据此完善最小单元规划提示与有界校验反馈，未弱化非空测试和文件规则。

### 修正后的设计测试：再用 15 次，累计 20 次

目录：`/private/tmp/unit-workflow-deepseek-corrected-20260917`；日志：`/private/tmp/unit-workflow-deepseek-corrected.log`。

架构产生有依赖顺序的六个功能单元，共享契约和加法 Dev Design 经独立评审正式化。平方设计在静态 ESM 导入、零依赖和“受控替换 add 来证明调用”之间形成测试方案冲突；独立 Reviewer 两次 revise 后要求澄清，任务停在 waiting_user／dev_design，没有绕过评审，也未进入完整开发。

模型在计划中把特定测试技术固化成验收要求，暴露不必要的设计约束。随后补充计划提示：验收只描述已确认行为、具体测试方法留给单元设计；补充直接依赖真实设计上下文和旧设计修订依据。最后这些补充通过机制回归，未在真实架构设计流程中完整复跑，不能据旧运行声称它们已解决问题。

### 固定设计的真实开发探针：剩余 10 次，累计 30 次

目录：`/private/tmp/unit-workflow-development-probe-20260917`；日志：`/private/tmp/unit-workflow-development-probe.log`。启动参数 `20 --develop-probe`。

使用明确标注的固定合成共享契约与三个单元（加法、调用加法后平方、界面），只验证开发与程序测试机制。它不是模型生成的完整架构／设计证据。

真实 DeepSeek 写入加法实现和测试，程序 Node 10 项通过后才推进平方。平方完成后程序执行两个功能的回归，Node 20 项通过。结果与版本保存在 `workspace/1/evidence/development-progress.json`、`evidence/units/`、Trace 和工具摘要。没有回到此前同七文件反复读取的轨迹，但该短样本不能证明消除了所有空转。

界面代码与 HTML 已生成，但 UI 测试、verify_product.py、implementation.md 尚未齐备，30 次 HTTP 预算耗尽，模型调用包装为 `model_transport_failed:RuntimeError`；实际原因是手动测试硬预算。保留失败状态，不增加预算或修改生成代码继续冒充成功。完整 Worker test／start／verify 和交付未完成。

## 真实浏览器独立操作

对上述部分生成产物单独启动临时 HTTP，并实际使用 Chromium 输入和点击。检查 2+3 的求和／平方、负数、空白／非数字／小数／越界错误提示及各次错误后恢复、边界结果，共 14 项通过，页面错误 0。没有调用产品内部业务 API，也未修改生成代码。临时服务已停止。

首次独立检查额外要求错误文案必须在 #result，而合成需求仅要求可见提示，造成 4 项假失败；保留 `independent-browser-initial.json`，按原需求核对可见提示与恢复后，结果为 `independent-browser.json`，截图 `independent-browser.png`。这项浏览器操作不能替代缺失的 UI 单元测试与整体流程。

## 正式服务

最终回归后确认正式运行任务 0、pending Event 0，重启单 Worker，最终 PID 88183 存活；Task25 保持 waiting_acceptance、Task26 保持 failed。未自动续跑任务或改业务状态。最终加载日志：`/private/tmp/unit-workflow-worker-restart-final.log`，前次加载日志单独保留。API 与前端未改，无需重启。

## 已知限制

未完成全自动架构／全部单元设计／开发测试修复／整体浏览器交付的连续真实验证。真实模型未在本次触发并完成一次代码测试失败返修，该能力的本次证据来自 Fake＋真实 Node 故障回归。完整原内容管理工具、增量变更、Windows 和用户本人验收未验证。计划的语义覆盖仍依赖架构与设计评审，不能用程序结构校验宣称所有需求都已覆盖；测试通过也不保证验收充分。临时目录不属于永久证据归档。
