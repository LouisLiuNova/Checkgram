# v0.1.0 MVP 验收记录

本文只记录当前仓库中可以复现的自动化证据，以及必须在真实 Telegram/VPS/GitHub 环境完成的人工验收。未完成项不视为 MVP 已发布。

## 自动化验收

以下检查在本地工作树已执行通过：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
docker build --tag checkgram:mvp .
docker compose -f compose.yaml config --quiet
docker run --rm checkgram:mvp --help
```

当前自动化结果：

- 67 项 pytest 通过；
- Ruff 检查和格式检查通过；
- mypy 通过；
- `checkgram:mvp` 镜像构建通过；
- 镜像帮助命令通过，镜像入口为 `checkgram serve`；
- Compose 配置通过，包含非 root、只读根文件系统、`/data` 卷、无端口、能力集清空、禁止提权、256 MB 限制和日志轮转。

自动化覆盖 workflow 配置结构与流程图、事件隔离、按钮精确/包含匹配和类型安全、快速回复缓冲、可选等待超时分支、单账号认证与会话权限、session 预检查、服务/账号锁、调度/退避/预算和日志脱敏。

## 真实环境验收

目标 VPS 上已取得以下真实环境证据。部署镜像对应提交 `415184610d99398885b067390a75b7c739b1058c`：

- [x] 单账号认证已完成；服务器会话文件权限为 `0600`，`validate --data-dir /data` 确认引用的会话存在。`auth ACCOUNT_ID` 不读取完整配置的行为另有自动化测试覆盖。
- [x] 2026-09-26 手动执行一次“今日已签到”路径，一次尝试成功。
- [x] 2026-09-27 07:00（Asia/Shanghai）计划任务进入 `send → wait → click → wait`，Bot 返回签到成功；可选等待 15 秒后成功结束。对话记录中也存在对应的签到成功回复。
- [x] 2026-09-27 重启容器后会话校验通过；重启后立即观察到服务继续运行，未出现补跑日志。
- [x] 通过 SSH 检查彩色、脱敏的工作流日志；重启后空闲进程 `VmRSS` 为 58,824 kB。
- [ ] 真实答题分支、失败分支和单流程峰值 RSS 尚未观察或测量。
- [ ] 发布测试 GitHub Release，确认 Actions 成功、GHCR 中存在 Release tag 和 SHA 标签，稳定版更新 `latest`、预发布不覆盖 `latest`；
- [ ] 按 README 的固定版本方式拉取镜像并完成一次容器启动/回滚演练。

在这些外部证据补齐前，不能把本项目描述为完成正式 MVP 发布，也不能关闭最终验收 Issue。
