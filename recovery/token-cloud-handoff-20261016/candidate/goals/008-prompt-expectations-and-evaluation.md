# 008：提示词预期、反例与可运行评测器

状态：已实现并验证，待用户验收。86模板261案例职责预期及正反离线证据身份审计通过；260合成参考与1真实回放区分，不宣称真实模型效果全部认证。

## 目标与可运行结果

每个提示词有明确输入、预期输出／行为、禁止行为与反例。交付可运行的本地评测入口，读取案例和捕获响应／工具轨迹，输出逐项判定报告。首版支持离线证据，真实模型执行另行批准。

## 范围与步骤

1. 先确认案例结构、判定器和重要／普通／轻度含义，更新有效设计并约定新增目录。
2. 建议按错误后果分级，等级与正常／边界／反例独立；不改变线上模型路由或预算。
3. 覆盖全部提示词的适用输入；每类至少有正常、边界和反例，确实不适用须说明依据。多轮及工具提示词使用必要轨迹，不只检查最终文本。
4. 实现受控格式、字段、参数和轨迹检查。语义不能可靠自动判定时输出待人工判断，禁止默认成功。
5. 用明确正确与错误的响应／轨迹运行评测，证实能通过正确行为并检出错误。

## 完成条件与验证

- 可通过实际命令运行一组案例，报告案例ID、模板版本、输入身份、判定依据和失败原因。
- 越权、过期绿灯、缺必要信息、错误参数和无显式提交等反例被正确识别。
- 已确认：重要或普通案例失败、未执行、待人工判定均阻止启用；轻度失败提示，不能掩盖关键失败。
- 离线回放、Fake／Mock、真实模型结果分别标记；未执行为未执行，人工判断缺失为待判断。

## 边界与证据

不执行任意用户断言脚本，不修改受保护的原回归依据。外发范围、模型和HTTP上限另批；运行数据持久留存且不含凭据。交付入口命令、样例报告、案例依据与验证记录，更新ROADMAP。

## 2026-10-10 执行证据

见 [提示词平台与有限真实基线](../docs/evidence/prompt-platform-real-baseline-20261010.md) 。实际命令与权限边界以证据为准；历史目标正文保留，不代表此前已实现。

## 后续：58组件组合预期与最终离线核对

58公共／反馈组件新增174个职责场景，标明真实消费角色、父角色变量和声明工具；片段与消费角色组合评测，父角色版本改变使批准输入与报告失效。连同28任务角色87案例，现86项261案例。参考响应明确标为检查器格式夹具，尚未人工认证完整业务语义；不将夹具通过解释为真实模型全部正确。

新增骨架与切片结构检查复用现有解析器，重复文件所有权、缺少验收映射等错误不能被人工通过覆盖；不执行生成代码。all-case-final-audit.json核对全部86项未判语义时关键案例阻止激活，58组件结构夹具通过。35项相关回归、前端build、86项注册审计与git diff --check通过；未重跑最新全量，历史452项不作为本次全量结果。父角色组合提示与格式夹具警示已实现，最新页面视觉检查未执行。

正式空闲服务身份核验后已加载API48864／Worker48865，health通过，正式数据、schema、文件状态、产品哈希及旧实验计数五项保持。证据位于workspace/experiments/formal-service-recovery-20261003-4caius6l/repair-v1-reload-result-20261010-component-cases.json。本轮新增模型HTTP0；原真实批次19HTTP／426,372Token保持。008语义评审仍待完成，011新入口实际模型成功路径与其余真实覆盖未验证，012候选和新预算未获确认，整体goal不标完成。

## 后续：产品与设计角色31组语义正反例

实际逐例读取10个角色输入、预期及参考响应后，发现design-final-author（label=架构）的参考正文是产品简介，缺架构职责与数据流。现正常／反例明确候选中的materials／storage／view职责、保存与初始化数据流、空标题／存储失败策略；只在指定版本文件生成正式架构，边界例改为目标已存在时安全停止。同步生成脚本；未改变用户产品规则或模型提示词正文。

product-design-semantic-pairs.json保存10角色31组正确参考响应与越权／反转需求错误响应及离线人工判断理由。31正确合成响应经过结构检查及逐例语义核对passed，31错误响应failed；语义判断由本开发助手明确给出，不冒充检查器自动识别所有业务错误，也不作为用户验收。来源offline_manual_review_of_synthetic_responses，真实模型／工具执行均false。相关53项回归通过，新增模型HTTP0，不生成正式通过报告或激活版本。

