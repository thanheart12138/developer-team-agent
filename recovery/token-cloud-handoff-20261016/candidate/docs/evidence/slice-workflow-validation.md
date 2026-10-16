# AI 原生逐业务切片流程验证

日期：2026-09-19。状态：机制已实现并通过 Fake 模型与真实 Node 测试；真实 DeepSeek 素材管理全链路已运行，但失败，不能认定流程有效。

## 已实现

- 新架构正式化后只创建绑定产品与架构哈希的 `docs/delivery-plan.json`，不再生成完整开发单元清单。
- Dev Design 只调用 Slice Planner 生成第一张结构化执行卡，保存到 `docs/slices/`；不生成共享契约及全部单元 Author／Reviewer 文档。
- Develop 按「当前切片实现与自测 → 程序独立执行当前和此前测试 → 真实通过后规划下一片」串行推进。
- Planner 每次只能返回 implement、complete 或 clarify。执行卡校验业务标识、目标、数据所有者、公共接口、产品路径、Node 测试文件和验收条件；测试、文档、脚手架或验证不能作为独立切片。
- 开发可用 `REPLAN:` 请求当前切片的内部文件、顺序或非公共接口重规划，重规划不得更换切片 ID；`BLOCKED:` 仅用于需求、数据所有者、公共接口语义、业务规则或验收需要用户决定的情况。
- 每个 Step 仍共用原 100 次模型调用预算，最多 12 个切片；全部切片通过后仍须全量测试、HTTP、真实浏览器和用户验收。
- 已有 `development-plan.json` 任务保持原逐单元恢复入口，不转换历史状态。

## 验证

新增机制测试使用 Fake Planner／Developer，但开发产物由受限工具真实写入临时工作区，Developer 先运行受控 `run_unit_tests`，程序随后再次执行真实 `node --test`。第一张素材新增切片通过后，第二次 Planner 调用能够读取真实通过证据并返回 complete；任务只在固定入口齐全后进入 test。另有校验用例证明纯 verification 切片被拒绝。

首次机制验证的全量后端回归 185 项通过；Python 编译、提示词注册表 SHA-256 和 `git diff --check` 通过。

## 真实 DeepSeek 结果

隔离目录：`/private/tmp/content-workbench-slice-v1-20260919`。从空工作区运行素材管理需求，产品与架构阶段完成，Dev Design 只生成第一张切片。真实运行没有要求用户参与内部工程选择，但最终为 `failed / develop`，未进入全量测试、启动或浏览器验收。

- 共发生 111 次 HTTP 尝试，其中 105 次取得可计量响应；另有两轮各 3 次连接失败。可计量总量 1,602,673 Token：输入 1,527,548，输出 75,125，缓存命中 606,848。
- 各阶段：产品文档 4 次／19,032 Token；架构 4 次／32,566；Dev Design 2 次／17,460；Develop 95 次／1,533,615。新流程消除了旧流程 774 万 Token 的全量 Dev Design 膨胀，但消耗转移到了 Develop。
- 系统记录 9 张切片为 passed，第 10 张 `app-delivery` 失败。然而该结果不可作为能力证据：第 2～9 张切片持续复用仅含 7 个 storage 断言的 `product.test.js`，程序只校验测试进程通过，没有校验测试是否覆盖当前卡片 acceptance，形成连续假阳性。
- Planner 曾把浏览器验证拆成独立切片，程序正确拒绝后，模型把内部校验升级为用户澄清。已修复为内部校验期间禁止 clarify，并补充回归测试。
- Planner 宣布 complete 时仍缺 `verify_product.py` 与 `implementation.md`，程序原先直接失败。已改为把缺失固定入口放入规划上下文并要求继续生成 `app-delivery` 切片，补充回归测试。
- 第 10 张切片范围包含完整 UI 与全部业务流程。Developer 在已有代码、执行卡和历史工具结果间反复读取、分析、`REPLAN` 和重新规划，最终耗尽 develop 的 100 次逻辑模型调用，未提交有效实现，错误为 `unit_submission_required`。

这次实测证明逐业务切片方向减少了前置设计成本和用户干预，但当前门禁仍有两个阻塞缺陷：切片测试与验收条件没有程序级覆盖绑定；最终 UI 交付切片过大，且 Developer 每轮携带不断增长的上下文，无法稳定收敛。

修复后的项目回归为 187 项通过；Python 编译、7 个提示词版本哈希和 `git diff --check` 通过。

## 未验证

- 切片 acceptance 与测试断言绑定后的真实通过率。
- 缩小最终 UI 交付范围并压缩 Developer 上下文后的收敛能力。
- 完整交付、启动和真实浏览器结果。
- 架构文本能否始终提供足够明确的数据所有权和公共接口；若架构本身含糊，新流程仍可能进入 clarify。
