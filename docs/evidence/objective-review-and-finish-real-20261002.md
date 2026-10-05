# 已提交版本的原目标审查与 finish：真实进入待验收

日期：2026-10-02。用户「授权」明确允许将隔离产物的验证脚本、运行结果和原目标发送给 DeepSeek，并按现有流程执行 finish；Planner 可能调用 Kimi，所有 Provider／重试共用最多四次 HTTP。不重跑产品、规划、切片或开发，不修改正式任务。

## 当前结果

**隔离返修实例已真实进入 waiting_acceptance，原目标 E4-1 在该实例中闭合。**自动验证和目标审查完成，用户尚未验收。此前两次导航超时根因仍未确认，本次成功不是导航修复或稳定成功率证据。

- 实际 Worker 使用未包装的原 `verify_product.py` 与系统 Chrome，在当前地址执行完整流程，退出码 0，无 skip。
- 全量 Node：102 passed／0 failed／0 skipped／0 todo。没有为本轮增加测试或改产品业务代码。
- DeepSeek 独立只读审查确认原缺陷覆盖：页面编辑已有素材笔记、已有选题角度与优先级，显式保存，不增记录，刷新保留。操作与断言引用逐字匹配脚本，关闭结果绑定当前代码版本。
- Kimi 正常 Next Action Planner 先 inspect 当前素材模块，再提议 finish；程序重新核验目标、测试／浏览器版本及服务可访问性，写入 waiting_acceptance。没有人工设置目标闭合或待验收状态。
- 实际三次 HTTP，三份有效响应用量，未发生传输重试或 Provider 降级；总计 88,591 Token。

## 调用与成本

| HTTP | 模型与行动 | 输入 Token | 输出 Token | 总 Token |
|---|---|---:|---:|---:|
| 1 | DeepSeek flash thinking，原目标独立审查 | 13,949 | 14,007 | 27,956 |
| 2 | Kimi for coding，Planner 选择 inspect 素材模块 | 27,274 | 414 | 27,688 |
| 3 | Kimi for coding，Planner 选择 finish | 32,553 | 394 | 32,947 |
| 合计 | 本轮目标审查及完成门禁 | 73,776 | 14,815 | 88,591 |

DeepSeek 第一份响应报告 reasoning_tokens=13,619；这是输出 Token 的组成，不额外相加。Kimi 第三份响应报告缓存 Token 25,856；不同 Provider 的缓存字段不能直接当成统一全轮缓存成本。上限四次，实际第三次完成后停止，剩余一次未使用。

从前述同一返修起点到本次待验收，原轨迹 12 次 DeepSeek、交接续测 4 次 DeepSeek、本轮 1 次 DeepSeek＋2 次 Kimi，合计 19 次 HTTP／696,468 Token。这不包括更早的产品、规划、开发及失败实验，不是软件从零生成成本，也不是严格 A/B 或稳定成功率。

Kimi inspect 的直接依据是当前素材文件哈希与旧验收调查哈希不同；它读取 `product/src/materials/materials.js` 的当前证据后完成。两次 Planner 合计 60,635 Token，表明后续决策输入仍有成本，不因整体到达待验收而宣称 Token 目标已经全面达成。本轮没有优化 Planner 或改提示词。

## 探针错误与恢复

第一轮真实浏览器及 DeepSeek 审查均已通过。进入 finish 时，准备脚本误调用 `process_task(db, task)`；实际入口签名为 `process_task(db)`，异常发生在 Planner HTTP 发出之前。保留原脚本、原日志及 `attempt1-result.json`，没有将它归因产品、模型或 Provider。

修正后的 `finish-resume.py` 核对隔离库唯一可运行任务为 Task 1、原目标已闭合且测试／浏览器证据与当前版本匹配，通过实际启动门禁恢复同一个 URL。随后调用正常 `process_task(db)`，沿用已用一次的预算；没有重跑 Node、浏览器或目标审查，没有清零预算或手工写通过状态。

只读审计第一次误按 TAP 的 `# tests` 形式解析报告，实际 Node stdout 是 spec 的 `ℹ tests`。改为解析报告 JSON 中实际 stdout 后完成核对；没有重跑测试或增加调用。原报告与服务状态保持。

## 隔离与运行证据

目录：`/private/tmp/objective-review-continuation-20261002-L3L7mW`。

- `baseline.json`：源隔离产物、20 文件哈希、原目标和 32 条检查点哈希。
- `run.log`、`attempt1-result.json`：首轮原目标闭合及探针参数错误。
- `finish-resume.log`、`result.json`：累计三次请求、实际 inspect／finish 与待验收结果。
- `sent-requests/001.json` 至 `003.json`：实际请求正文，不含认证头。
- `workspace/1/evidence/verification-report.md`：原 Node 与浏览器真实报告。
- `workspace/1/evidence/repair-objectives.json`：E4-1 closed、精确引用与验证哈希。
- `audit-summary.json`、`formal-after.json`：版本、服务、正式任务与 Trace 隔离核对。

源 20 文件、原目标账本及原 32 条协议检查点均未变；当前实例业务代码和测试未变，只有正常 Worker 更新了 product/README.md 的访问地址。正式 24 个任务状态／版本和 16,908 条 Trace 与基线相同，pending Event 和运行任务均为 0；Worker 2573 未重启，日志仍 0 字节。源实例仍保留原 open 状态，不把隔离成功写回正式任务。

当前保留服务：`http://127.0.0.1:61626`，PID 47204，以实际 service.json 及审计时进程状态为准。本地静态服务，不是生产部署；临时证据与服务不保证长期存在。

## 用户验收与限制

1. 打开当前地址，在素材库新增素材，选择已有记录编辑笔记并保存。
2. 在选题管理新增选题，选择已有记录修改内容角度和优先级，保存后记录数应不增加。
3. 刷新页面后，两类修改应保留。

完整软件需求的用户验收、Windows、同类任务稳定成功率及此前导航超时根因仍未完成。当前结论仅为这个已生成产物的原缺陷返修路径已走到待验收；不将多次人工恢复实验称为从零全程无人干预交付。历史失败见 [导航诊断](navigation-diagnosis-20261002.md) 与 [此前独立验收阻塞](objective-close-validation-blocked-20261002.md) 。