这是008的局部正负语义证据，剩余18任务角色及58组件仍待同等范围核对；不以本轮31例声明全部261例已认证。011剩余真实覆盖、012候选及新预算继续待确认。

## 后续：行为与规划角色27组语义正反例

实际核对行为提取／局部修正／覆盖／审查、验收行动规划、bug规划、集成诊断及单元规划9角色27案例。发现unit-planner的编辑feature复用新增验收，app也仅覆盖新增；已改为编辑结果、无效编辑保持原素材及修正后编辑恢复，页面覆盖新增与编辑。生成脚本同步，不改正式产品或模型提示词。三规划参考JSON通过真实ordered_units结构门禁。

behavior-planning-semantic-pairs.json保存27组参考与越权改需求／伪finish反例、逐例人工理由及判定；正确合成响应passed、错误响应failed。来源offline_manual_review_of_synthetic_responses，不冒充语义全自动、真实模型、实际工具执行或用户验收。累计19任务角色58案例有此类局部证据，其余9任务角色与58组件仍待核对，008不标完成。

新增模型HTTP0，git diff --check通过；只改案例与文档，无服务代码改动，不需要重启。011剩余真实覆盖和012候选／新预算仍待明确确认。

## 后续：设计与结构角色15组语义正反例

补architecture-scaffolder、design-author、design-reviewer、execution-base、repair-objective-reviewer五角色15组离线合成正反响应人工核对，证据design-structure-semantic-pairs.json。发现design-author参考正文为产品简介，已补素材create／edit接口、数据归属、持久化／初始化流程、失败保持旧列表及重试验收，引用输入中已确认storage依赖，不重定义依赖。目标已存在示例安全停止；旧生成脚本尊重已审阅标记，不恢复通用夹具。

参考正确合成响应passed、越权改需求及空泛完成反例failed，判断包括明确人工项，不冒充自动语义识别、真实模型或实际工具执行。累计24任务角色73案例完成此层次核对；剩余repair-executor、unit-developer、slice-developer、slice-planner四角色14案例及58组件尚未完成完整正负语义证据。开发角色的空replace参数只有顺序意义，没有替换正文及真实自测／网页证据，不能人工刷成完整修复通过。

全种子案例门禁与58组件实际payload两项专项验证通过，git diff --check通过；仅案例／证据变更，无服务代码修改，HTTP0。整体007—012目标保持进行中；011剩余真实覆盖与012候选／新预算仍待批准。

## 后续：已有真实返修轨迹只读重判

运行 `PYTHONPATH=. .venv/bin/python workspace/experiments/prompt-platform-20261010/replay_known_cause.py`，复用原已授权normal现场，不新建数据库、不重启产品或模型调用。核对批准30HTTP、原normal17HTTP、零人工介入、原独立Node／浏览器exit0、自测passed、22个测试后产品哈希匹配提交manifest与现存代码、启动／网页验证passed；输入与原证据hash重判前后保持。

保留23条完整工具动作及结果，包括前期失败／后期调查，不抽取成功片段；当前repair-executor known-cause按原批准逾期行为重新评测passed，人工结论属于开发助手复核，不是用户验收。known-cause-replay.json标为real_model_trace_replay，只有该例，不用于全模板激活；未重放或替换原模型输入。另将删除显式提交动作的副本作为synthetic_mutation_of_real_trace反例，自动失败即使人工true也不能覆盖，不冒充真实模型失败。

该证据补齐一个真实完整案例的轨迹／版本／独立验证关联；其余13个任务案例及174组件案例的完整语义证据仍不足，011新真实入口成功路径／其余覆盖及012候选／新预算仍待确认。新增模型HTTP0，原19／426,372保持，git diff --check通过。

## 后续：14骨架反馈组件42案例与实际导入

逐项打开scaffold-workflow-feedback-1至14原模板，核对固定交付文件、规范路径、声明匹配、唯一所有权、模块id／文件上限及延迟初始化要求；对应42正常／边界／反例的完整参考骨架一致，人工语义与真实_parse_scaffold结构门禁passed。重复文件所有权的合成错误响应在42例均failed，即使人工true仍不能覆盖。所有权反证不是每种业务错误的全自动识别，不推断模型成功率。

