# Checkgram

Checkgram 是一个自托管、轻量、无 Web 服务的 Telegram 多账号签到工作流运行器，适合在单台 VPS 上为约 5 个自有账号执行低频、正常的定时操作。

核心能力：

- 全局串行执行，不并行操作账号或工作流；
- 按本地时区定时，支持 `send`、`wait`、`click`、条件匹配和前向分支；
- 每轮固定 1 小时预算，失败后按 2/4/8/16 分钟退避；
- TOML 工作流配置、离线校验、独立 StringSession、Docker Compose 部署；
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

# Edit the root config.toml with your workflow values.

uv run checkgram validate --config config.toml
uv run checkgram auth primary --data-dir ./data
uv run checkgram validate --config config.toml --data-dir ./data
uv run checkgram run daily-checkin --config config.toml --data-dir ./data
uv run checkgram serve --config config.toml --data-dir ./data
```

根目录的 `config.toml` 只包含非敏感的账号和工作流配置；`.env`、`data/` 和会话文件已被 `.gitignore` 排除，不能提交 API 凭据或会话内容。

### Docker Compose

在项目根目录编辑仓库提供的 `config.toml`，并准备 `.env` 后：

```bash
docker compose run --rm checkgram validate
docker compose run --rm checkgram auth primary
docker compose run --rm checkgram validate --data-dir /data
docker compose run --rm checkgram run daily-checkin
docker compose up -d
docker compose logs -f checkgram
docker compose down
```

宿主机根目录的 `config.toml` 会挂载到容器工作目录 `/app/config.toml`，与 CLI 默认配置路径一致，因此一次性命令即使命令覆盖服务默认的 `serve` 命令，也会继续使用该配置。如果宿主机缺少 `config.toml`，Compose 会直接报错；请先编辑仓库根目录提供的示例配置。

Compose 服务不暴露端口。容器以非 root 用户运行，根文件系统只读，仅命名卷 `/data` 可写；容器重建或重启不会删除该卷中的会话。默认内存上限为 256 MB，Docker 负责日志轮转。

## 配置参考

仓库根目录的 [`config.toml`](config.toml) 是可直接运行的最小示例。配置文件只描述账号别名、目标 Bot、执行时间和工作流步骤；Telegram `api_id`、`api_hash`、手机号、验证码、2FA 密码和 StringSession 都不写入此文件。

### 完整示例

下面的示例展示了一个“发送命令 → 等待回复 → 必要时点击按钮 → 根据结果结束”的工作流。复制后至少要修改 `target`、`times`、发送文本、按钮文字和回复匹配值。

```toml
[app]
timezone = "Asia/Shanghai"
step_timeout = 30

[[workflows]]
id = "daily-checkin"
account = "primary"
target = "@target_bot"
times = ["08:00", "20:00"]

[[workflows.steps]]
id = "start"
type = "send"
text = "/start"
next = "result"

[[workflows.steps]]
id = "result"
type = "wait"
timeout = 45

[[workflows.steps.cases]]
id = "success"
match = "contains"
value = "签到成功"
next = "success"

[[workflows.steps.cases]]
id = "already-done"
match = "contains"
value = "今日已签到"
next = "success"

[[workflows.steps.cases]]
id = "need-confirm"
match = "contains"
value = "请确认"
next = "confirm"

[[workflows.steps]]
id = "confirm"
type = "click"
text = "确认"
timeout = 30

[[workflows.steps.cases]]
id = "confirmed"
match = "contains"
value = "签到成功"
next = "success"

[[workflows.steps.cases]]
id = "rejected"
match = "contains"
value = "失败"
next = "failure"
```

账号不写入配置。先通过 `auth ACCOUNT_ID` 创建每个本地账号，再增加 workflow 并修改 `account` 即可复用步骤定义：

```toml
[[workflows]]
id = "secondary-checkin"
account = "secondary"
target = "@target_bot"
times = ["09:00"]

[[workflows.steps]]
id = "start"
type = "send"
text = "/start"
next = "result"

[[workflows.steps]]
id = "result"
type = "wait"

