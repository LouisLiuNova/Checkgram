# v0.1.0 MVP 验收记录

本文记录当前仓库中可以复现的自动化证据，以及 Telegram、VPS 和 GitHub 环境的实际验收。`v1.0.0` 已发布；未完成项仍需单独验证，不能视为最终验收通过。

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
- [x] 2026-09-27 23:58（Asia/Shanghai）为第二个账号增加独立工作流，`validate --data-dir /data` 确认两个会话均存在。手动执行 `send → wait → click → wait`，一次尝试以 `success` 结束；用户已在目标对话中确认看到签到。随后重启常驻容器并再次通过会话校验，服务恢复运行。
- [x] 2026-09-28 发布 [v1.0.0](https://github.com/LouisLiuNova/Checkgram/releases/tag/v1.0.0)，Release 工作流的验证与推送作业均通过。目标 VPS 已拉取 GHCR 镜像，`v1.0.0`、提交 SHA 和 `latest` 标签指向同一镜像；镜像版本与源码提交标签吻合。
- [x] 目标 VPS 已保留原配置、环境文件和会话卷，更新仓库文件到 `main`，使用固定 `v1.0.0` 镜像重建服务；会话校验通过，容器运行且重启次数为 0。升级前已备份配置和会话卷。
- [ ] 真实答题分支、失败分支和单流程峰值 RSS 尚未观察或测量。
- [ ] 预发布不得覆盖 `latest` 的行为尚未通过实际预发布验证。
- [ ] 按 README 的固定版本方式完成一次回滚演练。

在这些外部证据补齐前，不能把最终 MVP 验收标为完成，也不能关闭最终验收 Issue。
