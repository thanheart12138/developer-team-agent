# 005 工作台逾期场景预检与调用准备

当前状态：零模型准备完成，真实外发／最多20次HTTP授权待回复，未创建任务SQLite或运行真实返修。此记录不是模型完成证据。

## 场景与预期

沿用既有批准素材平台文档，product.md1.2定义逾期为未完成且截止日期早于本地当天；已发布、无截止日期和当天到期均不计入。任务改已发布后应从逾期移除，回退为未完成时按当前状态重算；各状态计数、总数、详情编辑和其它业务保持。

绿色基准来自material-task-detail-scoped-search-20261010/baseline。新副本只将dashboard/dashboard.js的逾期计算来源从unfinished.filter替换为records.filter，故意误算已发布任务。原150项Node和60条实际浏览器断言不修改，原W2已有「无截止日期与已发布不计入逾期」用例，不由故障实现倒推新需求。

## 实际预检

真实Docker绿色Node／浏览器exit0，故障两项exit1。浏览器复现逾期计数应0实际1、逾期列表出现已发布任务、已发布任务未被移除；原测试能识别这一行为。原九轮runtime指纹核对保持，生成Python／Node只在Docker执行，未修改源基准或原预算。

## 可批准的真实测试范围

提议DeepSeek thinking最多20次实际HTTP含失败重试，无审查预留。外发仅新隔离平台代码、既有批准文档、合成缺陷及固定测试；密钥只认证。独立库及预算获授权后才建立，不沿用旧剩余额度；模型自主调查／修改／自测／提交，开发助手不人工修生成代码或提示收尾，程序独立复测原断言和网页。完整结果分别回答机制、模型完成和软件要求，不因测试状态成功自动批准业务。

持久目录 `workspace/experiments/material-workbench-overdue-20261010/` 已保存README结构约定、baseline、task、prepare.json、prior-state.json、preflight.json/log、run.py、summarize.py、audit.py及机制指纹。没有external-approval.json，执行入口实际返回external_model_authorization_pending，检查后无test.sqlite、无Trace请求、无runtime预算文件；未发送HTTP。该预期拒绝证明入口等待授权，不能把它写成真实模型测试失败。

收到明确授权后继续同一现场，不重新注入／重置或自动扩大预算。本次执行准备没有正式服务重启、数据库schema／密钥修改、提交推送或付费调用。