执行 `PYTHONPATH=. .venv/bin/python workspace/experiments/prompt-platform-20261010/scaffold_semantic_review.py`，新持久scaffold-import-fixture先写目录约定，8个参考文件加独立verification.test.js在已有Docker sandbox仅执行一次Node测试；真实导入materials／app并断言三个公开方法仍抛NotImplemented。exit0，tests4／pass1／fail0／todo3。诊断文件属于验证夹具，不写正式产品或参考模板；保留todo明确业务未实现，不将骨架导入解释为网站交付。

scaffold-component-semantic-pairs.json保存逐例casehash、正反判定及真实Node输出。新增模型HTTP0，未改变正式服务、旧实验、批准预算或提示词正文。008剩余44组件132案例、4任务角色中13尚缺完整证据的案例继续推进；011剩余真实覆盖／新入口及012候选／预算仍待确认。

## 后续：切片反馈的具体场景纠正

逐项打开切片反馈1—8后发现2／3／5／7仍复用新增A1卡：返修目标A2未描述，空coverage_summary场景无覆盖报告，缺固定入口场景不补入口，未实现依赖场景却继承「storage已通过」。已修12案例输入与参考输出：2明确当前编辑返修目标及app实现／原测试；3给定全部真实覆盖的合成输入后返回complete及非空来源摘要；5返回app-delivery并纳入index.html／verify_product.py；7明确storage未交付并纳入全部实现／测试和owner。原三级与正常／边界／反例分类保留，不改批准需求。

各例新增针对性自动字段检查与人工业务判断；将正确响应分别删编辑ID、覆盖摘要、验证入口、依赖测试的12个合成反例均failed，即使人工true也不能覆盖。正确合成参考经结构＋明确人工复核passed，coverage_summary还通过实际完成摘要校验。slice-feedback-semantic-pairs.json保留输入hash与正负判定；旧组件生成脚本保留已审阅案例，避免重生成恢复通用夹具。

全种子门禁和58组件实际payload两项验证通过，HTTP0，无服务代码改动。现18组件54案例有局部正负语义证据，40组件120案例及13任务案例仍待完整证据；011／012待办不变，不将合成输入的测试来源当实际模型或产品验证。

## 后续：两个开发角色六案例及真实红绿夹具

unit-developer／slice-developer原正常参考replace仅path，无old／new，不能算有效修复参考。现六案例补完整当前代码、合法精确替换参数、自测与提交description，并明确引用独立夹具证据；boundary已有正确代码但诊断不能代主动自测，counterexample缺权限仍无工具动作并BLOCKED。保留原所有权和空标题／恢复验收，不改正式产品或提示词正文。

`PYTHONPATH=. .venv/bin/python workspace/experiments/prompt-platform-20261010/developer_fixture_review.py` 在持久developer-validation-fixture先定目录约定，以已有Docker sandbox最多两次Node执行：固定同一三断言，red exit1、green exit0，验证正常新增、空白拒绝不改变列表、修正后重试。实际执行的是独立验证夹具，不是模型返回轨迹；参考replace／test／submit为离线构造，tools_trajectory_executed=false、model_verified=false，不能宣称模型自主完成。

developer-fixture-semantic-pairs.json保存六组正负响应、casehash及红绿真实结果；未测试直接提交或缺权限仍提交的反例自动failed，人工true不覆盖。旧生成脚本保留此审阅版，不恢复空参数。全案例待判断门禁及58组件实际payload两项通过，HTTP0，无服务代码修改。

008剩余7任务案例（repair其余四项／slice-planner三项）与40组件120案例仍需完整证据；011真实入口与剩余覆盖、012候选及新预算仍未确认。已完成的机制、合成响应、真实工具、真实模型及用户验收继续分别记录。

## 后续：五设计反馈组件15例纠正

逐项核对worker-answer-instruction-1754-1、worker-extra-1757-1／2与worker-instructions-1854-1／1861-1：原参考正文仍是产品简介，无法证明最新决定、接口／状态／流程或架构局部修订。现提供完整单元设计或架构参考，明确本地保存的confirmed_design_answers覆盖旧同步待确认，给出正式上游职责与storage共享契约；局部修订输入提供previous_architecture／preserved_sections／upstream_diff。架构extra的父角色label改为架构，避免和单元设计标签相冲突；路径与overwrite=false不变。

