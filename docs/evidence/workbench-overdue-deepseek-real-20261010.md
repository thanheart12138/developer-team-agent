# 005 工作台逾期新场景真实返修

## 结果

用户明确授权新隔离外发及最多20次实际HTTP后，DeepSeek thinking完成返修到awaiting_acceptance：11／20HTTP，262,827Token，54秒，无人工改码／纠错。原固定Node150／150及实际Chromium60条独立通过；没有模型审查，原目标台账仍open，用户批准事件未发送。新场景报告完成，不宣称整个平台绝对无缺陷。

## 输入、执行与效果

此前零模型预检已复现：逾期从全部records而非unfinished计算，导致已发布任务仍在逾期列表。批准产品规定逾期仅未完成且截止日期早于本地当天，无日期／当天／已发布均不计入。原W2断言和浏览器工作台操作保持，不由模型改测试自证。

授权后复核故障／基准及运行机制hash，与预检相同；在已有持久目录material-workbench-overdue-20261010建立独立库及20HTTP预算，不重置旧计数。第1—5轮搜索／读取，第6轮replace修改工作台，第7轮继续读取，第8轮自测通过，第9—10轮继续搜索／读取，第11轮计划与显式提交同批。搜索实际使用path=product并续查cursor50／version，成功无参数错误；通过后仍3轮，收尾行为未解决。

唯一修改dashboard/dashboard.js：在isOverdue中先判断任务状态是否未完成，添加中文说明及isUnfinished辅助函数。没有直接把records.filter改回unfinished.filter，但效果符合需求；未人工精简模型实现，未以修改形式判失败。既有任务状态／日期变化会按当前集合重算，未引入缓存或数据写入。

程序固定测试→启动→浏览器通过，随后另复制产品并恢复基准原test.js／verify_product.py独立复测，Node150项、浏览器60条通过，问题列表为空。生成Python／Node只在Docker执行。已发布不再计入逾期、状态回退与日期边界、任务总数／其它计数／编辑、刷新及原素材选题业务由原断言验证。网站 [本轮素材平台](http://127.0.0.1:54472/) GET200，首页字节匹配，不把首页检查单独当交互成功。

## 成本与留存

| 指标 | 实际 |
|---|---:|
| 执行／审查HTTP | 11／0 |
| 输入／输出Token | 256,976／5,851 |
| 总Token | 262,827 |
| 缓存命中／未命中 | 33,280／223,696 |
| 自测 | 1次 |
| 最后通过到提交 | 3轮 |
| 总控制耗时 | 54秒 |

11次全部有响应，thinking开启、工具协议完整，无失败工具。剩余9次未使用，不追加调用。旧九份runtime／预算指纹与源绿色文件保持，原220计数仍独立保存，机制hash实验中不变，正式服务未操作。十轮新实验累计137HTTP／3,878,125Token；本例与素材关联案例任务不同，不据此计算优化百分比或稳定成功率。

证据位于 `workspace/experiments/material-workbench-overdue-20261010/`：external-approval.json、prepare.json、preflight.json、run.log、result.json、summary.json、effect-check.json、preview-check.json、implementation-hashes.json、prior-state.json及task/原Trace／思考／检查点／累计预算、independent/原断言输出。文档整理零新增调用，未提交推送、部署、迁移数据库或批准验收。
