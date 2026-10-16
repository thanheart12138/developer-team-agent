# Planner 跨阶段证据复用与具体纠错修复

日期：2026-10-03。用户在前轮失败分析与修正建议后回复「可以」，批准局部修复；本轮不追加真实模型调用，不续跑失败任务。

## 结论

机制修复已实现并验证，空闲正式 Worker 已加载。跨阶段需要同版本内容时，现有 inspect 恢复已存 Trace，不再次执行产品文件 read；引用可定位且包含版本适用性。Planner 看见当前门禁任务及建议行动，非法决定得到具体字段与原因，原有一次纠错、三次调查及十二次行动上限保持。

相关集合首次 96 通过／1 个新夹具断言失败，修正该断言后单项通过；没有再重复整套。旧真实失败副本的实际调查 Trace 离线恢复核对通过，读取工具与模型 HTTP 均为零，旧非法 inspect 回复在新跨阶段候选中合法。**这不证明真实模型下次会正确选择推进或软件已完成交付。**

详见 [状态、离线核对与加载 JSON](planner-evidence-reuse-validation-20261003.json) 。

## 复现依据与先行设计

输入为 [前轮后续交付失败](context-slimming-delivery-real-20261003.md) ：Task 1 failed／start_product／version 67，Kimi 两次选择已读而不在 remaining_files 的 `tasks.js`。该版本浏览器与 Node 已通过，调查正文仅随一次决定提供；下一阶段正文省略且没有合法恢复入口，纠错也没有给出实际非法字段。

先在当前 ARCHITECTURE／DEV_DESIGN 记录用户确认的恢复及纠错规则，再修改 Worker；原用户设计及历史失败记录保留。没有为了测试通过把 failed 写成待验收、关闭原目标或修改产品验收条件。

## 实际修改

| 修改点 | 实际效果 |
|---|---|
| `saved_bug_inspections` | 按同事件 Trace 的实际路径、SHA、正文 SHA 和当前文件 SHA 核对；只恢复当前有效的正文，缺失／损坏／过期不复用 |
| inspect 候选及执行 | 跨 Run 可恢复已存证据，记录 `content_source=saved_inspection` 与原 `reused_from`；不调用 read。当前 Run 同版本路径不重复调查，恢复与新读取共用原三次额度 |
| compact 引用 | 给出实际 `evidence_ref`、`matches_current_file`、`available_for_inspect` 和正文是否在当前请求；正文紧接下一次决定提供后仍省略 |
| 当前阶段事实 | 记录最近开发 Run、当前阶段门禁目标、原反馈的历史角色及 suggested_action；finish 建议仍由原实际版本和目标门禁决定 |
| 协议纠错 | 返回 JSON 对象、action、reason、inspect path、非 inspect 的非空 path 和澄清问题的具体错误；有有效旧正文时在一次纠错内恢复，不执行非法行动；仍非法则原样失败 |

仅修改 `backend/app/runtime/worker.py`、直接相关的 `tests/test_context_slimming.py` 及记录文档；保留此前全部未提交改动。没有新增模型工具或行动、依赖、数据库字段或设置，没有改生成产品文件、Provider、thinking、开发协议、自测／提交或最终独立门禁。

恢复证据仍可能需要一次模型 inspect 决定，计入原行动与调查额度；本文不声称调用次数、实际 Token 或稳定成功率降低。程序为核对 SHA 读取文件字节，不等同于模型重复取得源码的 read 工具结果；本轮断言的是同版本源码不重复执行 read。

## 验证输入、边界与结果

命令：

```sh
.venv/bin/python -m pytest tests/test_context_slimming.py tests/test_worker_events.py -q
.venv/bin/python -m pytest tests/test_context_slimming.py::test_planner_corrects_same_run_repeat_with_saved_body -q --disable-warnings
.venv/bin/python -m py_compile backend/app/runtime/worker.py tests/test_context_slimming.py
git diff --check
```

- 新增 14 个参数化回归实例，覆盖跨阶段恢复零重复 read、同 Run 非法重选的具体 path 纠错及缓存恢复、正文省略、缺失／正文损坏／非字符串／文件改版、三次额度耗尽、两次非法仍失败，以及各非法字段。固定原目标与旧 Trace 字节保持。
- 与现有 Worker 事件及精简回归共 97 个实例：首次 96 通过／1 失败。新用例只准备已读 `a.js`，没有其他未调查候选，实际同时产生 action 和 path 错误；夹具却假定第一个错误必然是 path。改为按具体 field 核对 path 及拒绝码，没有改实现或削弱该断言，单项复验通过。原首次失败保留，不与后续一项相加冒充 98 项。
- 原 Worker 回归同时覆盖过期测试证据阻止启动、原目标不因普通浏览器成功消失、旧／改变版本拒绝 finish 等；上述已通过，不另重跑相关集合。
- 编译和差异检查通过。测试中的 Kimi 响应为 Fake，只验证合法恢复、拒绝及状态控制；不替代真实模型收敛。现有 datetime 弃用警告保留，没有顺手修改。

### 真实旧证据离线核对

临时目录 `/private/tmp/planner-evidence-reuse-fix-20261003-pcsu1moo` 先写结构 README，再保存零模型调用审计及 Worker 加载脚本。

`audit_source.py` 只读旧真实失败数据库和 Trace，禁止 `httpx.Client.stream` 及工具 execute，使用新缓存核对函数恢复原任务的 `product/src/tasks/tasks.js`；实际保存路径、原 SHA、正文与当前文件 SHA 一致。原调查属于 test Run 33，启动 Run 34，可跨阶段恢复，原一次调查未用完三次额度。将实际 Trace 1355 的原 JSON 回复按新候选校验，错误为空。

源任务仍 failed／start_product／67，源数据库和整个工作区指纹保持。没有运行 Planner、启动服务、改 Task 状态或给原目标写关闭；这是恢复机制的真实数据核对，不是真实 Kimi 复验。

## 空闲加载及保持

按项目默认加载规则，只读确认正式库零 pending 事件、零 pending／running 任务后，核对原 Worker 命令和工作目录，仅重启 Worker **73713→27466**。使用原内存认证和代理，不保存环境正文或认证头，不改 `.env` 或密钥文件。

前后正式 24 Task 的状态／版本、全部 StepRun 状态／逻辑计数、Event 状态及 Trace 16,908／消息数量快照相同；原素材平台以及前两轮隔离副本的数据库与整个工作区指纹相同。新进程存活、目录和代码 SHA 匹配。原素材平台 PID 31445、http://127.0.0.1:61626 保持 HTTP 200，Task 1 waiting_acceptance／version 73；失败副本仍 failed／start_product／67，未续跑。

本轮新增模型 HTTP／Token 为零。无产品服务重启、schema／凭据修改、Git 提交或推送。永久 JSON 保存必要核对结果和版本，临时详细快照可能被系统清理。

## 当前边界与下一步

本轮「机制实现和验证」完成；修复后真实 AI 完整收尾、总 Token 收益及用户最终验收仍未完成。下一步若批准有界真实调用，可只沿原 start_product 断点继续，不重新开发或切片，不把剩余预算自动当作新授权。