design-component-semantic-pairs.json保存五组件15组明确人工复核的合成响应；非法覆盖反例自动失败、人工true不能覆盖。声明工具与父角色渲染仍通过全种子／全58组件两项专项验证；不把合成参考当实际模型决定或文件成功写入。保护已审阅标记使旧生成脚本不再覆盖新具体场景。

当前23组件69案例已有此层次离线正负证据，35组件105案例和7任务案例仍需推进。新增模型HTTP0，只改案例及文档、不改服务代码或正式版本；011剩余真实覆盖与012候选／预算待确认。

## 后续：20交接与上下文组件60例

集中核对unit-developer消费的20个反馈／工具组件，补合法replace旧／新正文、调用description及具体旧／当前证据。有效绿灯且无待办的feedback-4／740-1等清除当前旧错误，v1失败明确历史；740-2／803-1不把旧错误当当前失败，现正确v2正文仍须主动自测。751-1／804-1去除未携带正文的伪current_code并保留必要read；802-1明确已携带的同版本正文，不重复读取；745-1仍承认passed=false再修复。792-1区分逻辑预算与含重试HTTP预算，不因接力重置。

handoff-context-component-semantic-pairs.json保存20组件60组正／无工具伪完成反例。正确合成参考经结构和明确人工语义核对passed，缺关键交接动作反例failed，即使人工true仍不可覆盖。除旧feedback-2／755-1当前绿灯严格提醒正常例外，其余使用ordered_actions保留必要调查穿插，不把示例顺序升级为一律禁止阅读。description字段来自合法参考参数；不声明真实工具轨迹已执行，独立红绿夹具仅校准修复方向。

相关54项通过，git diff --check通过，新增模型HTTP0；只案例／证据变更，不更改正式服务、模型提示词或预算。当前43组件129案例有离线正负语义证据，剩余15组件45例和7任务案例仍待补；011剩余真实覆盖、新入口成功与012具体候选／新预算仍待确认。用户验收与真实模型能力不由这些合成响应代替。

## 后续：切片规划与四反馈组件15例

核对slice-planner/v6实际接口映射要求，修正正常新增参考缺已交付app.mountApp契约：scaffold_contract补已交付app声明，卡片声明／required_interfaces／验收映射纳入mountApp；不要求重写已交付app。编辑boundary／counterexample纳入归app所有的verify_product.py，不能只新增页面操作后遗漏原浏览器验证脚本。保持只认领当前A1／A2，不认领未交付搜索A3。

slice-workflow-feedback-1／4／6／8共12例更新对应具体完整卡，保留原materials.test.js todo、业务结果及已交付接口；8额外提供错误attempted_card缺少saveMaterials／mountApp映射作为真实待纠正输入，结构和针对性字段检查并用。Planner三例＋四组件12例正确合成参考通过明确人工复核与结构检查，仍有todo却直接complete的反例自动failed，人工不能覆盖。

slice-planning-component-semantic-pairs.json保留15组casehash及正负判定。两个全案例门禁／58组件payload专项通过，旧规划生成脚本保留审阅标记，不恢复接口遗漏。全部是离线合成，不宣称真实模型完整切片或实际网站验证。HTTP0，无服务代码更改。剩余11组件33例及repair其余4任务案例仍待核对，011／012原待办与批准边界不变。

## 后续：四Worker产品组件完整参考与实际网页验证

worker-instructions-2026-1／2034-1／2036-1／2041-1原参考仅index片段或占位Python，不能作为完整交付。现12案例提供静态欢迎的四文件（index、verify_product、implementation、Node测试）参考；首次write=false，返修只修改原脚本硬编码URL并使用sys.argv[1]，增量比较旧标题与已批准欢迎文本，更新受影响文件及测试，不写虚构设计。代码路径／工具参数符合真实write与exec协议。这里是提示词组件验证夹具，不是重建素材平台或改变任务目标。

