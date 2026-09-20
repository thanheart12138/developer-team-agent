# 素材管理事务式返修真实 DeepSeek 验证

日期：2026-09-20。结论：完整链路未通过；最初运行在第二张业务切片开发中失败，未进入集成返修，因此该轮没有实际触发事务式返修，不能据此判断其 Token 降幅。后续独立控制流切换的 materials 局部样本已通过，见文末；不覆盖以下历史失败。

## 运行范围

- 从空工作区运行 `tests/content_workbench_baseline.py`，全阶段使用真实 DeepSeek `deepseek-flash`。
- 固定素材管理需求与既有基准一致；测试控制核对产品候选后通过正式审批事件，没有修改生成代码。
- HTTP 上限 200，单 Step 逻辑调用上限 100。
- 有效证据目录：`/private/tmp/content-workbench-transactional-v1b-20260920`。
- 第一次入口 `/private/tmp/content-workbench-transactional-v1-20260920` 因工作树没有默认密钥文件而在请求前失败，实际 HTTP 为 0；修正为指向已有受控凭据文件后从新的空目录重跑，不计为模型能力结果。

## 结果与成本

最终状态为 `failed / develop / unit_development_no_progress`。共 35 次真实 HTTP，输入 582,267、输出 43,199、合计 625,466 Token，缓存命中 150,272 Token。

| 阶段 | HTTP | 输入 | 输出 | 合计 |
|---|---:|---:|---:|---:|
| 产品文档 | 4 | 12,930 | 5,787 | 18,717 |
| 架构与骨架 | 5 | 33,757 | 17,551 | 51,308 |
| 首张执行卡 | 1 | 13,432 | 838 | 14,270 |
| Develop | 25 | 522,148 | 19,023 | 541,171 |

Develop 内部：第一张 `storage-persistence` 切片 6 次／81,638 Token，下一张切片规划 2 次／41,386 Token，第二张 `topics-management` 切片 17 次／418,147 Token。Develop 占总量 86.52％，第二张切片单独占总量 66.85％。

## 实际进展与失败

第一张切片完成并由程序验证通过：storage 与 materials 共 13 项 Node 测试通过、0 todo。第二张卡把 topics、tasks、storage、materials 四个模块及四个测试文件放入同一切片。模型实现后运行局部测试，发现 `tasks.test.js` 的 `getSourceTopic 经注入回调实时查询` 失败。

失败断言先调用 `wire()` 把 `tasks.getTopicById` 绑定为 `topics.getTopic`，随后只修改 `topics` 模块自己的注入回调，却期望 `tasks.getSourceTopic` 返回 `undefined`。当前实际返回原选题对象。无论最终应修测试还是调整注入契约，模型已经定位到同一失败片段，但此后连续多次重复读取 `tasks.test.js` 的相同行区间，没有写入，最终触发无进展门禁。

独立执行当前全部 Node 测试得到 47 项：35 通过、1 失败、11 todo。任务尚未进入全量测试、HTTP 启动或 Chromium 验证。

## 对本轮优化的判断

本轮新实现的失败证据版本化、返修上下文瘦身和“两次调用／一份失败证据、整个返修最多四次”的事务式返修只作用于全量测试或浏览器验证后的集成返修。本次在正常业务切片开发阶段提前失败，相关机制没有被调用。

本轮暴露的下一个成本问题是：业务切片开发在取得明确自测失败后，仍允许使用普通无进展额度重复读取相同文件；并且第二张卡同时拥有四个模块，输入上下文从约 14K 增长到约 30K Token。后续修复应针对切片开发的“自测失败事务”：绑定失败断言和责任文件，限制重复读取，并要求下一次有效动作是局部修改或结构化重规划。

## 针对本次失败的修复

`slice-developer` 升至 v7，明确区分“修正没有表达 acceptance 的测试实现”和“降低测试”：允许修正错误回调对象、夹具、数量计算和环境假设，但必须保持业务语义及覆盖强度。模型定位责任文件和错误位置后必须立即修改，不能继续读取哈希未变的重叠区域。

Runtime 同步增加自测失败后的语义读取门禁。程序记录失败后已成功读取的文件与行区间；后续读取同一文件的重叠区间，即使改变行号范围或 description，也返回 `self_test_repeated_read_requires_change`。读取尚未覆盖的必要依赖仍允许；成功 `write`／`replace` 后门禁解除并要求重新自测。完整 215 项回归通过。尚未再次付费续跑，因此只证明机制阻断本次同型循环，不证明真实模型已经完成素材管理。

