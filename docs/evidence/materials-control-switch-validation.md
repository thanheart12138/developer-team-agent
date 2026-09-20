# materials 推进违约后的独立实现验证

日期：2026-09-20。结论：控制流切换已实现，241 项项目回归通过；一个真实 DeepSeek 局部样本完成 materials 实现、Runtime 自测、提交和独立回归。完整素材管理产品未交付、未验收，真实页面保存操作未通过。

## 原问题、依据与确认

既有五个有效 materials 局部样本共 42 次调用、396,835 Token，全部失败。ToolResult 错误码、下一请求显式反馈、重复读取门禁和跨批写入后强制自测，都未稳定改变同一对话中的读取行为。详见 `content-workbench-transactional-repair-validation.md`；失败记录保留，不用本次局部成功覆盖。

用户确认：首次违反推进约束时结束原 Developer，以 Runtime 确认的依赖、接口映射和 owned_files 开启独立受限实现。优先完成需求，成本其次；不再微调同类提示或反复付费重试。新实现及修复最多四次逻辑调用，唯一局部样本最多十二次请求尝试，传输重试也计入。

当前工作区 dd56 起初缺少源任务 e034 的最新门禁和证据。先同步 20 份有差异的文件及新增文件；覆盖前的本地副本保存在 `/private/tmp/materials-control-switch-baseline/original`，源任务未修改。随后先更新当前有效架构和 Dev Design，再实施控制流。没有提交 Git、修改凭据、正式数据库或生产配置。

## 最小实现与取舍

- `worker.py`：首次 `covered_read_requires_write_test_or_replan` 落盘后立即结束旧循环，不再执行该响应后续动作；恢复可从检查点识别切换，不再次调用旧对话。
- `slice_workflow.py`：使用独立 history_key，并把切换、文件版本、阶段、已用额度保存在 `evidence/slices/developer-<history-hash>.json`。每次请求前预留调用额度，崩溃不返还，仍受原 Step 总预算约束。
- 依赖包复用同一接口所有权校验，核对依赖是否已交付、真实文件是否存在、文件哈希是否仍匹配通过证据。未知、歧义、越界、缺失或证据过期均停止，不猜路径。
- 独立 `slice-implementer/v1` 只收到当前卡、接口—文件映射、当前拥有文件及必要依赖全文、最新失败证据，不携带旧对话。模型仅可 `write`、`replace` 或请求重规划；工具入口同时拒绝隐藏的 read、exec、自测、提交及越权写入。
- Runtime 处理完整写入批次后直接运行当前及全部前置测试；未修改立即停止，失败才进入下一次独立修复。真实通过且当前卡 todo／skip 清零后，Runtime 调用原提交校验，后续原独立回归仍保留。提交是 Runtime 按已确认规则完成，不能表述为模型自主调用提交工具。
- 恢复保持当前 developing 尝试号；已通过自测的中断直接恢复提交，已提交且版本一致则不调用模型。进程若在预留额度后、实际写入前中断，本次尝试明确停止，不自动重发付费请求。

此方案增加确定性的调用切换和少量状态。代价是受限实现预载必要依赖，单次 Token 不保证更低；依赖证据不足时直接阻塞，不能靠模型继续猜测解决。

## 机制回归

执行 `/Users/aideihua/AI-study/ai-agent-product/.venv/bin/python -m pytest -q --disable-warnings`：**241 passed**。

其中新增 `tests/test_slice_control_switch.py` 的 17 项回归，使用 Fake 模型和真实 Node，覆盖完整批次执行、旧对话中止、独立历史、依赖缺失／过期／未知、工具权限、无修改停止、四次额度与 Step 共用额度、todo 拒绝、重规划／业务阻塞，以及切换落盘前、预留额度后、自测通过后的中断恢复。另通过原 handle_develop 路径验证同一尝试恢复和独立回归。Python 编译、提示词哈希和 `git diff --check` 通过。

这些只证明机制，不替代下述真实模型证据。

## 唯一真实样本与执行故障

- 入口：`tests/materials_control_switch_validation.py`，不被 pytest 自动收集。
- 来源：`/private/tmp/content-workbench-full-v5b-20260920/workspace/1` 的当前 materials 卡、docs、product 和切片进度；两张基础切片已通过，共 18 项前置测试。
- 输出：`/private/tmp/materials-control-switch-v1-20260920`。只复制夹具到新隔离目录，不继承旧模型历史、数据库或工具摘要。
- 调用正式 `run_slice_developer`，不人工修改生成代码，不运行其他业务切片或 Planner。
- 先只读核实 16 个接口的映射，两个只读依赖为 `product/js/core/storage.js` 和 `product/js/core/task-view.js`，哈希与通过证据一致。

第一次在沙箱内连续三次 ConnectError，没有收到模型响应、没有产物修改。保留 `summary-transport-failure.json`；Provider 没有返回 usage，不把缺失计费信息解释为已核实的零费用。

