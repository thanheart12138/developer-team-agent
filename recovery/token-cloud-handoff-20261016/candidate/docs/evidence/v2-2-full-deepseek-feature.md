# v2.2 已有产品小功能全 DeepSeek 测试

## 范围与输入

- 2026-09-15；隔离的合成四则运算计算器，旧版正式需求／架构／Dev Design、六个产品文件及既有 Task 阶段记录均预置在临时工作区；不读取或发送真实任务、密钥文本或个人数据。
- 变更请求：新增只使用输入 A 的 Square 按钮；A＝3 得 9、A＝4 得 16；无效 A 显示 `Error`，随后改为 A＝4 应恢复得 16；保留四个二元运算与 Clear。
- 仅在本次测试进程清空 `model.KIMI_STEPS`，让固定文档路由也调用 DeepSeek；项目源码、正式配置和 `.env` 未改。按模型请求 Trace 核对 Provider；单 Step 最多 16 次逻辑调用，传输最多 3 次，整次运行最多 55 次模型请求／24 次 Worker 轮询。

## 步骤与期望

1. 在已验收 Task 上提交 `change_request`；Planner 应识别需求变更，生成 Draft／Review／Candidate，并由独立覆盖校验逐条核对。测试用户仅在候选包含 Square 且校验通过时批准。
2. 架构和 Dev Design 阶段应根据新旧正式文档决定修订或复用，保存决定和版本。开发须实际修改相关代码与测试。
3. 动态行动须通过 Node 测试、HTTP 健康检查、真实 Playwright 浏览器验证；`finish` 仅进入 `waiting_acceptance`。
4. 再用独立浏览器操作核对原始验收例子、错误后恢复、原有加法与 Clear，并监听页面脚本错误。

## 实际结果

- 首次试跑为了缩短成本把传输尝试设为 1：需求变更识别、候选生成／审批已通过；在架构 Draft 请求收到 `ReadTimeout` 后 Task 为 `failed`。共 9 次模型请求，Provider 均为 DeepSeek；失败检查点保留在第一次临时工作区。
- 恢复现有最多 3 次传输尝试后重新运行：共 27 次模型请求、11 次 Worker 轮询，所有模型请求 Trace 的 Provider 集合仅有 `deepseek`。首个行动为 `update_requirement`；候选覆盖校验 3／3，批准后正式需求更新。架构 Planner 选择 `update_architecture`，Dev Design Planner 选择 `update_dev_design`，两阶段都保存了 V2 正式版本和决定。
- 代码和 Node／Playwright 测试均新增 Square。后续 Planner 行动为 `modify_code → run_test → start_product → inspect → verify_product → finish`；Node 10／10，无跳过；HTTP 启动及 Playwright 通过。第 11 次轮询后 Task 为 `waiting_acceptance`，无失败原因。测试脚本停止了隔离 HTTP 服务。
- 独立 Chromium 操作通过：B＝`invalid`、A＝3 时 Square 得 9；A 无效得 `Error`，改 A＝4 得 16；Add 2＋3 得 5；Clear 得 0；页面脚本错误 0。独立复跑 Node 10／10。生成脚本还覆盖四则运算、Square 忽略 B、空输入、除零及跨操作恢复。
- 本轮项目后端机制测试 76 项通过，`git diff --check` 通过。

## 边界

- 这是隔离合成任务，候选审批由测试脚本模拟用户完成；没有把真实项目 Task 改成验收通过，用户本人尚未验收生成软件。
- 本次通过依赖测试进程中的 DeepSeek 路由覆盖；正式系统仍按当前配置在文档阶段使用 Kimi、开发阶段使用 DeepSeek。首次一次传输尝试的超时不计作功能验证通过，复跑启用了现有最多三次传输尝试的上限。