## v6／v7 两次低成本决策对比

使用同一真实失败片段、测试装配和已知实现，各发送一次无工具 DeepSeek 请求，只要求结构化判断责任与下一步。v6 与 v7 均返回 `responsibility=test`、`next_action=modify_test`，均提出把 `topics.configureInjectedCallbacks` 改为 `tasks.configureInjectedCallbacks`，并声明 acceptance 保持、覆盖没有降低。

v6 输入 1,009、输出 628、合计 1,637 Token；v7 输入 1,144、输出 455、合计 1,599 Token；两次总计 3,236 Token。原始结果位于 `/private/tmp/slice-prompt-v6-v7-comparison-20260920`。

该结果证明两个版本在根因、相关代码和“无需再次读取”都明确给出时，都会口头选择修改测试；它不能证明 v6 在真实工具循环中会实际修改，也不能证明 v7 单靠提示词优于 v6。v7 的新增价值仍主要来自更明确的授权，加上 Runtime 对重叠读取的确定性门禁。后续提示词版本比较应使用信息不完全但足够决策的失败回放，或只允许局部工具的行为测试，而不是再次运行完整全链路。

## v6／v7 局部工具行为对比

使用三个最小产品文件和同一真实失败语义，v6、v7 各运行一次，开放 `read`、`replace`、`run_unit_tests`，每个版本最多 6 次模型调用。两者都实际把错误的 `topics.configureInjectedCallbacks` 替换为 `tasks.configureInjectedCallbacks`；独立 Node 复测均为 1 项通过。

v6 在第 4 次模型调用才执行 `replace`，此前进行了 6 个读取动作；v7 在第 2 次调用执行 `replace`，此前只有 2 个读取动作。v6 消耗 24,475 Token，v7 消耗 26,887 Token。v7 行为更快进入修改，但这一次总 Token 没有更低。

两个版本修改后都没有调用 `run_unit_tests`，而是继续读取文件，最终都以 6 次局部预算耗尽结束；流程状态没有因独立 Node 通过而自动成功。本夹具把初始失败作为 `unit_test_feedback` 注入，没有先在同一工具历史中调用 `run_unit_tests`，因此“失败后重叠读取”门禁没有触发。这揭示两个剩余缺口：恢复或外部提供的版本一致失败证据也要进入受限修复状态；成功修改后，下一步应强制复测，不能重新开放诊断读取。原始结果位于 `/private/tmp/slice-prompt-tool-comparison-20260920`。

上述两个缺口随后已修复。Runtime 现在同时识别同一历史中的失败自测和 `unit_test_feedback.passed=false`；失败修复产生成功 `write`／`replace` 后，下一模型批次除 `run_unit_tests` 外的动作统一返回 `unit_change_requires_self_test`。同一模型批次仍可完成同一根因的多个相关修改；复测失败后重新开放必要诊断，复测通过后沿用原提交门禁。完整 217 项回归、Python 编译和差异检查通过；尚未再次发起真实模型局部对比。

修复后使用同一三文件夹具再次执行 v6／v7 局部工具对比。两版都完成正确替换、主动调用 `run_unit_tests`，模型循环返回成功，Node 1 项通过。v6 用 5 次模型调用、21,511 Token；修改后仍尝试重新读取，4 个读取动作被 `unit_change_requires_self_test` 阻止，随后才复测。v7 用 4 次模型调用、17,495 Token；修改后的下一批直接复测，没有触发门禁。与修复前相比，两版均从“6 次预算耗尽”变为成功；本次 v7 比 v6 少 1 次调用和 4,016 Token。原始结果位于 `/private/tmp/slice-prompt-tool-comparison-retest-20260920`。

## 第二张切片膨胀修复

本次运行的第二张卡把已经通过的 storage／materials 与新增 topics／tasks 一起列为 owners，造成四个模块和四个测试文件同时进入 Developer 上下文。其根因不是业务必须一次重做四个模块，而是 Planner 把“调用已交付接口”错误表达为“重新拥有并实现依赖模块”，Runtime 又没有拒绝这种卡片。

