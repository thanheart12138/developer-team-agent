# 开发自测协议：从空工作区完整 DeepSeek 验证

日期：2026-09-18。结果：failed／develop，unit_development_no_progress。完整从零交付未通过，用户未验收。

## 范围与预算

用户要求从头重新测试，并明确每轮都有 300 次模型调用机会。每轮单独计数，传输重试计入实际 HTTP；不再以之前各轮的 287 次限制本轮。正式 Worker 的单 Step 逻辑预算未修改。

同一合成任务：math／ui 两模块，add 与 squareSum 功能、两个带 label 的输入框、求和与求和后平方、-1000..1000 整数限定及错误后恢复。要求被测试系统生成产品文档、架构、模块／功能计划、共享契约及单元 Dev Design，再逐单元开发、自测、提交与独立测试，最后真实启动和浏览器验证。本测试不是更大的内容管理工作台基准，也不是任意软件生成能力验证。

主命令：PYTHONPATH=. .venv/bin/python tests/unit_workflow_deepseek_validation.py /private/tmp/unit-full-self-test-corrected-20260918 4 --full-flow；日志同目录名加 .log。起始值 4 是本轮入口错误样本已消耗请求，不是往轮累计。实际主工作区为空，不预写正式产品文档、架构、计划、设计、代码或测试；初始需求仅作为用户 Message。全部 Provider 使用 DeepSeek，运行原正式机制与自测协议，不注入故障，不复用产品夹具，不代模型提交，不跳过独立门禁。

## 测试控制与证据边界

第一次入口 /private/tmp/unit-full-self-test-deepseek-20260918 仍沿用旧架构探针预写 product.md 的行为，使产品门径输入被标成 approved_product。发现后停止等待审批的隔离进程，保留 4 次请求、响应和候选；修正测试入口后使用新的空工作区。该入口样本不作为从零流程证据，成本仍计入本轮上限，未删除原始记录。

修正后产品文档从 initial_request 生成。测试控制读取产品候选，核对原需求核心范围，通过原 document_approval Event 放行后续阶段。product-approval-review.json 保留候选哈希、审批范围和格式解释：候选选择严格整数字面量，并把错误统一展示于 result；不宣称这些边界已经被真实用户验收。测试控制审批属于模拟验收者参与，不能描述为完全没有任何外部审批。架构、详细设计、工具执行和交接由被测试系统完成。

发送上下文为固定合成需求及本轮生成设计、代码和真实工具结果，不发送项目后端源码或个人数据；认证不进入模型输入。实际请求保存在 sent-NNN.json，工具与模型响应保存在 workspace/1/traces，检查点／进度／版本证据在 evidence。

## 当前进展

产品文档通过测试控制审批，架构与开发计划生成 math／ui 两模块、math_add／math_square_sum／ui_validation／ui_interaction 四个 feature，具有文件所有权和依赖顺序。共享契约及所有单元设计最终通过系统评审，开发只完成加法，平方自测失败并停止；UI、集成、启动和浏览器验证未执行。

## 澄清与同轮恢复

页面交互设计两次 revise 后，第三次评审要求 clarify：验证脚本的 URL 由系统还是外部调用方提供。核对 Worker handle_verify 实际执行 python verify_product.py {task.result_url}，明确是系统已启动服务后自动传入 argv[1]。测试控制只通过原 user_message Event 提供已实现的运行事实，不新增业务决定、不改生成文档；runtime-url-answer.json 保存问题、回答及源码来源。恢复命令在同一工作区使用 --full-flow --resume，继续本轮 28 次计数及同一设计 StepRun 预算，没有重置预算。summary-before-runtime-url-answer.json 保留第一次 waiting_user 状态；恢复日志 /private/tmp/unit-full-self-test-corrected-resume-20260918.log。

因此本测试包含产品候选放行与运行事实澄清两次测试控制介入，不能陈述为完全无人干预。主测试仍未预置或人工修补设计／代码。

## 实际失败与定位

加法单元创建实现与测试，首次写入 overwrite 标志错误，模型自行纠正；run_unit_tests 9 项通过，再显式提交，后续程序独立测试也通过。平方单元创建 square-sum.js 与 square-sum.test.js，主动自测失败：测试按共享契约从 ./index.js 导入 squareSum，而公共入口没有该导出。实际错误 SyntaxError: The requested module './index.js' does not provide an export named 'squareSum'。

计划把 product/src/math/index.js 唯一分配给 math_add，math_square_sum 只拥有 square-sum.js 与其测试。共享契约要求 squareSum 经公共入口导出；加法设计又说明由其他单元负责 squareSum 导出。计划／共享契约／单元设计未明确一个有权限完成公共入口装配的路径。数学计算实现能写出，但不能在当前所有权内完成其验收接口。

模型尝试修改 index.js，程序返回 unit_write_outside_owned_files，所有权保护正确生效。随后模型无工具回复已准确描述设计缺口并提出 BLOCKED 问题，但前面还有解释段落，未以 BLOCKED: 开头。当前程序按 startswith 判断，不识别这次阻塞，要求继续提交；模型又读依赖，最终触发 8 次无文件进展停止。不能把这个终止仅解释为「模型不愿自测」：本轮它确实主动自测，并收到一个无法在原所有权内解决的真实失败。

关键 Trace 位于 workspace/1/traces/develop/1：000133-tool_result.json 为加法自测通过，000194-tool_result.json 为平方自测失败，000204-tool_result.json 为越权写入拒绝，000206-model_response.json 为夹带 BLOCKED 的设计缺口说明。目录末级 1 为阶段尝试序号，数据库开发 StepRun ID 为 4。已生成四个数学实现／测试文件，无 index.html，没有产品服务，UI 及浏览器验证标为未执行，不以独立补文件或测试代替原流程成功。

## 成本与结论

本轮实际 50／300 次 HTTP，入口错误样本 4 次，真正从初始消息的流程 46 次（包括同轮澄清后恢复）；全部 50 份完整 usage 可核对。入口样本输入 9,988／输出 4,950／总量 14,938 Token；主流程输入 520,669／输出 62,710／总量 583,379 Token；本轮合计输入 530,657／输出 67,660／总量 598,317 Token。round-audited-results.json 保存两目录的汇总，先前其他轮 287 次不合并为本轮上限。未耗尽预算，停止源自设计／所有权冲突和有界控制，不应靠放宽上限续跑。

自测工具、失败结果反馈和文件所有权门禁在真实从零任务中运行；它们不能弥补生成设计本身的跨单元装配缺口。固定夹具的上一成功样本不代表自主设计成功，本轮失败保留。开发助手建议优先评审计划、公共接口装配职责与文件归属的一致性，以及阻塞状态的可靠传递；尚未修改服务实现、生成设计或正式任务状态。未验证更大的内容管理工具能力、Windows、稳定成功率或用户本人验收。