worker_product_fixture_review.py在持久worker-product-fixture使用已有Docker sandbox跑Node与浏览器各一次，exit0。静态夹具图标URI随后发现引号编码格式风险，修正后补同两项相关验证（原sandbox证据保留，总四次本地执行），不开展模型试错。verify脚本实际连接系统传入URL，检查欢迎内容及pageerror；不是全部控制台／网络错误验收。Node测试使用内置框架，不新增产品依赖。业务仅静态显示，无交互／错误输入恢复要求，不能推广为素材平台交付。

worker-product-fixture-semantic-pairs.json保存12组离线参考正例／无写入和测试却声称完成反例及真实夹具运行结果。model_verified=false、tool_trajectory_executed=false，真实执行的是独立固定产品夹具，不是模型工具轨迹。两个全案例／组件payload专项验证及差异检查通过，新增模型HTTP0。

剩余7组件21案例及repair四案例尚待核对；011真实入口及剩余覆盖、012候选与新预算仍待批准，整体goal不标完成。

## 后续：返修评测工具协议对齐与历史查询组件

对照Worker实际组装代码（含read／exec即附加QUERY_TOOL_SCHEMAS）发现，真实评测repair-executor分支漏只读历史查询，无法等价测试835指令的历史能力。已复用同一schema附加三项历史工具，新增测试保证原schema逐字段一致且不重复；受控入口仍只观察工具、不执行。准备输入hash随协议变化，旧批准不能用于新发送，未执行真实调用。相关55项通过。

worker-tool-instructions-759-1原参考只replace／test／submit而未查询历史，现六组中的该组件三例使用真实历史文件、模型调用与摘要ID，先file_history／model_call／detail，再比较当前合成回退副本修复。实际只读ToolSummaryStore原normal现场三查询成功、含原替换参数及结果、账本字节不变；后续replace／自测／提交仅合成参考未执行，不宣称新修复完成。同步当前design为dashboard逾期职责，避免原素材标题设计与当前目标混用。unit-workflow-feedback-1三例核对短完整JSON与原设计相符；当前文件read替代历史或违规工具替代完整JSON反例均failed。

historical-query-component-semantic-pairs.json保存真实脱敏查询页与六组正负判定。两个全案例／组件专项通过，API67420／Worker67421空闲身份核验后加载协议对齐，health及五项正式／旧计数指纹保持；新增模型HTTP0。剩余5组件15例与repair四例尚待核对，011／012待办和预算批准边界保持。


## 后续：任务级返修权限三案例

worker-tool-instructions-791-1三例补全当前dashboard故障正文、product任务授权与旧卡topics所有权边界，以及真实原逾期修复的精确old／new参数。正确合成动作修改后主动自测、显式提交，人工语义和结构通过；以旧卡不拥有dashboard为由BLOCKED且无动作的反例失败，人工true不能覆盖。task-scope-component-semantic-pairs.json保存三组正负判定；轨迹未执行、模型未验证，HTTP0，不用于版本激活或产品交付。

实际命令PYTHONPATH=. .venv/bin/python workspace/experiments/prompt-platform-20261010/task_scope_component_review.py通过；全种子案例专项1项通过，未重跑全量回归。仅案例和文档变更，无需重启服务。008剩余4组件12例及repair四例；011实际入口和剩余覆盖、012候选及新预算仍未完成。


## 后续：系统托管验证地址契约三案例

worker-tool-instructions-752-1原输入为素材标题API、参考只有replace路径，与验证职责冲突不符。现使用原素材平台完整verify_product.py，合成注入固定错误URL并提供旧卡／当前系统契约；精确替换地址后逐字恢复原绿色脚本，全部原业务操作与断言保留。正常／边界／反例三组正确参考通过；跳过验证的错误new参数自动失败，人工true不能覆盖。

verification_contract_review.py及verification-contract-semantic-pairs.json保留原脚本SHA256、逐字恢复断言、三组离线正负判定。原绿色网页证据来自已有基线，本轮未执行注入故障或合成动作，不冒充新的模型／网页运行。全种子案例专项1项通过，git diff --check通过，新增HTTP0；仅案例文档变更，无服务重启。008剩余3组件9例及repair四例，011／012未完成。


## 后续：诊断不是主动自测三案例