`slice-planner` 已升至 v5。已通过模块现在默认只作为 `required_interfaces` 的只读依赖，不再重复进入 owners、implementation_files 和 test_files。只有当前 acceptance 明确要求改变既有行为时，Planner 才能声明 `rework_delivered_modules`，并为每个模块提供 `rework_reasons`；Runtime 会拒绝没有该声明的重复模块和不完整的返工声明。

Developer 首次上下文只预载当前卡拥有的实现及测试文件，不再预载工作区全部产品源码；已交付依赖仍保留只读按需访问能力。程序自测继续执行当前卡测试和全部先前已通过测试，因此缩小模型上下文不会削弱回归门禁。Planner 收到的 passed_slices 和最近测试结果也改为结构化摘要，不携带历史测试的完整输出。

局部 7 项及完整 218 项回归通过，覆盖：重复已通过模块被拒绝、显式返工可通过、组合接口依赖解析、Developer 预载范围、Planner 历史摘要和提示词注册。尚未运行新的真实 DeepSeek 全链路，所以当前只证明流程机制已收紧，不能声称第二张卡一定缩为 topics／tasks，也不能声明实际 Token 降幅。

## Planner v4／v5 两类真实对比

按提示词升级验证流程执行两类真实 DeepSeek 对比。每个样本只调用一次 Planner，不开放工具，不运行完整产品链路；新旧版本使用相同输入和模型。为还原真实故障链，历史回放又分为首次规划请求和首次卡片被校验拒绝后的重试请求。共 6 次 HTTP，输入 79,315、输出 5,551、合计 84,866 Token。

| 场景 | 版本 | owners | 是否重复已交付模块 | Runtime 校验 | Token |
|---|---|---|---|---|---:|
| 最小构造故障 | v4 | topics、materials | 是，materials | 未使用真实骨架执行 | 1,465 |
| 最小构造故障 | v5 | topics | 否 | 未使用真实骨架执行 | 1,466 |
| 真实首次规划回放 | v4 | topics | 否 | 通过 | 20,345 |
| 真实首次规划回放 | v5 | topics | 否 | 通过 | 20,500 |
| 真实校验反馈后重试 | v4 | topics | 否 | `slice_required_interfaces_mismatch` | 20,479 |
| 真实校验反馈后重试 | v5 | topics | 否 | 通过 | 20,611 |

最小构造故障直接验证了提示词差异：v4 为调用 `getMaterial(id)` 把已交付 materials 再次列入 owners 和 implementation_files；v5 保持 materials 为只读接口依赖，只拥有 topics。两版单次 Token 几乎相同，因此该样本证明的是卡片边界改善，不支持提示词本身降低单次 Planner Token。

真实首次规划回放中，两版这次都返回可执行的最小 topics 卡，说明 v4 的膨胀行为不是同一输入下的确定结果，单次采样不能证明 v5 全面优于 v4。历史 Trace 114 显示当时 v4 的首次 topics 卡随后进入校验反馈；Trace 116 才生成 owners 为 storage、materials、topics、tasks 的四模块卡。

复用实际第二次重试请求后，v4 本次没有重现四模块膨胀，但其卡片无法通过当前接口覆盖校验，还会继续消耗下一次 Planner 调用；v5 返回可直接通过校验的 topics 单模块卡。结合构造样本，当前证据支持的结论是：v5 能在依赖存在和校验反馈后保持已交付模块只读，并提高一次生成可执行最小卡的稳定性。由于每个条件只有一个新样本，尚不能给出稳定成功率，也不能把 84,866 Token 视为全链路节省。

原始结果与审计汇总位于 `/private/tmp/slice-planner-v4-v5-comparison-20260920`。其中 `constructed-*.json`、`real-replay-*.json`、`real-retry-replay-*.json` 保存完整模型文本和 usage，`audited-summary.json` 保存范围及 Runtime 校验结论；不包含凭据。

## 修复后完整链路验证

从空工作区启动真实 DeepSeek 素材管理全流程。第一个入口样本在第一张 storage 卡开发时，模型正确生成实现和测试，但把文件工具参数写成查询工具使用的 `file_path`；Runtime 只接受 `path`，两次写入失败后无进展停止。该样本 20 次 HTTP，输入 115,599、输出 31,957、合计 147,556 Token。Runtime 随后增加无冲突参数归一，写入仍经过原有路径和所有权校验。

