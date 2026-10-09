# Docker 隔离实施记录

## 范围与当前结论

用户于 2026-10-05 确认隔离设计，授权实现和合成探针。仅新增隔离执行能力，不调用真实模型、不续跑旧任务、不增加 220 次旧预算、不提交或推送。当前为实施中，真实容器隔离和流程集成未完成，新入口仍关闭。

## 配置依据

- 现有开发依赖为 Python Playwright 1.55.0，保持版本，用官方 Python Noble 镜像；版本匹配、非 root 浏览器及命名空间 seccomp 来自 [Playwright Docker 文档](https://playwright.dev/python/docs/docker) 。
- `docker buildx imagetools inspect` 核对多平台 manifest 为 `sha256:640d578aae63cfb632461d1b0aecb01414e4e020864ac3dd45a868dc0eff3078`，包含 arm64；本机 Docker 29.6.1／linux arm64。
- seccomp 原样保存自 [官方 1.55.0 profile](https://raw.githubusercontent.com/microsoft/playwright/v1.55.0/utils/docker/seccomp_profile.json) ，SHA-256 为 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`。
- 初次下载 profile 因本地环境 SOCKS 依赖缺失失败；改用现有 HTTP 代理的显式客户端完成，未安装 host 依赖、未修改环境或密钥。
- 镜像内安装相同 Playwright 包，使用其 bundled Node，实际 Node 版本和浏览器兼容仍待构建／运行验证。

## 已实现的机制

- `container_execution.py`：冻结快照、禁止链接／特殊文件／凭据路径、固定容器参数、启动前实际配置核对、宿主意图／结果、未知结果停止、超时停止整个专用容器，不删除现场。
- `runtime-images/website-repair/`：固定 digest、非 root、控制程序只执行 Node 测试／固定浏览器脚本／HTTP 健康检查，无 shell；有界输出由宿主落证。
- 独立合成探针现场位于 `workspace/experiments/docker-isolation-20261005/`，不含正式数据或认证。

## 已执行验证

1．`.venv/bin/python -m pytest tests/test_container_execution.py -q`：最初 7 项通过，补未知结果不重放／完整结果复用及非法参数后 11 项通过。

2．`.venv/bin/python -m pytest -q`：360 项通过，35.44 秒；使用测试夹具与本地 Node／回环服务，未调用真实 Provider。存在既有弃用告警。

3．补实际配置含凭据／可写挂载时拒绝的回归后，隔离集合 12 项通过，0.03 秒。未再次扩大运行全套。

4．新增可信静态预览及回环验证，与隔离集合共 13 项通过，0.60 秒。同 origin 更新快照、健康提交标识、冻结 HTML 字节、生成 Python 仅返回文本、目录越界返回 404 均实测；尚未集成正式启动和独立进程恢复，浏览器 localStorage 同 origin 实测仍待补齐。

5．只读 registry ARM manifest 显示压缩层约 30／45／91／776 MB，总计约 942 MB，其中前两层已完成；下载尚未报错，不据此归因网络失败。控制程序补读取 cgroup 资源事件，实际资源耗尽验证仍待完成。

6．官方 776 MB 层经现有显式 HTTP 代理抽样请求返回 206，1 MB 用时 11.8 秒；仅证明该抽样路径可达，不代表 Docker daemon 全层下载速率，也不据此改 Docker 配置。配置指纹进一步绑定 `.dockerignore`；命令结果同时绑定标签／控制配置，隔离集合再次 12 项通过，0.04 秒。

## 尚未验证

专用镜像下载进行中。完整 Docker 探针、实际沙箱浏览器、外网／宿主网络阻断、资源耗尽、超时后代清理、实际恢复、同 origin 预览及自测／固定验证集成均未完成。不生成成功 profile，不解除 `isolation_ready()` 门禁，不把单元测试视为真实隔离成功。
