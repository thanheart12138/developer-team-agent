# 通用产品入口修复验证

日期：2026-09-17。状态：已实现、已验证；用户验收待执行。

## 用户确认范围与实现

先更新 `docs/DEV_DESIGN.md` 的生成文件契约，再修改 Worker：

- 固定必需文件仅 index.html、verify_product.py、implementation.md。JS/CSS 路径服从正式设计，解析 HTML 直接 script src、stylesheet href 的本地引用并检查存在，支持产品站点绝对路径、查询参数和片段；不再要求根目录 app.js/styles.css。
- 产品至少有一个 *.test.js/cjs/mjs 文件，可在子目录；测试、浏览器前置 Node 验证和返修受控复验均使用 node --test。开发及验证前检查入口，避免缺失测试被零发现成功退出掩盖。
- 首次开发等模型完成全部设计文件后再校验，不在入口刚写完时截断工具循环。恢复捷径要求匹配当前设计的实现血缘。
- 修订快照与文件变化判断覆盖实际全部产品文件，含子目录与新增文件；每轮刷新可覆盖路径清单。需求变更仍要求实现和测试同时修改；实现代码哈希包含 cjs/mjs。
- 多模块手动基准脚本移除旧六文件与根目录 app.js 的适配假设，保持其单独授权的多模块/localStorage 范围。

未处理工具历史压缩；正式单模块、禁止数据存储、Provider 路由与默认调用预算未修改。未改生成产品代码、正式任务记录或历史 Trace。

## 回归验证

命令：`.venv/bin/python -m pytest -q`。

102 项通过。新增 11 项入口相关用例覆盖：无根目录 app.js、子目录与站点绝对引用、query/fragment、缺失脚本/样式、普通链接不作资源检查、越界引用拒绝、缺少测试在 test/verify 阶段返修、匹配血缘恢复、只改子目录模块的真实 Node 返修、新增模块首轮失败后下一轮可见并可覆盖。原有浏览器 SKIP 回归补齐真实入口前置条件，断言不变。

最终日志：`/private/tmp/product-entry-regression-final.log`。`git diff --check` 通过。

Node 默认自动发现及测试命名依据：[Node.js Test runner 官方文档](https://nodejs.org/api/test.html) 。本项目采用其中 *.test.js/cjs/mjs 命名，不依赖版本特有的 TypeScript 自动发现。

## 真实生成产物验证

### Task25 计算器

复制既有产品到临时目录，检查入口通过；执行 node --test 自动发现 calculator.test.js，22 项通过。临时启动静态 HTTP 服务，使用项目虚拟环境执行既有 verify_product.py，真实 Chromium 检查通过；随后停止本次临时服务。未改 Task25 产品、状态或原服务。

证据：`/var/folders/h7/z81qmxk16ks2kn3jzr21_k7m0000gn/T/calculator-entry-regression-rt6lizqv`，含 node.log、browser.log、summary.json。控制日志：`/private/tmp/product-entry-calculator-regression.log`。

### 多模块内容工具

使用前次基准生成的原产物副本，根目录没有 app.js，实际入口 js/app.js。本次独立隔离任务经过修改后的 Worker test/start/verify，Node 20 项及生成浏览器脚本通过，状态 waiting_acceptance。Trace 中实际 Node 命令为 node --test，不再指定 calculator.test.js。没有任何新增模型调用。

独立 Chromium 按原始需求操作，13 组检查通过，包括空标题后恢复、检索、多对多关联、重复转任务去重、标题独立、删除级联与删除限制、工作台状态/逾期、刷新、实际同端口服务重启后 localStorage 数据关系状态保留，页面脚本错误零。

证据：`/private/tmp/content-workbench-entry-regression-20260917`，含隔离库、Trace、报告、independent-acceptance.json、截图和最新 acceptance-server.json；控制日志 `/private/tmp/content-workbench-entry-regression-20260917.log`、`/private/tmp/content-workbench-entry-independent.log`。

仅复验已有产物与入口机制，未重新运行真实 DeepSeek 从需求到开发的完整链路，不将前次失败基准改写为成功；Windows 和用户本人验收未验证。静态检查覆盖 HTML 直接引用，JavaScript 模块内部依赖由 Node/真实浏览器验证。

## 正式服务加载

检查正式 MySQL：运行/待执行任务 0，pending Event 0。最终单 Worker PID 73874 存活，已加载修复。Task25 仍 waiting_acceptance、Task26 仍 failed，没有续跑失败任务。仅重启受影响 Worker，API 与正式预览未重启。

重启证据 `/private/tmp/worker-product-entry-20260917.json`；凭据只在受控进程环境中复用，未输出或写入证据。无数据库 schema、CI/CD、密钥或 .env 修改。临时证据可能被系统清理。
