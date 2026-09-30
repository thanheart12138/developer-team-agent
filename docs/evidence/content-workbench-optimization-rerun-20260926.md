# 素材管理全流程优化后复测：DeepSeek 与 Luna

日期：2026-09-26。目标按优先级判断：先看是否在产品阶段后无人干预地产出满足需求的软件，再比较 Token。两组均从隔离 SQLite 和空工作区启动，使用相同原始需求、固定约束、300 次模型 HTTP 总上限和单阶段 100 次逻辑调用上限。产品阶段由测试控制核对并批准候选；Luna 的具体交互追问由测试控制在产品阶段回答。进入架构阶段后没有人工修改生成文档、代码、测试、任务状态或预算，也未续跑失败任务。两组生成的正式产品候选、架构和切片不同，不是逐字固定设计的严格 A/B。

## 本轮改动与机制验证

- 先更新 `docs/DEV_DESIGN.md`：架构骨架中的模块文件路径必须与 `files` 键逐字一致；浏览器运行前只拦截可确定的脚本契约与错误排序断言，并把问题反馈给有界返修。
- `architecture-scaffolder` 提示词升为 v5；骨架解析及重试反馈指出具体模块、错误路径和 `product/` 路径。Worker 增加验证脚本预检，并在首次验证及返修复验前使用。
- 后端 `pytest -q`：217 passed；提示词注册表加载成功；`git diff --check` 通过。旧 DeepSeek 失败脚本的 `sorted(...)` 错误断言被预检识别为 `verification_script_expected_order_invalid:875`。正式 MySQL 核查待处理事件 0、运行中任务 0 后，旧 Worker PID 30891 退出，新 Worker PID 66871 加载当前代码。正式任务状态与路由未修改。

## 两组真实调用结果

| Provider | 任务终态 | 自动流程走到哪里 | HTTP 请求 | 已报告输入 Token | 已报告输出 Token | 已报告总 Token | 已报告费用 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| DeepSeek thinking | `waiting_acceptance / verify_product` | 5 个切片、96 项 Node 测试、启动和生成脚本验证通过 | 57 | 4,310,598 | 442,317 | 4,752,915 | 响应未提供美元费用 |
| OpenRouter Luna medium | `failed / develop / unit_development_no_progress` | 骨架与前 3 个切片通过，第 4 个切片停滞 | 62 | 610,334 | 72,298 | 682,632 | 0.10892833 美元 |

Token 来自 `summary.json` 中收到的模型响应 usage 之和；HTTP 计数包含传输请求，因此 DeepSeek 57 次请求对应 56 份 usage，Luna 62 次请求对应 61 份 usage。Luna 前 19 次 HTTP 消耗在产品阶段重复追问：测试控制起初反复提供不对应问题的旧布局回答；第 19 次请求中断后，补足页面内表单、状态下拉框和选题专用按钮的产品选择并从同一产品阶段继续。此中断和回答均发生在产品审批前，应计入成本，不能据此宣称两模型产品阶段使用完全相同的人工输入。

Luna 上轮停在架构骨架文件路径不一致，本轮骨架通过。第 4 个切片是「从选题创建或打开内容任务」。生成代码和该切片的真实 Node 断言已经通过，但模型连续重复调用 `run_unit_tests`，未调用交接动作，最终触发无进展上限。这是本轮可观察的失败机制，不能单凭该结果归因为业务实现能力不足。证据见该任务 `workspace/1/evidence/slice-progress.json`、`workspace/1/traces/develop/1/000260-model_response.json` 至 `000284-state_transition.json`。

DeepSeek 的自动状态不能作为完整交付结论。生成的 `verify_product.py` 忽略 Worker 传入的位置 URL，自己启动临时 HTTP 服务；浏览器部分只检查四个区域存在，没有执行需求中的素材编辑、选题编辑和跨模块完整操作。它违反当前 Dev Design 中「读取传入 URL，不自行启动服务」的验证脚本契约；本轮静态预检未识别这类脚本。生成脚本返回 0，Worker 因而进入 `waiting_acceptance`。证据见该任务 `product/verify_product.py` 与 `evidence/verification-report.md`。

## 独立产品核查与缺口

使用本机 Chrome 和独立 Playwright 脚本实际操作 DeepSeek 软件，核查了新增素材、选题关联、创建任务、草稿和逾期状态、工作台计数、刷新后读取、重复创建不重复、空标题失败后保留输入并修正、关联素材取消／确认删除，以及发布后待办和逾期归零；页面脚本异常为 0。另以独立静态服务在同一端口停止并重启，确认浏览器 `localStorage` 中的素材仍可读取。执行脚本保留于 `/private/tmp/independent_content_workbench_browser_20260926.py` 与 `/private/tmp/independent_content_workbench_restart_20260926.py`；脚本成功输出分别含 `PUBLISHED_COUNTS_OK` 和 `SERVICE_RESTART_PERSISTENCE_OK`。这验证了上述操作，不替代所有需求验收。

独立审查发现确定的需求缺口：原需求与批准的产品候选均要求「新增、查看、编辑和删除素材／选题」，但 `product/src/materials/materials.js` 的视图只渲染删除按钮，提交处理始终调用 `repo.create(fields)`；`product/src/topics/topics.js` 同样没有编辑入口，提交处理始终调用 `repo.create(fields)`。仓储层的 `update` 通过 Node 测试，真实页面却无法让用户编辑。这是切片验收与浏览器验证没有覆盖用户动作导致的假阳性；不能把 DeepSeek 本轮记为「满足确认需求的软件」或用户已验收。

## 对比结论与下一步问题

相对 2026-09-25 的失败基线，DeepSeek 本轮报告总 Token 从 11,817,765 降到 4,752,915，并首次自动到达 `waiting_acceptance`；两次生成结果与失败路径不同，不能把减少量单独归因于本轮修复，更不能因流程状态认定完整交付。Luna 从骨架失败推进到第 4 个切片，但仍未产生可验收软件，较低 Token 主要体现较早停止。

下一项阻塞是验收门禁与用户需求的覆盖关系：需由用户决定是否先把「关键用户动作的可执行浏览器证据」和「生成脚本必须使用传入 URL」纳入正式验证设计，再实施与复测。Luna 另有测试成功后重复自测而不交接的问题。两项均未在本轮修复；两模型的软件均未由用户验收。
