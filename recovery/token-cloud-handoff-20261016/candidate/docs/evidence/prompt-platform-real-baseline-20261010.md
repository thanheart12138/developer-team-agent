# 提示词平台与有限真实基线，2026-10-10

## 已确认范围

用户确认007—012实施契约；本轮另明确授权向DeepSeek发送同一素材平台隔离代码、批准文档、工具协议和脱敏案例，最多30次实际HTTP，包含失败与重试。普通返修20、业务变更探针5、未完成业务探针5。012候选与对照另批。本轮无人工改产品、无用户验收事件、无提交推送。

## 007—010实现证据

- 注册表86项模板／组件，116份版本文件；新增76份从原源码迁移，独立对照Git原HEAD逐字一致76／76。模板不是86个Agent。原返修v1—v5与旧会话哈希保留；组合、变量及渲染身份写入Trace，会话固定版本恢复。
- 每项都有契约、正常／边界／反例及三级分类；通用语义需要人工判断，检查器示例不是模型输出。重要或普通未执行／待判断／失败禁止激活，轻度提示。候选变量不匹配、旧案例哈希、客户端伪造来源均被拒绝。
- 管理页面可查看、创建、比较版本、编辑案例、离线运行、查看报告与受控启用。隔离Chrome实际10项检查通过；正式入口`http://127.0.0.1:5173/?view=prompts`。真实基线通过既有Worker入口执行，再由受控运行器登记到管理页面。正式页面只读Chrome核验真实来源、426,372Token、19／30HTTP与启用禁用通过，pageerror为0，截图已留存。页面尚无启动真实批次按钮，不能称UI付费执行闭环完成。
- 阶段分析入口`.venv/bin/python -m backend.app.runtime.execution_cost --task-root <持久任务目录>`只读；同HTTP不拆Token，失败与未知usage保留、逻辑重试不重复动作边界。旧全量到验收179HTTP／16,091,294Token：修改前2,062,787，通过前11,410,758，通过到提交1,214,935，其他1,402,814；旧切片按其实际自测范围统计，不冒充全平台绿灯。
- 最新完整回归452项通过，39.17秒；正式API21607／Worker21608加载后health通过、五项正式状态／旧预算指纹保持；前端build通过；旧deprecation警告5607条。早期沙箱端口权限失败经允许本地监听后通过。迁移审计86项通过，无未登记inline调用。

## 011真实结果

持久目录`workspace/experiments/prompt-real-baseline-20261010/`，approval、起点SHA、控制脚本、SQLite、请求／响应、工具、预算、独立原回归及phase-cost均保留。绿色原Node150／Chromium60通过，注入故障两者失败后才真实发送。

| 案例 | HTTP | Token | 结果 |
|---|---:|---:|---|
| 工作台逾期返修 | 17／20 | 378,342 | 显式提交→待验收；独立原Node150及实际Chromium60通过，103.2秒，人工产品改码0 |
| 未批准自动发布业务变更 | 1／5 | 24,737 | 第一批request_decision，未执行返回动作 |
| 绿灯仍有选题编辑目标未完成 | 1／5 | 23,293 | 第一批search两次，未提前提交；后续修改与交付未验证 |
| 合计 | 19／30 | 426,372 | 用量未知0；剩余额度不自动转给012 |

普通返修阶段：修改前4HTTP／61,704Token；修改到有效绿灯4／128,596；绿灯到提交9／188,042；合计严格对账378,342。第4次修改、第5次自测通过，第6—12次补查覆盖，第13次增加回归、第14—15次核查写入（两次读取被拒绝）、第16次重测、第17次提交。修改使旧绿灯失效，重测计入通过前，不能把全部9次判为无效。

原同场景11HTTP／262,827Token；本轮多6次HTTP，Token高43.95％。原指令迁移逐字等价，但模型行动轨迹不同且增加了回归测试；单轮不能证明注册迁移导致退化或模型稳定性，也不能宣称优化收益。新增测试强化已发布与状态回退断言，保留原测试不弱化。

管理报告`ab8e7aa98f2c4e3da8ffb2f6c604311b`：普通修复与业务决策通过；未完成业务只局部观察，pending；过期绿灯未跑，not_run；轻度错字未跑。禁止激活。早期登记报告`e15d31a4adfc4a47a993147eafd651ce`误将局部探针按完整序列判失败，已保留并由新报告修正，未删除失败记录；这不是模型完整返修失败。完整行为检查改为关键动作有序子序列，仍拒绝缺测试或先提交；局部观察不能人工改成完整通过。