[[workflows.steps.cases]]
id = "ok"
match = "contains"
value = "签到成功"
next = "success"
```

### 配置结构

TOML 中的 `[[...]]` 表示数组中的一项，因此每个账号、工作流、步骤和条件都要重复对应的表头。所有字段均区分字符串和数字：例如 `step_timeout = 30` 正确，而 `step_timeout = "30"` 会被拒绝。

| 路径 | 必填字段 | 说明 |
| --- | --- | --- |
| `[app]` | `timezone`、`step_timeout` | 全局运行设置。`timezone` 使用 IANA 时区；`step_timeout` 是未单独设置步骤超时时使用的默认秒数。 |
| `[[workflows]]` | `id`、`account`、`target`、`times`、`steps` | 一个可独立调度或手动执行的工作流。`account` 是本地账号 ID，必须使用安全的文件名字符；`target` 通常填写目标 Bot 的公开用户名。 |
| `[[workflows.steps]]` | `id`、`type` | 按文件顺序执行的步骤。`id` 在当前 workflow 内唯一，分支只能跳到后面的步骤。 |
| `[[workflows.steps.cases]]` | `id`、`match`、`value`、`next` | `wait` 或 `click` 收到事件后的匹配分支。`id` 只需在当前步骤内唯一。 |

### `[app]` 全局设置

- `timezone`：必填的 IANA 时区，例如 `Asia/Shanghai`、`Asia/Tokyo` 或 `UTC`。它同时决定 `times` 的解释方式；不要填写 `CST`、`GMT+8` 这类不明确的缩写。
- `step_timeout`：必填正整数，单位为秒。每个步骤都可以用自己的 `timeout` 覆盖它。这个值只控制单步等待或操作的最长时间，不会改变每轮固定 1 小时的总预算。

调度器只等待严格晚于当前时刻的下一次时间。例如当前本地时间已经是 `08:00`，`times = ["08:00"]` 会安排到第二天 `08:00`，不会立即补跑。进程重启也不会补执行已经错过的时间。

### 账号 ID 与认证

账号 ID 不在 `config.toml` 中声明，而是在认证命令中创建：

```bash
uv run checkgram auth primary --data-dir ./data
uv run checkgram auth secondary --data-dir ./data
```

- ID 是 Checkgram 本地别名，同时决定 `--data-dir/<id>.session` 的文件名；
- 只能使用字母、数字、`.`、`_` 和 `-`，长度为 1–64 个字符，且必须以字母或数字开头；
- `auth` 一次只处理一个账号，不支持 `--all`、`--from-config` 或无参数模式；
- 认证成功后如果已存在同名 session，必须输入完整的 `yes` 明确确认覆盖；其他输入都会取消认证；
- 每个 Telegram 账号使用独立 session，但所有账号共用同一套 `TELEGRAM_API_ID` 与 `TELEGRAM_API_HASH`；
- 认证成功后会显示脱敏的 Telegram username、手机号末两位或 ID 末四位，便于确认本地别名没有绑定错误账号；
- 会话文件由程序保存到 `--data-dir` 下的 `<id>.session`，因此不要把手机号、StringSession 或其他登录信息填到 `config.toml`。

### `[[workflows]]` 工作流设置

```toml
[[workflows]]
id = "daily-checkin"
account = "primary"
target = "@target_bot"
times = ["08:00", "20:00"]
```

- `id`：工作流唯一标识。手动执行时使用 `checkgram run <id>`。
- `account`：要使用的本地账号 ID。它可以先写入 workflow，再单独执行 `auth ACCOUNT_ID` 创建 session。
- `target`：Telegram 目标，通常是公开 Bot 用户名，例如 `@target_bot`。当前实现使用用户账号连接目标，不支持把 BotFather token 或手机号写在这里。
- `times`：至少一个 `HH:MM` 字符串，可以填写多个时间；必须是两位小时和两位分钟，例如 `"08:00"`，不能写 `"8:00"`。重复时间没有实际意义，程序会按时间顺序处理。
- `steps`：至少一个步骤，按 TOML 文件中的出现顺序执行。每个 workflow 的第一步是入口。

### `[[workflows.steps]]` 步骤

每个步骤都需要唯一的 `id` 和 `type`。支持三种类型：

| `type` | 用途 | 字段要求和行为 |
| --- | --- | --- |
| `send` | 向 `target` 发送文本 | 必须有 `text` 和 `next`，不能有 `cases`。发送后立即进入 `next`；返回的消息可供后续 `click` 使用。 |
| `wait` | 等待目标产生回复或事件 | 必须有至少一个 `cases`，不需要 `text`。会匹配新的消息、编辑后的消息或 callback answer。 |
| `click` | 点击上一步回复中的按钮 | 必须有 `text` 和至少一个 `cases`。`text` 必须与上一条回复中的一个可见按钮文字完全相同；点击后继续等待并匹配 `cases`。 |

通用字段：

- `timeout`：可选正整数，单位为秒，覆盖 `[app].step_timeout`。例如 `timeout = 45` 表示该步骤最多等待或执行 45 秒；实际仍受当前轮剩余预算限制。
- `next`：`send` 使用的后继步骤。也可以指向终态 `success` 或 `failure`。对于 `wait` 和 `click`，后继目标写在各自的 `cases.next` 中。
- `text`：`send` 是要发送的文本；`click` 是要点击的按钮可见文字。点击匹配区分整个按钮文字，不是模糊包含匹配。

步骤的跳转规则是有意限制的：目标只能是后面定义的步骤、`success` 或 `failure`。不允许跳回前面的步骤，也不允许形成循环；每一步都必须能通过 `next` 或某个 case 离开。这样可以在离线校验时发现拼写错误和无法结束的流程。

建议以 `send` 作为工作流第一步，让 Checkgram 先建立目标会话并获得后续 `click` 所需的回复上下文。

### `[[workflows.steps.cases]]` 条件分支

```toml
[[workflows.steps.cases]]
id = "success"
match = "contains"
value = "签到成功"
next = "success"
```

- `id`：当前步骤内的条件名称，只用于识别和日志，不参与匹配。
- `match`：只能是 `exact` 或 `contains`。
  - `exact`：收到的文本与 `value` 完全相同。
  - `contains`：收到的文本包含 `value`。
- `value`：非空匹配文本。匹配前会去除实际文本和配置值的首尾空白，并忽略大小写；不会执行正则表达式匹配。
- `next`：匹配成功后的后继步骤，或终态 `success` / `failure`。

多个 case 按文件顺序依次检查，匹配到第一个就跳转。因此更具体的条件应放在更宽泛的 `contains` 条件前面。例如“签到失败”应放在只匹配“签到”的条件前面。`click` 步骤收到 callback answer 时，待匹配文本是 callback data；收到普通消息时，待匹配文本是消息正文。

### 按操作类型填写

只发送后立即结束：

```toml
[[workflows.steps]]
id = "send-command"
type = "send"
text = "/start"
next = "success"
```

等待成功或失败回复：

```toml
[[workflows.steps]]
id = "result"
type = "wait"
timeout = 45