网络续跑第一次被自动审批拒绝，理由是具体载荷授权不足。核对实际请求后，确认快照仅含生成的 materials 实现／测试，其他上下文为当前卡、文件清单和接口映射；未发现凭据路径、认证头、token 或私钥混入载荷。向审批提供原始用户授权和核查结果后，同一命令获准执行。拒绝期间没有绕过审批发送请求。

使用 `--resume-transport` 续跑同一数据库、同一夹具和累计计数；该选项仅允许“无模型响应且无文件改动的初始 ConnectError”恢复。不是新建第二个付费模型样本，也没有重置十二次上限。

## 真实流程及 Token

| 有效响应 | 历史／动作 | 结果 | 输入 Token | 输出 Token | 合计 |
|---|---|---|---:|---:|---:|
| 1 | 普通 Developer／read | 读取依赖 | 7,137 | 188 | 7,325 |
| 2 | 普通 Developer／read | 继续读取 | 10,187 | 179 | 10,366 |
| 3 | 普通 Developer／read | 继续读取 | 8,513 | 141 | 8,654 |
| 4 | 普通 Developer／read | 首次完整重复读取被拒 | 12,275 | 132 | 12,407 |
| 5 | 普通 Developer／read | 首次违反推进约束，立即终止旧对话 | 8,972 | 196 | 9,168 |
| 6 | 独立实现 1／write | 写 materials 实现；Runtime 自测为 18 pass、8 todo，拒绝提交 | 9,794 | 1,739 | 11,533 |
| 7 | 独立实现 2／write | 将八个 todo 改为真实测试；Runtime 自测通过并提交 | 14,110 | 3,296 | 17,406 |

有效响应 **7 次、76,859 Token**：输入 70,988、输出 5,871、缓存命中输入 28,416。旧对话 47,920 Token，独立实现两次合计 28,939 Token。连同三个连接失败尝试，总请求计数 **10／12**；Step 逻辑计数 8，其中一次逻辑调用包含三次失败连接尝试。受限实现使用 **2／4** 次额度。

最终局部状态 `SUBMITTED_FOR_TEST`，自测与独立 Node 回归均为 **26 tests、26 pass、0 fail、0 skipped、0 todo**。只修改 `product/js/modules/materials/model.js` 与 `product/tests/materials.test.js`；全部非拥有文件哈希不变。Search／Validate 的 import 指向真实 `task-view.js`。

仅有一个成功样本，不声称稳定成功率。相比最后一个失败样本的 74,601 Token，本次多用 2,258 Token，但完成了实现和测试；不能把此前五轮总消耗与本次单样本相比后声称节省比例。

## 独立验收与真实浏览器边界

开发助手依据当前执行卡另写独立验收脚本，不修改生成代码。`independent-acceptance.mjs` 五组实际 Node 测试全部通过：无效新增保留输入及恢复、排序／编辑／失败原子性及恢复、搜索、删除影响与关联清理／保留选题任务，以及新模块实例读取已保存数据。该脚本使用内存 localStorage 替身，不能代替浏览器持久化证据。

随后真实启动隔离产物的本地 HTTP 服务和 Chromium：

- 首页 HTTP 200。
- 在真实页面填写标题、笔记并点击保存：**未显示、未持久化，页面操作不通过**。
- UI 骨架仍引用不存在的 `relations.js`、`search.js`、`validate.js`，服务器记录 404；这些文件引用属于未开发的 UI／其他模块，本轮没有修改它们。
- 在同一真实浏览器内直接调用已实现的 materials 模块：空标题失败后正常新增、大小写无关搜索均通过；同一 browser context 刷新后数据仍存在，使用真实 localStorage。
- 页面 `pageerror` 数为零不代表成功，模块加载 404 和实际保存失败已单独保留。临时服务及 Chromium 在验证结束后关闭。

因此必须分别评价：**控制流机制通过；真实模型完成当前业务模块实现／测试，Runtime 完成自测／提交；完整软件用户操作未通过、未验收。** 不扩大范围修 UI，不追加付费样本。

## 证据定位与运行实例

- 原始请求、Trace、检查点、提交状态和用量：输出目录下 `sent-requests/`、`workspace/1/traces/`、`workspace/1/evidence/`、`summary.json`。
- 独立验收：`independent-acceptance.mjs`、`independent-acceptance.log`。
- 实际页面与浏览器模块验证：`browser-check.py`、`browser-check.json`、`browser-page.png`。
- 夹具和本次 Runtime 文件哈希：`input-manifest.json`。
- 原始目录位于临时空间，存在被系统清理的留存限制；本报告保留结果、成本、失败与验证边界。

现有 API／Worker 的进程工作目录均为 `/Users/aideihua/AI-study/ai-agent-product`，不加载 dd56 工作区；本轮没有可重启的受影响服务。真实验证已直接加载 dd56 新代码，不代表主工作区服务已更新。