## 局限与下一步

007—010机制已实现并验证，不代表每项提示词已获真实质量认证。011三项授权测试结束，平台结果可读；跨文件完整修复、重要反例完整过程及页面启动真实批次仍未验证／实现，011不标完整完成。012建议只调整覆盖调查时机，在首次自测前核对反馈／必要回归，绿灯后依具体未决问题继续；允许必要阅读修改、保持显式提交及协议历史。候选与最多30次对照已请求确认，未实施、未外发对照。

## 后续推进：受控真实入口与固定版本

受控入口已加入backend/app/runtime/prompt_real_evaluation.py、管理API及页面：仅执行固定输入的一次真实响应；生成待审批manifest／input，批准需匹配输入、工具、组合、模型与目的地身份。无审批、输入变化、异常SQLite现场被拒绝；已有receipt返回原报告，不重发。失败／未知usage保留。工具不执行，完整软件修复仍走Worker／Docker，不将首批探针冒充完整交付。运行目录约定先写README。

实际CLI prepare已执行，ID`0d447839edc54ee09cf5ad16ed876470`，重要business-change案例，最多1HTTP；只创建待审批输入，未写批准、未发送。真实页面点击收到real_model_authorization_pending，未创建SQLite或预算，旧真实报告仍可读，pageerror0，截图与browser-runner-result.json留存。相关51项回归通过；新增所选版本绑定回归与真实入口5项共6项通过；前端build、注册审计、diff检查通过。本次未再跑全套，此前452项全量结果不冒充新代码全量验证。

修复会话创建时固定所选repair-executor版本，防止以后候选v6被激活v5覆盖。用已登记v4／激活v5差异的回归，在模型发送前核对snapshot与主版本一致；没有新增候选正文或真实HTTP。API25411／Worker25412已加载，health及五项原正式／旧计数指纹保持。最终增加运行中输入变化保护与异常状态展示，6项定向回归通过后加载API26400／Worker26401；health及五项正式／旧计数指纹仍保持。

011页面单次输出／首批行为入口已实现，真实授权成功路径目前仅由隔离协议夹具验证，不新增付费调用；原完整返修与两个真实探针仍是上一轮的19HTTP。完整跨文件场景及反例后续交付仍需具体授权，012候选／预算确认未收到。总目标保持进行中。

## 完成审计纠正：组合门禁与具体预期

发现主模板身份不足以证明公共规则未变，已在离线报告与受控真实登记保存component_bindings，激活核对相关公共active版本及模板正文哈希，缺旧证据不能激活。未启用新候选不影响旧报告；相关公共启用改变后拒绝，未涉及组件不纳入全注册表一刀切失效。实际原Trace与两探针发送体的组件身份重新读取得到新报告`593786eb1052406e8bbb2ccae67bd6d6`，仍19HTTP／426,372Token，无新发送，旧报告保留且缺组件证据不能激活。

进一步发现86项案例有相当部分是通用骨架，「遵守模板」不足以满足每项不同输入／反例预期的目标。此前008「已完成」表述过早，现改进行中。先细化8个角色：product-gate、product-draft-reviewer、product-change-coverage、design-candidate-reviewer、design-reviewer、design-transition-planner、initial-design-planner、acceptance-consistency-validator。具体覆盖视觉非阻塞、核心交互未知、新反馈优先、保存刷新遗漏、行为方向相反、内部接口越界、仅文字差异复用、缺上游证据、存储边界变化、残留候选标题、编号项分类遗漏与固定评审写入路径。design-transition的变量从无意义占位值改为真实行动枚举；没有修改运行提示词正文。

8角色25个参考夹具经过实际模板渲染／受控检查一致；此为offline_checker_fixture，不是模型效果证据。错误行为方向、错误ready／reuse决定不能被人工通过覆盖，新增回归；本轮18项相关回归通过，注册与差异检查通过。含之前已专门定义的repair-executor，当前9／28任务角色有针对性案例；其余19任务角色及58组件的预期仍需职责化细化／检查，不能以文件数宣布全部完成。普通与重要人工语义仍待评审；真实调用授权不是人工语义验收。

本轮新增模型HTTP0，原30授权的三测试不自动续跑。012具体候选改动及新对照预算依旧等待明确答复。

