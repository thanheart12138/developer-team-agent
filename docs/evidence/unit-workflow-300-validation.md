# 模块／功能流程：300 次预算追加验证

## 范围与预算

2026-09-17，用户授权累计真实 DeepSeek HTTP 请求上限提高到 300 次，原三轮 30 次计入，传输重试同样计入。手动入口 `tests/unit_workflow_deepseek_validation.py`，普通 pytest 不执行付费测试。正式 Step 默认 100 次逻辑调用、业务库、Provider 路由不变。

只恢复隔离固定设计探针因测试预算耗尽的 Task／StepRun，保留原摘要 `summary-before-300.json`、模型 Trace、检查点和调用计数；未人工修改生成代码。原自主设计澄清任务保留，另建同需求隔离复测，检查当前提示和依赖设计上下文。

四轮累计实际 HTTP 40 次，完整 usage 返回 40 份：输入 175,758、输出 53,840、总量 229,598 Token。汇总 `/private/tmp/unit-workflow-300-usage.json`，含之前 30 次，不重复计入续跑前的摘要。不宣称成本收益。

## 固定设计开发探针续跑

目录 `/private/tmp/unit-workflow-development-probe-20260917`，追加日志 `/private/tmp/unit-workflow-development-300.log`。实际新增 3 次 HTTP，累计 33 次。恢复时两个 math 功能已通过，ui 文件未齐；模型补齐 UI 测试、实现说明与浏览器脚本，程序逐单元测试后执行全量 test、start_product、verify_product，最终 waiting_acceptance，无失败原因。

全量 Node 43 项通过、无跳过；生成 Playwright 脚本使用系统 URL 验证通过。访问地址 `http://127.0.0.1:49962`，隔离产品进程 PID 88821。

独立 Chromium 操作 18 组通过，页面异常 0：正负数两个按钮，±1000 边界，空白／非数字／小数／正负越界提示「输入错误」，每次非法输入后恢复正常求和。证据 `independent-browser-300.json` 与截图 `independent-browser-300.png`；独立脚本 `/private/tmp/unit-workflow-independent-300.py`。

此探针的设计为预置合成输入，只证明真实模型开发及程序验证链路，不证明自主架构和设计成功，用户本人验收未执行。

## 自主流程复测

目录 `/private/tmp/unit-workflow-full-300-20260917`，日志 `/private/tmp/unit-workflow-full-300.log`。从正式合成需求进入架构阶段，无预置架构、开发计划或 Dev Design。新增 7 次 HTTP 后 failed／architecture_docs，原因 unit_plan_validation_failed，累计 40 次，未触及 300 次预算。

正式架构已生成，但三个计划候选均把 ui-input-validate、ui-render 标为 ui 模块的 feature，同时把 entry-assembly 标为同一 ui 模块的 module，违反整模块单元不能与同模块功能单元并存的规则。三次 unit_plan_module_feature_overlap 反馈后模型仍原样保留冲突；程序没有猜测修改单元类型，未进入逐单元设计或开发。复现证据是架构 Run 1 的 000022、000025、000028-validation.json。完整真实自主链路仍未通过，增加调用总预算不能解除此有界纠正失败。

## 当前必要上下文对照授权

用户授权重新测试不自动携带最近交互的策略。仅在隔离手动入口启用：不投影历史完整交互或历史摘要，仍保存原始 Trace／账本／检查点；当前设计、当前单元及依赖文件快照、文件清单和未解决失败继续提供。模型明确请求的最近读取／查询结果作为当前请求数据提供，成功写入的旧参数与确认不再回传。固定同一需求与预置设计先复测开发，再复测无预置设计流程，共用累计 300 次 HTTP 上限，已有 40 次计入。正式服务不切换策略。

## 项目回归

本轮完整后端 pytest 137 项通过；手动入口语法检查、差异检查通过。本轮只修改手动测试入口和证据文档，无服务实现修改，无需重启正式服务。
