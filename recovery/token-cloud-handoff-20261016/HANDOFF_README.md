# 公开仓库交接说明

此目录是云端独立候选，尚未与 Mac 的未合并改动做三方合并。目录外的原仓库文件保持原样；不要直接把本分支合并 main 作为功能升级。进入 candidate/ 阅读和选择性迁移代码。

后续真实运行前仍缺：最新跨环境完整预算与分供应商账核对、唯一执行者确认、实际授权边界、真实运行环境及获准连接验证。不得凭本目录开启真实模型请求。历史 164 项离线通过为保存证据，本次上传未重跑测试。

本公开副本把历史文档中的个人本机用户路径替换为 /Users/USER；除以下公开化处理外，源码与原交接包一致。SHA256SUMS.json 已按公开副本重新计算；SOURCE_PROVENANCE.json 中来源 SHA 是原始来源的历史值，改动文件见 PUBLICATION_MANIFEST.json。原附件 zip 的 SHA 不适用于此目录。

# Token 云端源码交接：164 项离线修复版本

用途：交给同一用户的 Mac Codex 在独立目录做源码比较与选择性迁移。不要机械全覆盖本地的两个协议分支，不要覆盖原实验、真实账本、配置或凭据。142 与 164 是不同来源/范围的离线测试计数，不能直接比较质量，也不能相加。

## 内容与基线
- candidate/ 是 mainline-low-candidate 当前 UTF-8 文本源码、测试、仓库提示词模板/测试样例、前后端依赖声明及 package-lock.json、文档的原字节副本。不是原始真实模型请求存档。
- 基线：thanheart12138/developer-team-agent，commit 5a9b7307a435e5a83a3a505a7a2c6bd6f0e91563。恢复记录标明 480 个已校验 Git blobs；4 项历史二进制证据未恢复，本包不声称补齐它们。
- BASE_TO_CURRENT.patch 是本次直接从保存基线文本到当前 candidate 生成的增量；BASELINE_SHA256.json 记录对应基线文件 SHA256，DELTA_FILES.json 列出增量。优先三方比较：保存基线、云端 candidate、本地分支。不要把阶段补丁重复叠加到当前 candidate。
- evidence/ 中 auth-scan 与 live-adapter 的报告、补丁、manifest 保留原字节。阶段 manifest 引用的 .log 文件未随包传递，避免把日志当源码；本包 SHA256SUMS.json 是实际内容索引。
- test-guard/sitecustomize.py 是原离线网络/容器守卫。
- dependency-versions.txt 是历史云端已安装版本快照，不是跨平台锁；后端按 requirements.txt/requirements-dev.txt 声明，前端 package-lock.json 为仓库锁。没有携带虚拟环境或安装任何依赖。

## 阶段变化与真实边界
1. 基线后已有 low 上下文优化、连续账、预算预约、响应保全、离线 runner 与 controlled transport。历史全套 654 passed / 4 环境失败发生在后续改动之前。
2. auth-scan：请求头/Chat SSE/Responses 使用同一调用侧认证值做泄漏扫描；新增14例先6失败8通过，修复后相关46通过。仅合成认证值与离线测试。
3. live-adapter：显式 call_approved_direct，官方 DeepSeek 或 OpenRouter Luna 精确路由，必需可信授权核验器、认证加载器及沿用获准网络策略的客户端工厂。没有默认生产连接，无 Go/Kimi/自动重试/重定向。
4. 独审修复：不强制绕过现有代理/证书网络路线；settle 异常时仍保存 HTTP 账结果。两账不是跨文件原子事务，崩溃后 pending 仍需对账。
5. 最后保存的定向离线回归164通过：live28、controlled38、offline8、budget35、lineage14、response27、transport14。包含先前160/70/46，不得累加。本次打包未重跑任何测试。

既有脱敏真实报告仅是保存截点：73 HTTP（70已知、3未知），输入2361313、输出384783、合计2746096已知tokens。包含失败重试；reasoning 已含 completion，不二加。该文件不是当前余额证明。不得以离线 fixtures 的 attempted 字段增加真实 HTTP，不得将 unknown 记0，不能重置219060非实际保留量。15项产品验收未运行，同范围同质量完整任务≤100万目标未证明。真实调用前仍要核实最新完整跨环境及分供应商账、实际授权/子轮边界和安全连接。本包不提供凭据。

## Mac 独立比较和复核
1. 解压到新的独立目录，保留本地当前分支/未提交改动，用 SHA256SUMS.json 校验本包；记录本地 HEAD 和差异再做三方比较。
2. 重点比较 backend/app/runtime/{live_token_transport,controlled_transport,token_offline_runner,task_budget,token_lineage,token_response_evidence,token_transport}.py 及对应测试；实际路径以 DELTA_FILES.json 为准，若某名称不存在不要凭此列表创建替代模块。
3. 先看 ROADMAP.md、docs/evidence/token-controlled-transport-20261015.md、docs/architecture-issues/005-prompt-governance-and-cost-attribution.md、docs/INTERVIEW_GUIDE.md，保留本地两协议分支的处理逻辑。
4. 以下是复核命令说明，本包未执行。将 PYTHON 设置为 Mac 已有、依赖匹配的隔离解释器绝对路径，在本包根目录执行：

ROOT="$PWD"
cd candidate
env -i PATH=/usr/bin:/bin HOME=/tmp PYTHONPATH="$ROOT/test-guard:." "$PYTHON" -m pytest -q tests/test_live_token_transport.py tests/test_controlled_transport.py tests/test_token_offline_runner.py tests/test_task_budget.py tests/test_token_lineage.py tests/test_token_response_evidence.py tests/test_token_transport.py

必须保留外部 test-guard 的 PYTHONPATH；测试内 mock 不是唯一网络保护。不要启动应用、容器或真实模型探针以代替上述离线校验。适配器回调是可信上层代码约定，不是抵抗恶意 Python 的权限系统；测试 lambda 不能当生产授权。
