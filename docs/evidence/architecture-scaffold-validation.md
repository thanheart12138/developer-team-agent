# 架构代码骨架流程验证

日期：2026-09-19。状态：机制测试通过；真实 DeepSeek 素材管理全链路未完成，失败证据已保留。

新任务在首轮架构正式化后，由 `architecture-scaffolder/v1` 一次返回结构化模块和文件清单。程序校验 `product/` 路径、20 个文件与 60000 字符上限、模块实现文件、唯一测试文件、固定入口和每模块 todo，然后写入代码骨架。骨架验证逐个执行 JavaScript `node --check`，再执行所有 Node 测试并要求实际发现测试；契约保存到 `docs/scaffold-contract.json`，绑定产品和架构哈希。

Slice Planner 与 Developer 升级为 v2。Planner 接收骨架契约和 `remaining_todo_files`，仍有 todo 时必须选择对应业务测试，不能 complete；Developer 必须把当前测试的 todo／skip 改成真实断言。程序在每张切片独立测试后再次扫描本片测试文件，仍有占位测试时强制判失败。这阻止 storage 测试冒充其他模块通过，并把模块接口、文件结构和应用装配提前到架构阶段完成。

骨架仅用于首轮新建且 `product/` 为空的任务。已有产品的架构返工、历史 `development-plan` 任务和明确跳过架构的任务保持原入口，不覆盖已有代码。

验证结果：新增定向用例真实创建模块、入口和两个 `test.todo`，真实 Node 测试能够发现占位测试，契约正确记录未完成文件；旧架构修订与复用回归通过。

## 真实 DeepSeek 全链路

测试根目录为 `/private/tmp/content-workbench-scaffold-v1-20260919`，整轮限制 220 次 HTTP、单 Step 100 次逻辑调用。实际 78 次 HTTP，输入 1,336,339／输出 72,127／总计 1,408,466 Token，其中缓存命中 336,256。分阶段如下：

| 阶段 | HTTP | 输入 | 输出 | 总计 |
|---|---:|---:|---:|---:|
| Product | 4 | 12,028 | 4,196 | 16,224 |
| Architecture＋Scaffold | 7 | 46,477 | 27,642 | 74,119 |
| Dev Design 首切片 | 1 | 11,577 | 420 | 11,997 |
| Develop | 66 | 1,266,257 | 39,869 | 1,306,126 |

架构骨架首次返回超过 20 个文件，程序在内部反馈后于两次纠正内生成 17 个文件、6 个模块和逐模块 todo 测试。`infra-storage-id-clock` 与 `material-crud-search` 两张切片一次通过，分别形成 6 项和累计 18 项真实断言。第三张 `topic-crud-link` 的删除验收依赖尚未实现的 `task.hasTaskForTopic`，原卡却只拥有 topic 实现和测试文件。模型实现了其余 topic 行为，但 34 项累计真实测试稳定为 33 通过、1 失败。

本轮据此发现并修复四个 Runtime 问题：骨架结构错误没有内部纠正；带分析前言的 `REPLAN:` 未被识别；重规划复用了首次规划历史；显式恢复复用了旧开发历史。对应机制测试已补齐。随后将自由文本重规划升级为 `request_slice_replan` 结构化工具，`slice-developer` 升为 v4。真实续跑中 DeepSeek 仍未调用该工具，而是反复读取和尝试在 topic 内注入替身，最终触发 `unit_development_no_progress`。因此 v4 的结构化协议只有机制测试证据，没有真实模型成功证据。

最终产物共有 61 个 Node 测试：33 通过、1 失败、27 todo。infra 和 material 已完成，topic 未通过，task、dashboard、ui 未实现；任务状态为 `failed / develop / unit_development_no_progress`。这证明架构骨架能提前固定模块和测试边界，也证明当前 Planner 没有在出卡前确定性校验跨模块验收依赖，Developer 仍可在大上下文中空转。不能声称素材管理完整交付，也不能声称 Token 已降低。

项目侧最终回归 193 项通过；全部 Python 源文件语法解析、8 个激活提示词哈希和 `git diff --check` 通过。真实生成软件的失败测试与 todo 如上保留，不计入项目机制回归成功。

## 后续修复与同一素材管理产物复验

继续运行经过多轮 Runtime 修复后的同一需求，6 个业务切片最终全部通过，生成产品 53 项 Node 测试全部通过。自动流程在浏览器验证返修阶段结束为 `failed / develop / unit_submission_required`，累计 184 次 HTTP：输入 6,861,504、输出 343,111、总计 7,204,615 Token，其中缓存命中 4,354,560。不能把该运行记为自主交付成功。

检查原始 Playwright 输出和 `verify_product.py` 前序操作后，确认剩余失败来自验证脚本自身：流程创建 4 条素材，只删除 Alpha 后应剩 3 条，脚本却在 DOM、刷新和最终状态中断言 2 条；脚本又创建全新隔离 browser context 验证 localStorage，而隔离 context 按浏览器语义不共享该存储。修正这些确定性错误，并为页面加入空 data favicon 消除浏览器自动请求的 404 后，真实 Chromium 全流程全部通过，页面运行期错误为 0。生成软件 53 项 Node 测试再次通过。

Token 暴涨的直接机制也已修复：原返修将数百行 UI 文件全文读入上下文，模型随后多次尝试整文件输出并被 8192 输出上限截断，未能调用提交工具。`read` 现在支持 `start_line`／`end_line`；单元开发读取超过 200 行的文件时默认只返回前 200 行、总行数和局部读取提示，小改动使用唯一精确片段 `replace`。`slice-developer/v6` 同步要求按错误位置局部读取，并在生成浏览器验证时先维护操作后的数量变化、遵守 localStorage 同 context 语义。项目完整 206 项回归通过。

本次没有再次发起一轮新的付费全链路。因此已有证据证明当前生成产品满足素材管理流程，也证明局部读取和替换机制通过项目测试；尚不能证明 DeepSeek 在全新任务中会稳定遵守 v6 并显著降低总 Token。
