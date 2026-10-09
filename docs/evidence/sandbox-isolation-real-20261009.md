# Sandbox v1 真实隔离与集成验证

## 结论与范围

2026-10-09，用户授权启动 Docker Desktop，另行明确授权启动已有共享数据库容器 `id-photo-mysql`。已验证固定 Docker 执行边界和合成网站的完整提交验证链路，启用记录已保存，空闲正式 API／Worker 已加载。没有真实模型调用，没有续跑旧素材平台，没有代用户验收。独立目标审查使用固定响应，不能证明模型自主返修成功。

全套机制回归：`376 passed`，33.83 秒。Docker Engine 29.6.1／aarch64，Playwright 1.55.0，镜像内 Node v22.18.0。控制指纹：`30e7a35deffb54c2efe4b0d4c7068de4dc11ceff165afb3af996760237e3f99e`；实际镜像 ID：`sha256:188139e89b6496a78a6a28e72022259a41899cef53c2036912ea5466846791a4`。

## 真实工具结果

| 输入与期望 | 实际结果 |
|---|---|
| Node 尝试写冻结产品、访问宿主凭据／socket、外网和宿主桥接地址 | 写入拒绝，宿主路径不可见，外部连接失败；正常 Node 测试通过 |
| 核对实际 Docker 配置及 cgroup | 非 root、只读、断网、cap-drop ALL、seccomp、CPU／内存／PID 限制与预期一致 |
| Chromium 启动，非法输入后正常保存，再刷新 | 显式 `chromium_sandbox=True`，错误可恢复，保存及 localStorage 保持 |
| 大输出、超 PID、超内存、带子进程的悬挂测试 | 单流输出截断到 102400 字节，PID 拒绝计数增加，OOM kill 计数增加；120 秒后整容器停止 |
| 已知结果恢复和未知命令意图 | 复用宿主已有结果；未知动作拒绝重放，允许确认停止 |
| 零测试、skip、todo 输出 | 即使 Node 退出码为零，也均不满足交付测试门禁 |
| 指向宿主的产品软链接 | 冻结拒绝；宿主哨兵与原实验计数不变。其他链接／特殊文件边界由机制回归覆盖 |
| 自测→显式提交→固定 Node／HTTP／Chromium→独立审查 | 同一冻结版本到 `waiting_acceptance`，目标核销；独立审查为 fixture，模型请求为零 |
| 可信静态预览实际停止，再沿用相同 origin 启动 | 实际浏览器保存值在同地址重启后仍存在 |

原始证据均在持久实验目录 `workspace/experiments/docker-isolation-20261005/`，不纳入 Git：

- `extended-b263b394c4634bd9851f0781e84c5a4c.json`：资源、超时及恢复。
- `completion-4bf1ee8fe8664ee7ad1d47c951edef3d.json`：完成门禁、链接和宿主哨兵。
- `integration/1dedec28eb8d4cf2b387e1588778718c/result.json` 与其 `task/evidence/`：合成集成、完整执行输出及预览重启。
- `profile.json`：绑定当前控制／门禁源码、镜像、Docker 环境和 23 份原始证据 SHA-256。缺失、变化或环境不一致时入口关闭。
- `finalize_profile.py`：检查原始记录及当前指纹后生成 profile，不调用模型。

## 失败与修复过程

1. 首次真实 Chromium 在 chroot 处失败。逐字段核对官方 1.55.0 seccomp 源码，原 chroot 允许规则依赖初始 CAP_SYS_CHROOT；cap-drop ALL 下不匹配。仅在 namespace 规则增加 chroot syscall，保持非 root、cap-drop ALL 和 Chromium sandbox。此为派生 profile，不是未经修改的官方 profile。依据：[官方 profile](https://raw.githubusercontent.com/microsoft/playwright/v1.55.0/utils/docker/seccomp_profile.json) 与 [Playwright Docker 文档](https://playwright.dev/python/docs/docker) 。
2. 第二次合成页面缺少 UTF-8 声明导致中文断言失败，补齐探针页面声明；未修改真实素材平台。
3. 未知动作停止后，门面检查仍因历史未知意图返回 unknown。改为先核对底层容器确已停止，再保存 stopped，保留未知动作记录并禁止重放。
4. 探针运行期间变更控制源码使恢复指纹失效，按设计拒绝继续；失败证据保留。最终探针在固定源码后重新完成，不能把旧指纹成功记录直接用于新版本启用。
5. 预览同端口重启时，普通 socket 端口探测把 TIME_WAIT 判为占用。探测使用与 HTTPServer 相同的 SO_REUSEADDR，仍拒绝活动监听者；同 origin 实际停止／重启后浏览器持久化通过。

失败、停止容器、快照和日志全部保留，没有清理旧现场。直接浏览器脚本还要求显式 sandbox 参数并拒绝关闭参数；AST 检查只用于受支持脚本兼容性，不作为恶意代码隔离证明。

## 正式服务与成本

只读核对任务空闲后，停止本项目旧 API 36259，启动 API 33329／Worker 33330，健康检查通过。重启前后五项核对全部保持：正式任务／事件／运行指纹、schema、文件登记状态、产品字节、旧隔离实验调用计数。旧 Task 26 的 execution_mode 仍为 null，未发送任何事件。

核对记录：`workspace/experiments/formal-service-recovery-20261003-4caius6l/repair-v1-reload-result-20261009-sandbox.json`，及同日期 before／after 文件。共享数据库仅启动，未修改配置、schema 或数据；其他旧容器未启动。本轮新增模型 HTTP／Token 均为零，旧素材平台 220 次累计预算保持，不自动追加。

## 当前限制与下一步

已验证的是本机固定原生网站测试 sandbox 和程序集成；没有证明任意恶意代码安全、多租户生产隔离、真实模型收敛或真实缺陷修复。旧流程仍按原路径运行，未自动迁移。连续主会话、任务范围写权限与搜索优化尚未实施；真实模型验证需另有明确任务及调用上限，不能沿用本轮零调用探针授权。
