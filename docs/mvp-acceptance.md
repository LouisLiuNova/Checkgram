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

- 55 项 pytest 通过；
- Ruff 检查和格式检查通过；
- mypy 通过；
- `checkgram:mvp` 镜像构建通过；
- 镜像帮助命令通过，镜像入口为 `checkgram serve`；
- Compose 配置通过，包含非 root、只读根文件系统、`/data` 卷、无端口、能力集清空、禁止提权、256 MB 限制和日志轮转。

自动化覆盖配置结构与流程图、事件隔离、按钮安全、账号认证与会话权限、服务/账号锁、调度/退避/预算和日志脱敏。

## 真实环境验收

以下项目仍需要在目标 VPS 和一个用户自己的测试账号上执行，并记录日期、版本、结果和脱敏日志：

- [ ] 使用测试账号完成 `auth ACCOUNT_ID`，确认 `/data/<account-id>.session` 权限为 `0600`；
- [ ] 使用同一测试账号完成一次真实 `run WORKFLOW_ID`，确认目标 Bot 的成功/已签到/失败分支符合配置；
- [ ] 重启容器后复用会话，确认 `serve` 只等待下一次严格未来计划，不补跑；
- [ ] 通过 SSH 检查彩色、脱敏日志，并记录空闲和单流程 RSS；
- [ ] 发布测试 GitHub Release，确认 Actions 成功、GHCR 中存在 Release tag 和 SHA 标签，稳定版更新 `latest`、预发布不覆盖 `latest`；
- [ ] 按 README 的固定版本方式拉取镜像并完成一次容器启动/回滚演练。

在这些外部证据补齐前，不能把本项目描述为完成正式 MVP 发布，也不能关闭最终验收 Issue。
