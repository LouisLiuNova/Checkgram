# Checkgram

Checkgram 是一个自托管、轻量、无 Web 服务的 Telegram 多账号签到工作流运行器，适合在单台 VPS 上为约 5 个自有账号执行低频、正常的定时操作。

核心能力：

- 全局串行执行，不并行操作账号或工作流；
- 按本地时区定时，支持 `send`、`wait`、`click`、条件匹配和前向分支；
- 每轮固定 1 小时预算，失败后按 2/4/8/16 分钟退避；
- TOML 配置、离线校验、独立 StringSession、Docker Compose 部署；
- Loguru 彩色日志、统一敏感信息脱敏和 GHCR 发布流水线。

明确不支持 Web UI、远程 API、数据库、Redis、任务队列、执行历史、补跑、并行工作流、浏览器自动化、CAPTCHA、WebApp、支付、验证码、手机号和位置分享按钮。

## 运行语义

服务启动后只等待严格晚于当前时刻的下一次计划时间。已经错过的时间不会补跑；进程重启也不会恢复未完成的重试。

每次实际开始工作流时建立固定 1 小时截止时间。第一次失败后等待 2 分钟，随后等待 4、8、16 分钟；只有截止时间前仍有机会开始下一次尝试时才会重试。`run` 与计划任务使用相同预算，但不会改变下一次计划时间。

账号只在工作流执行期间建立 Telegram 连接，成功、失败和异常都会断开。`/data` 只保存账号 StringSession 和锁文件，不保存调度状态或执行历史。

## 准备凭据

### Telegram API 凭据