第二个主任务在骨架阶段首次 13 次调用失败。模型把 27 个文件逐步压到 21 个，通用反馈没有告诉它具体合并目标，之后又丢失模块接口及 `product/` 路径前缀。纠正反馈改为携带上一候选的模块／路径轮廓，精确列出多实现文件合并目标、缺失字段和路径前缀；不重复文件全文。任务恢复后骨架通过。

Develop 前两张卡成功：`core-storage-relations` 独立 9 项 Node 测试通过；`core-taskview-search-validate` 与前片累计 18 项通过。第三张 `materials-library` 最初把两个已通过模块继续列入 owners，但只包含 materials 文件，绕过了原先只检查重复文件的门禁。Runtime 现同时拒绝重复 owner，恢复时重新校验旧待开发卡并自动重规划；重规划后的卡片只拥有 materials。

第三张卡最终仍因无进展失败。Developer 起初按架构概念读取不存在的 `search.js` 和 `validate.js`；补充已通过切片的接口—实现文件映射后，它正确识别 Search／Validate 位于 `task-view.js`，并成功读取 `task-view.js`、`storage.js`、materials 实现与测试，但随后继续重复读取，没有执行写入，最终触发 `unit_development_no_progress`。因此当前剩余问题是普通开发状态下“依赖已经读齐后仍不进入修改”的空转，不是重复已交付模块或测试失败后的重复读取。

主任务累计 62 次 HTTP，输入 598,104、输出 118,417、合计 716,521 Token：产品文档 16,791，架构与骨架 262,468，Dev Design 43,553，Develop 393,709。最终未进入全量 Node、HTTP 启动、Playwright 或人工验收，不能声明素材管理交付成功。完整 219 项项目机制回归通过。主证据目录为 `/private/tmp/content-workbench-full-v5b-20260920`，阶段审计为其中 `audited-usage.json`；入口故障样本位于 `/private/tmp/content-workbench-full-v5-20260920`。

## 普通开发重复读取的逐批复核与修复

对 `materials-library` 最后 8 个模型批次逐项复核后，确认此前“依赖证据已经齐全”的表述过强。程序当时没有判断依赖是否齐全；能够确认的是模型已经定位并成功读取主要依赖，随后仍重复读取未修改文件。

- materials 实现和测试分别成功读取 3 次，后两次没有新增行。
- `storage.js` 首次读取 1—200 行并随后读取 200—207 行；后续又读取 1—120、1—200 和 195—207，均已被前两次结果完整覆盖。
- `task-view.js` 首次完整读取后又完整读取一次。
- 后期唯一新增证据是 `core-relations.test.js`；模型没有写入或运行测试。

Runtime 因此新增普通单元开发读取门禁。门禁使用工具实际返回的行区间合并覆盖范围；同一历史、同一未修改文件的下一次请求只有在请求区间已被完整覆盖时才返回 `unchanged_file_read_already_covered`。读取尚未覆盖的尾部或间隙仍允许；同一文件成功 `write`／`replace` 后清空旧覆盖证据，允许读取新版本。自测失败后的重叠读取和修改后强制复测仍保持更严格且优先的错误语义。

该修复针对已经证实的重复读取，不判断“业务依赖是否齐全”，也不强迫第一次读取后立即修改。局部 4 项回归覆盖：失败后重叠读取、普通开发全文重复、未覆盖尾部、连续区间合并以及文件修改后重读；完整 222 项回归通过。尚未再次发起真实 DeepSeek 全流程，不能声称该门禁已让素材管理成功或量化 Token 降幅。

## 普通开发读取门禁的局部 DeepSeek 验证

复用主任务在两张基础切片通过后的真实工作区、`materials-library` 卡片、正式 v7 Developer 提示和相同只读依赖范围，只运行当前切片 Developer；不运行产品、架构、Dev Design 或后续切片。模型调用上限为 10。第一次测试入口因 `/private/tmp` 脚本未加入项目导入路径，在发出模型请求前失败，调用数与 Token 均为 0；修正后使用新的隔离目录重新执行。

局部流程未通过。DeepSeek 实际调用 8 次，输入 73,440、输出 1,306、合计 74,746 Token，缓存命中输入 43,648 Token；最终仍为 `unit_development_no_progress`，没有写入、没有调用 `run_unit_tests`、没有提交或请求重规划。Runtime 共拦截 10 个 `unchanged_file_read_already_covered` 动作。模型在第 5 次响应已经明确指出 Search／Validate 实际位于 `task-view.js`，但后续三批仍请求已成功读取的 storage、task-view 或 materials 文件。

