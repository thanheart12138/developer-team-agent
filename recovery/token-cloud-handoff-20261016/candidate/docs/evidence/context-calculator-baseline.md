# 计算器 Context 回归基准

## 固定约定

使用 `tests/context_calculator_baseline.py` 内的原始需求作为固定输入，不随模型生成的软件修改期望。全程 DeepSeek，临时 SQLite／工作区，不操作正式任务。最多 30 次实际模型调用、两轮返修。审批由测试用户核对候选后执行；最终成功必须经过独立浏览器操作，模型自称完成不算成功。

这两个手动脚本放在已有 `tests/` 目录，文件名不以 `test_` 开头，普通 pytest 不会自动发起付费调用。仅在明确授权真实模型测试后运行。

## 运行方法

从仓库根目录运行：

```sh
PYTHONPATH="$PWD" .venv/bin/python tests/context_calculator_baseline.py --legacy
```

`--legacy` 在隔离进程内重建本次优化前 context：恢复重复正式需求、全部用户请求、无旧设计的全文差异，移除新增来源和快照标识。保留此前返修正确性修复，不回滚源码。省略此参数运行当前 context。

输出 ROOT 后，候选生成阶段暂停，测试用户必须读取 `workspace/1/docs/product-v1-candidate.md` 核对原始需求，确认后在 ROOT 下创建 `approve` 文件。未批准不得继续。不明确或有冲突时不创建批准标记，按实际情况记录失败或澄清。

自动链路到 waiting_acceptance 后，运行：

```sh
.venv/bin/python tests/context_calculator_acceptance.py <ROOT>
```

独立验收固定四则运算、两位小数、除零后恢复、小数点去重、禁止连续计算、等于前置条件、清空、键盘无效、长结果显示及页面错误。定位器用于操作页面，不是产品接口要求；生成 DOM 改变时只允许调整定位，不改变输入和期望。

## 每次记录

保存原始需求、候选审批意见、实际模型 ID、源码版本／工作区差异、模型调用和工具 Trace、预算、阶段路径、返修次数、Provider 实际 usage、独立验收和最终状态。临时目录保存原始数据，必要结果写入本目录的证据报告。

源码或模型更新可能改变结果。单次成功不代表通用能力；单次 Token 对比不能隔离随机生成内容和阶段选择的影响。后续应使用相同输入及预算重复运行，不能为了通过测试倒改需求。

出现需要测试用户回答的澄清时，脚本暂停，不猜测新决定。在临时库提交 user_message 后使用 `--resume <ROOT>` 恢复同一任务，并保留 `--legacy` 模式；恢复沿用已消耗预算。`sent-requests/` 保存测试覆盖后的实际请求体，普通 Worker 请求 Trace 在覆盖前记录，不应误用作 legacy 实际发送证据。

## 2026-09-17 首次旧 Context 重建样本

15 次 DeepSeek 调用，1 次架构澄清、0 轮返修，Planner 在澄清后跳过架构及 Dev Design。Node 30 项及独立 Chromium 22 项通过，测试用户验收后隔离任务 succeeded。输入 158,403／输出 15,317／总量 173,720 Token，全部来自实际 usage。

上一次当前 context 样本：14 次调用、1 轮返修，Node 35 项、独立 Chromium 22 项通过；输入 101,787／输出 25,461／总量 127,248 Token。旧重建样本总量高约 36.5％，但文档、阶段选择和缓存命中不同，不推断计费成本或因果节省。

首次运行封装的合成开发依据误用了字面 `\\n` 分隔符，而非真实换行；重复内容恢复及 metadata 移除确实在实际 Runtime 调用前执行，但不是逐字旧版请求。封装已修正并增加实际发送体保存。该次样本仅为可运行性证据，不作为严格去优化前后 A/B；预算内未再次执行完整真实链路，修正后封装尚未真实复跑。后续以固定需求、用例、预算及修正后的脚本为基准。

本次原始证据 ROOT：`/var/folders/h7/z81qmxk16ks2kn3jzr21_k7m0000gn/T/context-full-deepseek-o9t7eq8t`，其中包含临时数据库、工作区、summary.json、independent-acceptance.json、acceptance.png 和 final-status.json。首次运行没有覆盖后实际请求文件，不声称已保存；后续运行才保存 sent-requests。