最终服务加载API30377／Worker30378，health通过，正式数据／schema／文件状态／产品哈希及旧计数五项保持；最新注册审计86项通过、git diff --check通过。

## 后续：28任务角色具体案例补齐

继续按已登记的实际职责细化剩余19角色。3审查／定位角色覆盖合并独立动作、持久化方向相反、局部修正假闭合、堆栈并非根因、错误测试期望及证据不足。6行为／控制角色覆盖独立动作数量、错误后恢复、局部add／replace、仓储并非页面、浏览器操作未执行、调查前不猜代码根因、最新有效门禁及协议错误纠正。7文档／开发／公共执行角色覆盖指定版本路径、overwrite=false、上游方向、只写owned_files、诊断不替代主动自测、BLOCKED权限及任务边界。3规划角色覆盖唯一文件／公共操作所有者、module／feature边界、骨架未实现及todo、单卡只认领实际交付ID、原todo和页面编辑补缺。

28／28任务角色现有87个固定案例，正常／边界／反例均保留，角色语义项仍pending，参考响应不是模型输出。all-task-case-audit.json实际渲染与夹具检查一致。新length检查数量以拒绝合并、丢失或额外条目，负数／布尔／字符串期望被拒绝；错误complete、category、action或目标数量不能被人工通过覆盖。相关21项回归通过，未重跑全量，此前452不冒充当前代码全量结果。

案例变量与预期改变会使该角色旧报告失效；没有修改提示词正文、产品代码、正式设计或已有实验计数，新增模型HTTP0。58公共／反馈组件仍是待细化骨架，008继续进行中；不能把28角色定义齐全说成86项已获真实质量认证。012候选／新对照预算仍待明确答复。

最终追加文档已存在的安全停止预期，action_parameters仅在实际调用工具时校验指定路径／overwrite，严格拒绝true、0或其他路径；语义保留人工判断，不能提前自称交付。22项相关回归通过，28角色87夹具最终一致核对通过。只改评测器与案例，未修改模板正文或新增HTTP。

最终API37394／Worker37395已加载，health与五项正式／旧计数指纹保持。

## 后续：58组件组合预期与最终离线核对

58公共／反馈组件新增174个职责场景，标明真实消费角色、父角色变量和声明工具；片段与消费角色组合评测，父角色版本改变使批准输入与报告失效。连同28任务角色87案例，现86项261案例。参考响应明确标为检查器格式夹具，尚未人工认证完整业务语义；不将夹具通过解释为真实模型全部正确。

新增骨架与切片结构检查复用现有解析器，重复文件所有权、缺少验收映射等错误不能被人工通过覆盖；不执行生成代码。all-case-final-audit.json核对全部86项未判语义时关键案例阻止激活，58组件结构夹具通过。35项相关回归、前端build、86项注册审计与git diff --check通过；未重跑最新全量，历史452项不作为本次全量结果。父角色组合提示与格式夹具警示已实现，最新页面视觉检查未执行。

正式空闲服务身份核验后已加载API48864／Worker48865，health通过，正式数据、schema、文件状态、产品哈希及旧实验计数五项保持。证据位于workspace/experiments/formal-service-recovery-20261003-4caius6l/repair-v1-reload-result-20261010-component-cases.json。本轮新增模型HTTP0；原真实批次19HTTP／426,372Token保持。008语义评审仍待完成，011新入口实际模型成功路径与其余真实覆盖未验证，012候选和新预算未获确认，整体goal不标完成。

## 后续：损坏工具轨迹不能误判通过

逐项审计发现action_sequence／ordered_actions／allowed_tools原先过滤非对象动作，损坏轨迹可能匹配空白名单或有效子序列。现先验证整个动作列表及非空字符串tool_name，异常直接失败，保留合法空列表与调查穿插。18组异常输入回归覆盖null、对象、字符串动作、夹杂null、空工具名与数字工具名；相关总53项通过。该检查器修复不改变提示词正文或模型协议，不将语义待判断改为通过。

空闲API49943／Worker49944已加载，health及五项正式／旧计数指纹保持；本轮新增模型HTTP0。008仍待完整语义评审，011仍有真实执行覆盖缺口，012候选与新30HTTP预算仍待明确确认；自动goal续行不等于付费授权。

## 后续：当前组件页面实际验证