独立运行当前卡及前置切片测试得到 26 项：18 pass、8 todo、0 fail。todo 均属于未实现的 materials 测试，因此不能视为当前卡通过。

结论是本次门禁只实现了重复读取止损，没有让模型从“再次确认依赖”切换到写入。下一处需要修复的不是继续扩大读取判断，而是门禁失败反馈和后续动作约束：当普通开发读取被判定为完整重复后，下一批必须在写入当前拥有文件、执行已有自测或结构化重规划中选择，不能继续发起已知依赖读取。原始隔离证据位于 `/private/tmp/materials-repeat-read-local-v2-20260920`。

## 重复读取后的推进约束及局部复测

Runtime 随后增加两层约束：首次完整重复读取被拒绝后，后续批次只允许 `write`、`run_unit_tests` 或 `request_slice_replan`，直到其中一个动作成功；普通单元开发中的跨批成功写入也必须立即 `run_unit_tests`。工具错误的优先级经真实复测纠正为推进约束优先，下一次请求还会收到独立 `unit_progress_feedback`，明确说明现有读取证据仍有效和三个合法动作。

机制测试证明这些状态转换按规则执行，完整 224 项回归通过。但四次后续真实局部复测仍没有完成切片：

| 样本 | 调用 | Token | 实际结果 |
|---|---:|---:|---|
| progress-v3 | 10 | 101,816 | 推进约束首次使模型在第 8 次写入 materials 实现，但代码引用不存在的 `search.js`／`validate.js`；随后继续读，未测试或提交 |
| retest-v4 | 8 | 71,813 | 暴露错误优先级问题，模型仍只看到旧的覆盖错误；无写入 |
| retest-v5 | 8 | 73,859 | 修正优先级后持续返回推进约束，模型仍继续 read；无写入 |
| feedback-v6 | 8 | 74,601 | 下一请求显式携带推进指令后仍连续 13 次请求 read；无写入 |

加上第一次门禁局部测试，五个有效样本共 42 次真实调用、396,835 Token，均未通过。每次独立 Node 验证仍为前置 18 pass、materials 8 todo、0 fail。首个脚本导入错误发生在 HTTP 前，不计调用或 Token。

因此当前证据不支持继续用同类提示或 ToolResult 反馈重试。约束可以拒绝非法动作并节省工具读取输出，却无法稳定改变 DeepSeek 的下一步选择；继续把相同输入重新发给模型仍会消耗完整输入 Token。后续方案需要改变控制流，例如在依赖文件和接口映射已经由 Runtime 确定后直接构造实现任务，或在模型连续违反一次推进约束后立即结束当前 Developer 并进入独立的受限实现调用，而不是继续同一对话循环。本轮按上限停止，不再追加付费样本。原始证据分别位于 `/private/tmp/materials-repeat-read-progress-v3-20260920`、`/private/tmp/materials-repeat-read-retest-v4-20260920`、`/private/tmp/materials-repeat-read-retest-v5-20260920` 和 `/private/tmp/materials-repeat-read-feedback-v6-20260920`。


## 用户确认后的控制流切换与唯一局部样本

后续经用户确认，Runtime 在首次违反推进约束后结束旧 Developer 对话，使用已校验接口映射、owned_files 和当前只读依赖快照启动独立受限实现。模型只写入或重规划，写入后 Runtime 直接自测、通过后提交并独立回归；状态及最多四次实现／修复额度跨恢复保留，不再继续旧历史。

完整 241 项回归通过。真实 materials 局部样本旧对话五次有效响应后触发切换，独立实现两次调用补齐实现和八项真实测试；Runtime 自测、提交与独立 Node 均为 26 pass、0 todo。七次有效响应共 76,859 Token；沙箱内另三次 ConnectError 保留在同一样本，总请求计数 10／12。未修改只读依赖、未人工补生成代码、未追加付费样本。

五组独立 Node 验收和浏览器模块错误恢复／搜索／刷新持久化通过；真实整页保存仍因未实现 UI 的错误依赖路径而失败。仅能确认局部控制流与材料模块实现通过，不能宣称完整产品交付、稳定成功率或 Token 降幅。具体请求、审批阻塞与恢复、成本和失败结果见 [独立实现验证](materials-control-switch-validation.md) 。