在 Telegram 官方 [API development tools](https://my.telegram.org/apps) 创建客户端应用，取得 `api_id` 和 `api_hash`。将它们写入本机未提交的 `.env`：

```dotenv
TELEGRAM_API_ID=replace_with_api_id
TELEGRAM_API_HASH=replace_with_api_hash
```

两者是客户端应用凭据，不能写入 `config.toml`、镜像、日志或 Git。仓库中的 `.env.example` 只有占位符。

### 账号认证信息

执行 `auth ACCOUNT_ID` 时，Checkgram 在终端交互读取：

- 手机号：用户自己的 Telegram 账号手机号；
- 登录验证码：Telegram 官方会话或短信收到的一次性验证码；
- 可选 2FA 密码：该账号设置的 Telegram 云密码。

这些输入不会写入环境变量、配置文件、命令参数或日志。认证成功后，Telethon 生成的 StringSession 保存为 `/data/<account-id>.session`，权限为 `0600`。它不是网站申请的 token；如果泄露，应立即在 Telegram 的设备/会话管理中终止相关会话，然后删除该会话文件并重新执行认证。

工作流只需要目标 Bot 的公开用户名，例如 `@target_bot`。当前项目使用用户账号操作目标 Bot，不运行自有 Telegram Bot，因此不需要、也不得要求 BotFather Bot Token。

## 快速开始

### 本地开发

需要 Python 3.13 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --locked --dev
cp .env.example .env

# Edit the root config.toml with your own account and workflow values.

uv run checkgram validate --config config.toml
uv run checkgram auth primary --config config.toml --data-dir ./data
uv run checkgram run daily-checkin --config config.toml --data-dir ./data
uv run checkgram serve --config config.toml --data-dir ./data
```

根目录的 `config.toml` 只包含非敏感的账号和工作流配置；`.env`、`data/` 和会话文件已被 `.gitignore` 排除，不能提交 API 凭据或会话内容。

### Docker Compose

在项目根目录编辑仓库提供的 `config.toml`，并准备 `.env` 后：

```bash
docker compose run --rm checkgram validate
docker compose run --rm checkgram auth primary
docker compose run --rm checkgram run daily-checkin
docker compose up -d
docker compose logs -f checkgram
docker compose down
```

宿主机根目录的 `config.toml` 会挂载到容器工作目录 `/app/config.toml`，与 CLI 默认配置路径一致，因此一次性命令即使命令覆盖服务默认的 `serve` 命令，也会继续使用该配置。如果宿主机缺少 `config.toml`，Compose 会直接报错；请先编辑仓库根目录提供的示例配置。

Compose 服务不暴露端口。容器以非 root 用户运行，根文件系统只读，仅命名卷 `/data` 可写；容器重建或重启不会删除该卷中的会话。默认内存上限为 256 MB，Docker 负责日志轮转。

## 配置参考

仓库根目录的 [`config.toml`](config.toml) 是最小示例，请按自己的账号和目标 Bot 修改。

```toml
[app]
timezone = "Asia/Shanghai"
step_timeout = 30

[[accounts]]
id = "primary"

[[workflows]]
id = "daily-checkin"
account = "primary"
target = "@target_bot"
times = ["08:00"]

[[workflows.steps]]
id = "start"
type = "send"
text = "/start"
next = "result"

[[workflows.steps]]
id = "result"
type = "wait"

[[workflows.steps.cases]]
id = "success"
match = "contains"
value = "签到成功"
next = "success"
```

规则如下：

- `app.timezone` 必须是 IANA 时区，`times` 必须严格使用 `HH:MM`；
- 所有 account、workflow、step 和同一步骤内的 case ID 必须唯一；workflow 必须引用已定义的 account；
- `step_timeout` 和步骤自己的 `timeout` 必须是正整数，单位为秒；
- 步骤类型只有 `send`、`wait`、`click`；`send` 要求 `text` 和 `next`，`click` 的 `text` 是上一条回复中要精确点击的可见文字；
- `wait`/`click` 至少要有一个 case。case 的 `match` 只有 `exact` 和 `contains`，匹配默认忽略大小写并去除首尾空白；
- 分支只能跳到后续步骤，或终态 `success`/`failure`；未知目标、循环、空条件和无出口都会使 `validate` 失败；
- `click` 只接受 callback 和普通文字 reply keyboard，URL、WebApp、支付、验证码、手机号和位置分享按钮会被拒绝。

## 命令参考

| 命令 | 用途 |
| --- | --- |
| `validate` | 只读取 TOML 并离线校验，不连接 Telegram |
| `auth ACCOUNT_ID` | 交互认证一个已配置账号并保存独立 StringSession |
| `run WORKFLOW_ID` | 立即执行一个工作流；不修改下一次计划时间 |
| `serve` | 持有服务锁，等待并串行执行所有计划工作流 |

所有命令都支持 `--config PATH`；`auth`、`run` 和 `serve` 还支持 `--data-dir PATH`。配置在进程启动时加载一次。成功命令返回退出码 `0`，配置、认证、锁或工作流失败返回非零退出码。

## 安全与日志

- 每个账号使用独立的 StringSession 文件，文件权限为 `0600`；
- 服务锁阻止第二个 `serve` 实例，账号锁让同一账号的认证/任务串行；
- API hash、StringSession、手机号、callback data 和完整回复不会进入日志；
- 日志统一输出到 stdout，带 workflow、账号、attempt、step、action 和 result 上下文，文件轮转交给 Docker；
- VPS 快照、备份、Docker socket/管理权限和 `/data` 卷都属于高敏感权限；
- 只使用自己的 Telegram 账号进行低频、正常操作，遵守 Telegram 的第三方客户端使用约束。

如果出现 `FloodWait`、网络错误、超时、未匹配、按钮缺失/重复/不支持，先查看脱敏后的错误分类，再检查目标 Bot、配置、网络和账号会话。不要把 API hash、验证码、2FA 密码或 `.session` 文件贴到 Issue、日志或聊天中。

## 镜像、发布与回滚

GitHub Release 发布后，`release.yml` 会先执行测试、静态检查、镜像构建和 Compose 检查，再推送 `linux/amd64` 镜像到 [`ghcr.io/louisliunova/checkgram`](https://github.com/LouisLiuNova/Checkgram/pkgs/container/checkgram)。镜像标签包括：

- Release 原始 tag，例如 `v0.1.0`；
- 对应提交的 `sha-<full-commit-sha>`；
- 稳定版额外更新 `latest`；预发布不会覆盖 `latest`。

生产环境建议固定 Release tag：

```yaml
image: ghcr.io/louisliunova/checkgram:v0.1.0
```

升级前备份 `/data` 和 `config.toml`，将 tag 改为目标版本后重新拉取并启动；回滚时恢复上一个已验证的 tag。不要用 `latest` 作为无法追踪的生产依赖。

## 开发、测试与许可证

本地质量检查与 CI 使用相同命令：

```bash
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
docker build --tag checkgram:mvp .
docker compose -f compose.yaml config --quiet
```

自动化测试覆盖配置契约、流程图、事件隔离、按钮安全、认证/会话/锁、调度/退避/预算和日志脱敏。自动化通过不等于真实 Telegram 或正式 Release 验收；真实账号认证、一次实际工作流、重启后等待和 GHCR 拉取需要在目标 VPS/仓库环境单独记录证据。

项目使用 [GPL-3.0](LICENSE)。Issue 规划见 [v0.1.0 MVP](https://github.com/LouisLiuNova/Checkgram/issues/1)。