slice-workflow-feedback-9三例纠正诊断passed与当前业务故障混用：当前合成诊断明确只覆盖导入及接口存在，原空标题写入与错误后恢复目标仍需完成。补完整当前正文及精确替换／description，复用已有独立Docker红绿夹具校准修复方向，未执行本轮合成诊断或工具轨迹。正常／边界／反例正确参考通过，删除主动自测但保留修复及提交的反例自动failed，人工true不能覆盖。

diagnostic_feedback_review.py及diagnostic-feedback-semantic-pairs.json持久保存三组离线正负判定，model_verified=false、tool_trajectory_executed=false、HTTP0。全种子专项1项通过，差异检查通过，无服务代码变化。008剩余2组件6例及repair四例；011／012仍未完成。


## 后续：原编辑目标与最新网页失败六案例

slice-workflow-feedback-10／worker-tool-instructions-835-1原输入误用空标题或逾期上下文。现六例使用原素材平台完整topics/topics.js与verify_product.py，合成注入编辑只读旧记录及open_topic_typo两处故障；明确旧自测为v1、当前失败为v2，模型complete为未验证判断，逻辑／HTTP预算分开且不重置。

两个精确替换逐字恢复原绿色实现和验证脚本，保留原A013编辑、列表更新、重开三字段结果及关联业务断言；修改后主动自测和显式提交，系统后续独立网页验证不由Node代替。六组正确离线参考通过，只修脚本遗漏原编辑实现的反例自动failed，人工true不能覆盖。edit_feedback_review.py与edit-feedback-semantic-pairs.json保存原来源SHA256、逐字恢复断言和逐例casehash／正负判定。

来源offline_manual_review_of_synthetic_responses，model_verified=false、tool_trajectory_executed=false；原绿色网页证据是历史来源，本轮未执行注入故障或参考轨迹。全种子案例专项1项通过，git diff --check通过，HTTP0，无服务代码更改。至此58组件174例均有局部离线正负语义证据，仍需最终全范围身份／证据审计；008另剩repair四例。011／012原真实验证及预算批准缺口保持，不能标整体完成。


## 后续：剩余四返修案例完整正负参考

repair-executor的stale-green补当前已修复正文与v1过期测试，先主动验证v2再提交；business-change保留完整决策参数，BLOCKED文字不能代替工具；unfinished-after-green使用原选题完整代码注入缺编辑按钮，补回按钮／startEdit后逐字恢复原绿色实现，局部素材绿灯不证明选题完成；typo依据已批准业务解释统记／已发步，提供真实修复来源的完整精确替换参数而非口头理解。

repair_remaining_review.py与repair-remaining-semantic-pairs.json保存四组人工语义＋结构正例passed及过期直接提交／文本代决策／未完成直接提交／反转逾期规则反例failed。人工true不能覆盖自动失败。来源offline_manual_review_of_synthetic_responses，model_verified=false、tool_trajectory_executed=false，已有绿色代码只是参考依据，本轮未执行合成故障、自测或网页操作；HTTP0。全种子专项1项通过，差异检查通过。

008全86模板261案例现有局部正负证据，但最终证据身份／覆盖审计尚未完成，不据此标整体完成。known-cause真实完整回放保持原证据，不改原付费现场；旧案例hash的报告不能作为新案例激活依据。011真实入口成功路径及剩余覆盖、012候选和新预算仍待完成。


## 最终008离线覆盖及身份审计

实际执行final_semantic_audit.py，遍历注册86模板261案例，按真实消费角色渲染全部输入；对应260离线合成正反证据加1完整真实known-cause回放，逐项当前案例／文件hash匹配，正例261passed、反例261failed，无缺项或重复。全部86模板在缺人工语义判断时仍禁止启用。final-semantic-coverage-audit.json保存逐例版本、渲染SHA256、当前案例身份及证据SHA256，可运行命令为PYTHONPATH=. .venv/bin/python workspace/experiments/prompt-platform-20261010/final_semantic_audit.py。

先重跑只读replay_known_cause.py，原23动作、22产品哈希与当前提交一致，原独立Node／网页来源仍通过，原现场不变。新增HTTP0，未发布报告、激活版本或代用户验收。离线语义判断来自开发助手，260合成轨迹未执行；不宣称模型成功率或全部模型行为认证。008要求的职责预期、可运行检查器、正反离线证据及未判门禁现已实现并验证，待用户验收。011新真实入口实际成功路径／其余覆盖、012候选及对照仍未完成，整体goal保持active。