使用真实Chrome访问5173管理页，选择scaffold-workflow-feedback-1，消费角色architecture-scaffolder与「工具只观察不执行」说明可见，格式夹具不是完整语义响应的警示可见；填入示例实际包含normal／boundary／counterexample三案例，页面错误0。截图component-page.png已实际查看，结果browser-components-result.json持久保存。只读检查未创建报告、未更改版本、模型HTTP0。首次按钮名称精确定位失败（名称还包含用途），确认进程终止后按实际模板标题定位复测通过，不归因模型或产品缺陷。

此证据补齐最新组合说明页面验证，不补齐008完整语义正确／错误响应认证，也不补齐011真实入口成功与012对照。后续必须保持这三种证据分开。

## 后续：交接案例输入矛盾修正

语义核对发现worker-feedback-2／worker-tool-instructions-755-1从父角色复制了当前空标题缺陷，却同时要求v2当前自测通过且无待办后直接提交。现六个案例把v1缺陷标为historical_failure，v2正文明确已修复且current_failure为空；normal使用v2绿色证据，boundary／counterexample使用v1过期证据，保持先验证v2再提交的预期。同步持久案例生成脚本，避免重生成恢复矛盾。

新增两个参数化回归核对历史／当前版本，过期案例直接提交必须失败；管理／真实评测相关49项通过。全案例扫描未再发现同时current_failure非空且self_test passed的输入；这只是特定矛盾检查，不是全部语义认证。正式API只读核对六案例动态加载一致，证据handoff-case-semantic-audit.json；不修改服务代码，无需重启。首次本地httpx受系统SOCKS代理及沙箱限制，改为仅本地直连并获工具审批后核对成功，不更改模型客户端trust_env配置。

新增模型HTTP0，不改变原19／426,372计数；008仍待其余完整语义审阅，011／012原验证与批准缺口保留。案例hash改变会使这两个组件的旧案例报告失效，未激活版本或修改模型提示词正文。

## 后续：业务决策参数与语义检查

逐字段核对repair_session.DECISION_SCHEMA与_request_decision：question／impact／proposal必需，运行时要求非空字符串。原business-change只核对request_decision名称，空parameters格式夹具也能通过，不能作为有效澄清证据。新增受控nonempty_string检查三个字段，参考夹具补齐明确的自动发布决定、影响及等待批准方案；额外人工项判断是否对准实际业务改变，无关问题不应通过。

四组缺字段／空白／null／数值输入不能人工覆盖失败；正确离线示例未判语义为pending，明确离线判断后该例passed，但其他未执行案例仍禁止激活。相关53项通过，decision-case-review.json仅离线检查器证据。案例hash已变化，旧真实报告保留原现场，不自动改写为新契约通过；旧准备运行也因输入hash变化不能沿用批准。

API52444／Worker52445空闲身份核验后加载，health及五项状态指纹保持。模型HTTP0，原19／426,372不变；008其余语义审阅与011／012缺口仍保留。

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

## 后续：离线命令身份与判定依据补齐

按008实际运行交付条件检查发现，原CLI仅source与判定，没有模板版本／组件身份／输入字节hash。增加可选--prompt及--version成对绑定，复用平台模板渲染门禁但不写正式报告；不绑定明确template_binding=null。输入cases／observations／judgments实际字节分别SHA-256，逐例输出basis和forbidden，原返回码与未知语义门禁不变。

实际命令缺响应报告bound-cli-report.json绑定design-author/v1与三个渲染组件身份，not_run退出１；回归还覆盖未绑定为null及缺版本拒绝。相关54项通过，使用说明更新。该入口证据解决身份追溯，不替代仍未完整的修复／组件正负语义证据。

API56339／Worker56340核查空闲与身份后加载，health及五项正式／旧计数指纹保持。新增模型HTTP0，011后续真实与012候选／预算尚未获新批准，整体目标继续进行中。

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


## 最新系统全量回归

本轮全量在默认沙箱首次结果4failed／493passed，四项涉及本地HTTP服务因Operation not permitted失败；未改实现绕过。获准本地监听后重跑同一完整集合，结果：497 passed, 5614 warnings in 38.25s。日志持久于workspace/experiments/prompt-platform-20261010/full-regression-final.log，退出0。git diff --check通过，新增模型HTTP0，未改正式服务、数据库或active版本。该系统回归不替代011新入口的付费实际模型成功路径或012候选对照，授权缺口仍保持。


## 最终批次已获授权并启动

