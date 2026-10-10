# 001：产物与证据备份准备及恢复验证

当前状态：用户于2026-10-10决定「不用，一份就行」，取消异地副本要求；001按更新后的条件完成，继续002。下文异地待确认措辞为此前历史，本机归档与验证证据不变。零模型调用，无任务恢复或验收批准事件。

后续交付审计：嵌套源码268文件、产品22文件完整，敏感目录不在包中；7份历史文档包含本机用户名／临时路径。另建delivery-redacted.tar.gz，仅替换这些文档路径，未改代码及产品，原两个归档hash保持。脱敏包SHA256为72465d42cacd07aad043674b64050107de40ca123dfe0d7bc28420150b5cf3ce。delivery-review.json与delivery-redaction-check.json记录具体文件和复核；后续对外保存优先使用这个交付候选，不把原delivery.tar.gz称作完整脱敏包。仍没有实际异地副本，不自动外发私有现场。

核对九轮真实隔离实验：均awaiting_acceptance，summary与runtime累计计数匹配，合计126HTTP；9份SQLite只读integrity_check通过，任务非pending／running；产品、Trace和检查点存在。保留旧220为独立历史计数，本次未触碰其预算。原文件打包前后及恢复测试后指纹保持。

包保存在 `workspace/experiments/artifact-backup-20261010/`：

| 归档 | 用途 | 大小约 | SHA256 |
|---|---|---:|---|
| delivery.tar.gz | 源码／冻结产品交付候选，无实验SQLite／Trace | 1MB | 6127aa12b83ad17d0a06d1cbab059c520e1409e6274bb8b8c2ded360eeab073d |
| private-experiments.tar.gz | 私有九轮原实验现场 | 14MB | 4ade5423a7f901473633bdf097834faf32b67d99a43d5bb1d2603324ff065156 |

实验原现场3,063文件全部从包恢复到新隔离目录，逐项SHA256匹配，9库恢复后仍完整、累计126保持。再对恢复的最新素材平台independent/product执行受控Docker验证：Node exit0（150项），实际浏览器60条通过、问题列表为空。证明冻结产品及只读现场可恢复，不证明旧绝对路径已迁移或自动续跑安全。

凭据特征扫描无命中，排除凭据、环境、缓存和链接；扫描不能证明完全没有敏感数据。私有包保留原业务输入、完整模型思考、本机路径及历史状态，仅能存入用户控制的私有位置，不公开。源码交付候选包含已有项目说明，不能未经目的地确认就当作公开发布材料。

原清单与详细结果：inventory.json、manifest.json、restore-check.json、browser-check.json。prepare.py仅准备新现场，不覆盖已有manifest；RESTORE.md写明完整性检查、只读SQLite及不能直接运行原控制脚本的限制。异地备份问题已提交用户，等待保存位置和包类型；当前offsite_saved=false，不称已有异地副本，不自动上传或推送归档。