[[workflows.steps.cases]]
id = "ok"
match = "contains"
value = "成功"
next = "success"

[[workflows.steps.cases]]
id = "failed"
match = "contains"
value = "失败"
next = "failure"
```

等待回复后点击按钮，再等待点击结果：

```toml
[[workflows.steps]]
id = "question"
type = "wait"

[[workflows.steps.cases]]
id = "has-confirm-button"
match = "contains"
value = "请选择"
next = "confirm"

[[workflows.steps]]
id = "confirm"
type = "click"
text = "确认"

[[workflows.steps.cases]]
id = "done"
match = "contains"
value = "完成"
next = "success"
```

`click` 只接受 callback button 和普通文字 reply keyboard。URL、WebApp、支付、验证码、请求手机号和请求位置按钮会被拒绝；按钮文字缺失或同一回复中出现多个同名按钮也会失败。

### 修改和校验流程

1. 复制或编辑仓库根目录的 `config.toml`，修改 workflow 的 `account`、`target`、`times` 和步骤内容；`account` 只填写本地账号 ID，不添加 `[[accounts]]`。
2. 运行离线校验：

   ```bash
   uv run checkgram validate --config config.toml
   ```

   `validate` 不读取 Telegram 凭据，也不会连接 Telegram；它会检查 TOML 语法、必填字段、类型、唯一 ID、账号引用格式、时间格式和工作流跳转。
3. 为每个账号分别认证，例如：

   ```bash
   uv run checkgram auth primary --data-dir ./data
   ```

   如果希望在运行前同时检查 session，可以执行 `uv run checkgram validate --config config.toml --data-dir ./data`。缺少 session 时，命令会给出对应的单账号 `auth` 修复命令。
4. 先用 `run WORKFLOW_ID` 手动执行一次，确认目标、按钮文字和回复匹配值正确，再启动 `serve`。`run` 和 `serve` 也会在建立连接或等待调度前检查所需 session。

配置在进程启动时读取一次。修改 `config.toml` 后，必须重新执行 `run` 或重启 `serve`；运行中的进程不会自动重新加载。

`validate` 失败时，错误会带出配置路径，例如 `workflows[0].steps[1].cases[0].next`，可以根据路径定位对应的表项。常见错误包括：把 `08:00` 写成 `8:00`、使用不安全的 `account` ID、把步骤跳转到前面的步骤、给 `wait`/`click` 忘记添加 case，或把 `send` 步骤错误地写成带 `cases`。

## 命令参考

| 命令 | 用途 |
| --- | --- |
| `validate` | 只读取 TOML 并离线校验，不连接 Telegram |
| `auth ACCOUNT_ID` | 交互创建或重新认证一个本地账号并保存独立 StringSession |
| `run WORKFLOW_ID` | 立即执行一个工作流；不修改下一次计划时间 |
| `serve` | 持有服务锁，等待并串行执行所有计划工作流 |

`validate`、`run` 和 `serve` 支持 `--config PATH`；`validate`、`auth`、`run` 和 `serve` 支持 `--data-dir PATH`。`auth` 不读取配置文件；其他命令在进程启动时加载一次配置。成功命令返回退出码 `0`，配置、认证、锁或工作流失败返回非零退出码。

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