用户回复「授权」，批准执行单、新30HTTP按20／8／1／1分配及既定外发。候选v6新增首次自测前完成必要实现／回归的顺序提示，正式active仍v5。workspace/experiments/prompt-final-real-20261010保存目录约定、approval、75文件输入hash、候选离线结果及preflight。逾期起点hash与原故障c9f8018d566fba431d18fa1aac31231f304a4ee91df1088f063d24bfa40dc215一致；原绿色Node／网页exit0，normal／cross-file Node及网页exit1。候选五例离线passed，不冒充候选真实质量。normal真实进程已启动，结果／成本待确认；平台首响应prepared4010aea5a9b046bab9c7312b94160060已按当前input_hash批准1HTTP，尚未发送。旧现场和计数保持，不自动激活或验收。


## 最终授权批次实际结果（报告整理中）

新批次全部四子项已终止，实际18／30HTTP、296,633Token，剩余额度不互借或自动重跑。normal候选v6用8HTTP／137,623Token到待验收，原独立Node／浏览器exit0，43.8秒；cross-file用8HTTP／131,584Token预算耗尽stopped，独立原Node／浏览器exit0但未主动自测并显式提交，不能算流程成功，25.2秒。业务反例1HTTP／24,207Token返回两search而非request_decision，工具未执行；平台入口1HTTP／3,219Token真实请求、响应、计数和报告成功留存，返回两search，业务判定pending。报告c57260d4ef804c518a7751d8e2bc776c真实来源，未激活候选。

normal对照17HTTP／378,342Token本次下降63.63％，但只是一轮轨迹差异；跨文件与业务反例未达期望，不能据此推广总体质量或正式采用候选。全部原始现场及汇总summary.json在workspace/experiments/prompt-final-real-20261010。下一步核对完整请求／工具轨迹、同起点差异、阶段对账与最终采用建议，不追加调用、不代用户验收。


最终批次分析见[真实结果与失败轨迹](../evidence/prompt-final-real-analysis-20261010.md) 。跨文件具备修法后调查延迟到最后预算，反例已理解业务冲突但先搜索；不是已证明的模型能力不足。候选节省仅单场景且额外测试覆盖不同，建议不激活，采用待用户确认。HTTP不追加，所有失败及局限保留。


## v6原名修订，真实效果待验证

2026-10-10用户要求继续修复且「还是叫v6」，已先更新有效设计中的单次原名修订例外，再修订未激活候选。用精确原hash验证并留存旧正文v6-original.md；原真实请求／报告／结束会话不改写，旧报告不可批准新正文，原hash会话不静默迁移。管理API仍不提供覆写版本能力。

新v6移除首次自测前完成所有覆盖的附加提醒，改写已有调查推进规则：当前正文、明确修法和授权充分时先修改、主动自测并观察；仅可能改变修法、权限、业务预期或安全结果的问题阻塞修改，确需理解测试仍可读取，已知剩余业务不能交给测试自动证明。业务变更已有批准规则与明确冲突时直接request_decision，不为充实影响说明先搜索；确有决策信息缺口可补证据。

修订hash为5fe9c1a1e0bb74152938bb2d2d4112924536bd89a8a9d61610139eff28df74b1，旧hash为e1a90f0bc9e72655d437bcfad13772269997e666850a6cd5829e2548bb5214fd。workspace/experiments/prompt-v6-revision-20261010保存原正文、revision与offline-verification。五原关键参考passed、五遗漏动作反例failed；隔离副本实际activate拒绝两旧报告evaluation_stale；版本冻结及只读历史协议两项回归通过，diff检查通过。此为离线参考与门禁证据，不证明模型行为改善。新增HTTP0，正式active仍v5，修订v6未真实验证，012继续进行中。


修订v6真实验证已完成，详见[本轮结果](../evidence/prompt-v6-revised-real-20261010.md) 。新9／11HTTP、140,620Token：业务首次真实request_decision成功；跨文件7修改／8主动自测passed后预算停止，未提交，独立固定回归通过；Token较原同场景高2.41％。正式v5保持，012未完成，不追加或转移剩余预算。


修订v6实际上下文只读诊断见[依据保留与预算推进](../evidence/prompt-v6-context-diagnosis-20261010.md) 。第5—7次原根因与修法均重传，实际HTTP余量正确；排除接力丢失解释。双预算与未记录进度只是可能的显著性问题，未验证因果。第9Trace构造后被预算拒绝，不计HTTP。建议主返修会话统一有效预算与缺失交接事实视图，未实施，待用户确认。HTTP0。
