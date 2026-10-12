# v0.1.0 MVP 验收记录

本文记录当前仓库中可以复现的自动化证据，以及 Telegram、VPS 和 GitHub 环境的实际验收。`v1.0.1` 已正式发布并部署；Issue #1 的 MVP 完成定义已满足。额外验证项仍按下方清单分别追踪。

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

- PR #17 的修复提交完成 68 项 pytest；
- Ruff 检查和格式检查通过；
- mypy 通过；
- `checkgram:mvp` 镜像构建通过；
- 镜像帮助命令通过，镜像入口为 `checkgram serve`；
- Compose 配置通过，包含非 root、只读根文件系统、`/data` 卷、无端口、能力集清空、禁止提权、256 MB 限制和日志轮转。镜像 tag 可由 `CHECKGRAM_IMAGE_TAG` 固定；默认仍为 `local`。

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
- [x] 同时间调度故障已修复并正式发布。2026-10-12 07:00（Asia/Shanghai）旧生产镜像 `b508353` 中两个同时间工作流依次执行，于 07:00:18 和 07:00:34 成功结束，重启次数为 0；业务代码相同的正式 `v1.0.1` 镜像随后完成部署，见下方记录。
- [x] Issue #7 内存验收：升级前进程历史峰值 `VmHWM=58,544 kB`（约 57.2 MiB），生命周期覆盖真实定时工作流；cgroup 历史峰值为 82.1 MiB，无 OOM，低于约 192 MB 的目标。证据与 [Issue #7 最新验收评论](https://github.com/LouisLiuNova/Checkgram/issues/7#issuecomment-6115794159) 一致。
- [ ] 真实答题分支和失败分支尚未观察。
- [x] 2026-10-12 发布测试预发布版 [v1.0.1-rc.1](https://github.com/LouisLiuNova/Checkgram/releases/tag/v1.0.1-rc.1)，验证预发布镜像可拉取且不覆盖 `latest`；完整证据见下方。
- [ ] 按 README 的固定版本方式完成一次回滚演练。

Issue #8 所要求的自动化、文档、真实账号运行、容器重启、日志与固定版本镜像启动证据已记录。剩余的可选答题、失败分支和回滚演练仍按上方清单分别追踪，不视为已通过。

## Issue #9 预发布流水线验收

2026-10-12（Asia/Shanghai）在提交 `b508353d14b0211db19bd0869d04aec4e720ece8` 上发布测试预发布版 `v1.0.1-rc.1`。该标签用于验收发布流水线，包内版本仍为 `1.0.0`，不表示正式 `1.0.1` 已发布。

- 发布前：锁定依赖安装、Ruff、格式检查、mypy、68 项 pytest、Docker 构建、镜像帮助命令和 Compose 配置均通过；目标提交的远端 CI quality/image 作业通过。
- [Release Actions #38191318832](https://github.com/LouisLiuNova/Checkgram/actions/runs/38191318832) 由 `release: published` 触发，`verify` 和 `publish` 作业均成功。
- 实际拉取 `ghcr.io/louisliunova/checkgram:v1.0.1-rc.1` 和 `ghcr.io/louisliunova/checkgram:sha-b508353d14b0211db19bd0869d04aec4e720ece8`，两者摘要均为 `sha256:2de44051b751e501f7c0f37c8fd375593eb6e1271f04c907faacd40599e0949d`。
- 发布前后 `latest` 摘要均为 `sha256:21d2e89ca476c586d92e524144235a592a54492d01c0b711b882c87c2b131ff0`，预发布未覆盖稳定镜像；GitHub Latest Release 仍为 `v1.0.0`。
- 拉取镜像的 OCI source 指向本仓库，revision 与目标提交一致，version 为 `v1.0.1-rc.1`，created 为 `2026-10-12T01:18:27.904Z`，平台为 `linux/amd64`；运行镜像 `--help` 成功。

本次完成 Issue #9 的预发布验收，未更换 VPS 生产镜像。真实定时运行、其他业务分支和回滚演练仍按原清单分别验收。

## v1.0.1 正式发布与 HostVDS 部署

2026-10-12（Asia/Shanghai）将 rc.1 的业务代码正式发布为 [v1.0.1](https://github.com/LouisLiuNova/Checkgram/releases/tag/v1.0.1)。发布提交为 `dc18c8961b8f749f469a4fc072619bf3dfd4626f`；相对 rc.1，应用源码仅同步模块版本，依赖版本与业务逻辑保持一致。包、锁文件和模块版本统一为 `1.0.1`。

- 本地 Ruff、格式检查、mypy、68 项 pytest、Compose、镜像构建、镜像帮助命令与包/模块版本一致性校验通过。
- [源码 CI #38192938389](https://github.com/LouisLiuNova/Checkgram/actions/runs/38192938389) 通过；[Release #38192955235](https://github.com/LouisLiuNova/Checkgram/actions/runs/38192955235) 的 `verify` 与 `publish` 作业通过。
- HostVDS 实际拉取 `v1.0.1`、`sha-dc18c8961b8f749f469a4fc072619bf3dfd4626f` 和 `latest`，三者摘要均为 `sha256:4106134dd5aecf1d348c4829d0e9be5a3cdfae4c33e1a66a3b0a5e58299cd9de`。OCI revision、version 与发布提交及 tag 一致。
- 升级前独立备份 Compose、配置、环境文件和会话卷，压缩包可读、权限为 `0600`；原 `checkgram:b508353-amd64` 镜像及原 Compose 保留供回退。
- 09:48:19 使用固定 `ghcr.io/louisliunova/checkgram:v1.0.1` 重建生产服务，升级前后配置/session 校验均通过。配置、环境文件逐字比较一致，两个 session 校验和一致，无数据迁移。
- 09:48:49 回读：容器运行、重启次数 0、无 OOM，实际包与模块版本均为 `1.0.1`，`serve` 命令正确；非 root、只读根文件系统、无端口映射及 256 MiB 限额保持。空闲 RSS 约 57.3 MiB。
- 重建后未出现工作流执行日志，未观察到补跑；配置仍为 Asia/Shanghai 两项每日 07:00。按严格未来调度，下一次计划为 2026-10-13 07:00，新正式镜像的该次真实定时触发尚待后续观察。

## Issue #1 完成定义评估

2026-10-12 回读平台原生子 Issue 关系，#2–#10 全部关闭。配置/认证/引擎/调度/安全/容器/文档已有实现和验收；真实账号认证与手动运行证据见原记录，重启后会话保留且未观察到补跑；#7 峰值内存和 #9 预发布验收已补齐，同时间调度真实触发成功，正式修复版本发布并部署。

据此，Issue #1 的既定 MVP 完成定义满足。真实可选答题、失败分支、回滚演练，以及新正式镜像的下一次定时触发仍明确待验证，不作为本次已完成证据。
