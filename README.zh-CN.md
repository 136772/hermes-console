# Hermes Console

[English](README.md) | **简体中文**

> 给 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 做的网页管理控制台：监控、对话、配置、成本、告警、升级，一个面板全搞定。

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.11+-green)
![Docker](https://img.shields.io/badge/docker-ready-2496ed)
![CI](https://github.com/136772/hermes-console/actions/workflows/ci.yml/badge.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

纯 Flask + 原生 Canvas，**无前端构建、无第三方图表库、无外部监控依赖**。
3 个 pip 依赖，56 个 API，14 个视图，12 种告警渠道，零 node_modules。
29 项冒烟测试 + GitHub Actions CI。

---

所有 14 个视图（包括工作区编辑器）都做了移动端响应式，390 px 手机可用。

## 截图

| 总览 | 对话 |
|:---:|:---:|
| ![overview](docs/screenshots/01-overview.png) | ![chat](docs/screenshots/02-chat.png) |

| 成本 | 配置 |
|:---:|:---:|
| ![cost](docs/screenshots/03-cost.png) | ![config](docs/screenshots/04-config.png) |

| 工作区 | MCP 管理 |
|:---:|:---:|
| ![workspace](docs/screenshots/05-workspace.png) | ![mcp](docs/screenshots/06-mcp.png) |

| 多会话对话 | CodeMirror 编辑器 |
|:---:|:---:|
| ![chat-sessions](docs/screenshots/08-chat-sessions.png) | ![codemirror](docs/screenshots/09-workspace-codemirror.png) |

| 智能体编排 | 移动端（智能体） |
|:---:|:---:|
| ![agents](docs/screenshots/10-agents.png) | ![mobile-agents](docs/screenshots/10b-mobile-agents.png) |

| 移动端（抽屉） | 移动端（工作区） |
|:---:|:---:|
| ![mobile-drawer](docs/screenshots/07b-mobile-drawer.png) | ![mobile-workspace](docs/screenshots/07c-mobile-workspace.png) |

---

## Quick Start

**下载后跑安装脚本（推荐）**：

```bash
git clone https://github.com/136772/hermes-console.git
cd hermes-console
./install.sh
```

脚本会自动识别系统、检测国内网络配镜像源、交互式问你参数（全部有默认值，回车即可）。
也支持纯参数模式：`./install.sh --action install --mode docker --yes`

想一行启动的话：

```bash
curl -fsSL https://raw.githubusercontent.com/136772/hermes-console/main/install.sh | bash
```

### install.sh 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--action` | `install` 只装工作台 / **`hermes+dash` 工作台+Hermes 一起装** / `update` 只更新工作台 | 交互式问 |
| `--mode` | `docker` / `host` 宿主机 / `systemd` 宿主机+开机自启 | 交互式问 |
| `--hermes-dir PATH` | **宿主机上**的 Hermes 数据目录（容器内统一挂到 `/opt/data`） | `/opt/hermes/data` |
| `--port PORT` | 工作台端口 | `8080` |
| `--uid UID` | 运行用户 UID（建议和 Hermes 对齐） | `1001` |
| `--quota MB` | 配额，用于算百分比和告警 | `10240` |
| `--container NAME` | Hermes 容器名 | `hermes` |
| `--danger-token` | 危险动作令牌（重启/升级要填对） | **自动生成** |
| `--budget-daily` / `--budget-monthly` | 日/月预算（元） | `0`（不限） |
| `--tz` | 时区 | `Asia/Shanghai` |
| `--repo OWNER/REPO` | 自更新比对用的仓库 | 空 |
| `--cn-mirror` / `--no-cn-mirror` | 强制配 / 不配国内源 | 自动检测 |
| `-y` / `--yes` | 跳过所有确认 | 关 |
| `--help` | 看帮助 | — |

**常用组合**：

```bash
./install.sh                                          # 交互式（推荐第一次用）
./install.sh --action install --mode docker --yes     # Docker 模式静默装工作台
./install.sh --action hermes+dash --mode docker       # 连 Hermes 一起装
./install.sh --mode host --hermes-dir /data/hermes --port 9000
./install.sh --action update                          # 只更新工作台
```

> `--action hermes+dash` 是给**全新机器**准备的：Hermes 本体 + 工作台一步到位。
> 已经跑着 Hermes 的机器用 `--action install` 就行，脚本只会加工作台，不碰你现有的 Hermes。

**手动部署**：

```bash
# 1. 拉代码
git clone https://github.com/136772/hermes-console.git
cd hermes-console

# 2. 装依赖（就 3 个）
pip install -r requirements.txt

# 3. 设环境变量（按你的实际路径改）
export HERMES_DIR=/path/to/hermes/data    # Hermes 数据目录
export HERMES_MODE=docker                  # 或 local
export HERMES_CONTAINER=hermes
export QUOTA_MB=10240

# 4. 跑起来
python app.py
# 访问 http://localhost:8080
# 首次登录密码在 $HERMES_DIR/DASHBOARD_PASSWORD.txt
```

> Docker 一行启动：`docker compose up -d --build`

---

## 一、14 个视图

一共 **14 个视图**：

| 页 | 内容 | 为什么值得盯 |
|---|---|---|
| **总览** | 6 张状态卡（运行状态 / 配额用量 / 记忆文件 / 活跃技能 / 24h 错误 / 系统负载）+ 60 分钟趋势图 + 系统资源条 + 最近错误样本 + **三级活体探测** | 一眼判断"今天它正不正常"。探测分三级：进程可达 → 数据可写 → 模型连通，详见[活体探测为什么要分三级](#活体探测为什么要分三级) |
| **对话** | 网页里直接给 Hermes 下指令，带耗时显示和 4 个快捷指令。**流式模式**逐 token 返回 + 工具调用可视化卡片。**多会话**：新建 / 切换 / 重命名 / 删除，历史落盘，重开页面自动恢复 | 不用 SSH 进 NAS 也能使唤它 |
| **配置** | 五个子页：配置文件编辑器 / MCP 服务器 / Provider 与 Key / **对话接口** / 系统动作 | **以后再也不用进后台改东西** |
| **成本** | 今日 / 7 天 / 30 天 token 与花费，按模型分解，30 天柱状图；预算与告警渠道管理 | 监控告诉你它坏没坏，成本告诉你**值不值得继续养** |
| **技能** | 列出所有技能及 `description`，可禁用、恢复、归档、从 Hub 安装 | 技能膨胀 / 被塞了陌生技能，一眼看见 |
| **记忆** | 列出记忆文件与体积 | 记忆膨胀是最隐蔽的退化源 |
| **任务** | 定时任务启停（改名 `.disabled`，不删除） | 攻击者常在 cron 留后门 |
| **体检** | 一键跑 `health-check.sh` / `security-check.sh`，原文输出 | 复用你已经有的脚本，不重复造轮子 |
| **记录** | 变更审计：谁在什么时候把什么从哪改到哪 | 网页改配置的底气来源 |
| **仪表盘** | 整页嵌入 Hermes 官方 Web 仪表盘（FastAPI + React SPA，19 个页面） | 会话/文件/日志/分析/多身份/IM 渠道一次全有，随上游更新自动变强 |
| **功能** | Hermes 命令台：doctor / update / memory / curator / session / skills / mcp / tools / model / profile，白名单放行 | Hermes CLI 能干的，在网页里点点就行 |
| **系统** | 版本号 + 上游版本比对、**一键升级 Hermes / 升级工作台（git pull）**、跑 doctor、修改登录密码 | 不用再手敲 git 和 update |
| **工作区** | 浏览整个 Hermes 数据目录的文件树，读 / 写任意文本文件（自动备份 + 语法校验 + 越界防护） | 看见并改全貌，而不只是白名单里的配置 |
| **智能体** | 定义智能体（id / 名称 / 角色 / 人设 / 模型）与团队（成员 + 编排模式），三种编排：`sequential` 顺序 · `pipeline` 流水线（上游产出自动注入下一位上下文）· `parallel` 并行；点「运行团队」经 SSE 逐步展示每个智能体的输出与耗时 | 一个任务，一组专家接力 |

---

## 二、成本与告警

监控解决"它有没有坏"，成本解决"**养它值不值**"——后者才是你真正会天天看的东西。

### 成本统计

今日 / 近 7 天 / 近 30 天的 token 与花费，按模型分解，加最近 30 天的每日柱状图。

数据来源两条路：

1. **自动扫** `logs/*.log`、`sessions/*.jsonl` 里的 `usage` 字段（兼容 `prompt_tokens` / `input_tokens` 等写法）
2. **主动上报** `POST /api/cost/record` —— 当 Hermes 日志里没有 usage 时用这个

**没有数据就明说没有，绝不编数字。** 采集不到时页面会直接告诉你，并提示怎么接上报。

### 预算与告警

`BUDGET_DAILY` / `BUDGET_MONTHLY` 设预算（元），超 80% 预警、超 100% 告警。
后台巡检线程每 `ALERT_INTERVAL` 秒跑一次，**异常才推**，且同类告警默认 6 小时内只发一次
——不然"配额 91%"能每分钟给你发一条，两小时你就把它关了。

四类告警：进程停止 / 配额 ≥90% / 24h 错误 >50 / 预算超 80%。

推送渠道（**全部只用标准库，零第三方依赖；新增渠道 = 后端加一段 + schema 加字段，前端零改动**）：

| 类型 | 说明 |
|---|---|
| 通用 Webhook | POST JSON，什么都能接 |
| 企业微信机器人 | 群机器人 |
| 钉钉机器人 | 群机器人 |
| Telegram Bot | 填 Bot Token + Chat ID |
| 邮件 SMTP | SSL / STARTTLS |
| 飞书 / Lark | 自定义机器人，支持「加签」 |
| Slack | Incoming Webhook |
| Bark | iOS 推送（自建 / 官方服务器） |
| PushPlus | 推送加（支持群组 / 主题） |
| Server 酱 | SCT Key |
| Gotify | 自建推送 |
| 自定义 Webhook | 可配 GET/POST + JSON 模板（`{title}`/`{text}` 占位），兜底未来所有渠道 |

> 工作台「成本」页的「告警渠道」子页可**逐条增删改、启用/禁用、一键测试**。
> 所有凭证页面脱敏显示，配置文件权限 600，**你不动它就不会被覆盖**（编辑时即便改了名字，底层真实密钥也按下标对齐保留，不会被圆点冲掉）。
> 告警发出与否都会记录在「告警记录」页——发没发出去能查，不用猜。

### 对话接口（跟 Hermes 聊天的 API 也在控制台配）

「配置 → 对话接口」把 Hermes 的模型 API 一站式配好，**以后不用 SSH 进后台改 `config.yaml` / `.env`**：

- 选 Provider 预设（DeepSeek / Kimi / 通义 / z.ai / OpenRouter）或「自定义 OpenAI 兼容接口」
- 填默认模型（带 provider 前缀，如 `deepseek/deepseek-chat`）、API Key、自定义 Base URL
- 保存后写入 `config.yaml` 的 `model` 块 + `.env` 的密钥 / `OPENAI_BASE_URL`，需重启或会话内 `/reload` 生效

> 模型名必须带前缀，否则工具调用会静默失效——这是 Hermes 的老坑，页面已置灰提示。

### 亮色主题

右上角 `◑` 切换，记住选择，也跟随系统偏好。Canvas 图表的配色会跟着主题走
（这点容易漏：很多面板切到亮色后图表就看不见了）。

---

## 三、配置中心：从"看"到"改"

这是从监控面板升级成**控制台**的部分。目标是一个：**以后再也不用 SSH 进后台**。

### 配置文件编辑器

左侧是可编辑文件（白名单自动发现），右侧直接改，`Ctrl+S` 之外点保存。
能改：`config.yaml`、`.env`、`SOUL.md`、`AGENTS.md`、`memories/*.md`、`skills/*/SKILL.md`、`cron/*`。

- **保存即备份** —— 每次写入前自动存一份到 `.dashboard/backups/`，每个文件留 30 份
- **一键回滚** —— 「备份历史」里点回滚，且**回滚前会先把当前状态也存一份**，
  所以回滚本身也是可逆的
- **差异对比** —— 保存后直接显示 unified diff
- **YAML 语法校验** —— 校验不通过**绝不落盘**。用 `ruamel.yaml` 保序保注释地改，
  不会把你 config.yaml 里的中文注释洗掉

### MCP 服务器管理

增删改 MCP 服务器，页面上填名称/命令/参数/环境变量，不用手写 YAML。
两个内置的坑提示：

- 顶层键必须是 `mcp_servers:`。写成 `mcp:` 的话**不会报错，只会静默不生效** ——
  页面检测到这种情况会直接给你告警
- 改完可以点「热加载」触发 `hermes reload-mcp`，**不用重启**

### Provider / Key 管理

预设了 5 个国内可用 Provider（DeepSeek / Kimi / 通义 / z.ai / OpenRouter），
点一下写入 `.env`，并把每个 provider 的坑写在卡片上
（比如 DeepSeek 的模型名必须带 `deepseek/` 前缀，否则工具调用静默失效）。

`.env` 页面里 **API Key 默认脱敏显示**（`sk-a••••••••1234`），
更关键的是：**你不动它，保存时它就保持原值** —— 不会因为打开页面点了一次保存，
就把所有密钥覆盖成圆点。

### 系统动作

重启 / 拉镜像升级 / 热加载。全部记审计，全部二次确认，
且可用 `DASH_DANGER_TOKEN` 加一道令牌校验。

### 四道护栏（没有这些我就不敢做网页改配置）

| 护栏 | 实现 | 挡住什么 |
|---|---|---|
| 白名单 + 防穿越 | 正则白名单 + `realpath` 前缀校验 + 拒绝 `..` 和绝对路径 | 改到 `/etc/passwd`、改到 NAS 系统文件 |
| 语法校验先行 | YAML/JSON 解析不过**不落盘** | 一次手滑让 Hermes 起不来 |
| 写前自动备份 | 每文件 30 份，同秒内多次修改自动加序号 | 改崩了回不去 |
| 全量审计 | 每次写入记时间/动作/明细/来源 IP | 事后说不清是谁改的 |

另外还有：写锁防并发覆盖、原子写（临时文件 + rename）、单文件 512KB 上限、
危险操作令牌、只读总闸 `DASH_READ_ONLY=1`。

### 活体探测为什么要分三级

这是整个面板最容易被忽略、也最容易骗人的地方：

- **L1 进程可达**：能执行 `hermes --version` 吗 —— 证明程序没崩
- **L2 数据可写**：记忆目录能落盘吗 —— **写不进去 = 你所有调教都白费**，这是最阴的一类故障
- **L3 模型连通**：真跑一轮 —— 只有这个能证明"它能干活"，但**烧 token**

默认点按钮只跑 L1+L2（零成本）。**按住 Shift 点**才跑 L3。别把 L3 挂到定时任务上，
那等于每分钟给模型厂商送钱。

---

## 四、部署：三种方式，按需要选

### 方式 A：装在 NAS 宿主机上（推荐）

最简单，也最好用 —— 直接用宿主机的 `docker` 命令，**不需要挂 docker.sock**。

```bash
# 飞牛上开 SSH，进到你放文件的目录
cd /your/path/hermes-console
pip3 install flask          # 或 python3 -m pip install flask

export HERMES_DIR=/path/to/hermes/data
export HERMES_MODE=docker          # 用宿主机 docker 命令去 exec Hermes 容器
export HERMES_CONTAINER=hermes
export QUOTA_MB=10240
nohup python3 app.py > dashboard.log 2>&1 &
```

访问 `http://<NAS的IP>:8080`。

### 方式 B：跑在容器里

```bash
docker compose up -d --build
```

> **免本地构建**：配好 Docker Hub 自动构建后，可直接拉多架构预构建镜像（amd64 / arm64），
> 不用在 NAS 上现场 `build`：
> ```bash
> docker compose pull          # 拉 136772/hermes-console:latest（compose 已配好）
> docker compose up -d
> # 想锁版本：docker compose pull hermes-console && docker compose up -d
> #   镜像 tag 也可写成 136772/hermes-console:v1.6.0
> ```
> Caddy 反代已内置，`docker compose up -d` 会同时起 `caddy`（发布 8080 + 透传 WebSocket）。

需要网页对话时，把 `docker-compose.yml` 里 docker.sock 那两行注释打开
（含 `group_add`，GID 用 `getent group docker | cut -d: -f3` 查）。

> **Caddy 前置反代（已内置）**：`docker compose up -d` 会同时起 `caddy` 服务，由它对外发布 `8080`、
> 并把 WebSocket 升级请求透传到官方后端 `HERMES_API`（Flask 是 WSGI，处理不了 WS）。
> 工作台容器本身改为只监听内部 `8081`，不再直接对公网暴露。访问地址不变（`http://<NAS的IP>:8080`）。
> 想换 nginx 或自建反代也行：只要让反代对 `/proxy/*` 的 `Connection: Upgrade` 请求直连 `HERMES_API` 即可。

### 方式 C：纯只读监控（最安全）

不挂 docker.sock、不装 docker CLI，只保留总览 / 技能 / 记忆 / 体检四个页。
对话和 L1 探测会显示"未接入"，**其余功能完全正常**。
如果你只需要"它别悄悄坏掉"，选这个。

---

## 五、开机自启与进程守护（必做）

前几版靠 `nohup` 起的进程，**NAS 重启即失联，崩了也不会自起**——你以为在监控，其实监控早挂了。这一版给了两只"看门狗"：

**方式 A（宿主机）二选一：**
```bash
# 1) 看门狗脚本（自带 30s 保活），后台常驻
/your/path/hermes-console/start-dash.sh --daemon

# 开机自启：crontab -e 加一行（fnos 计划任务也能填这条）
@reboot /your/path/hermes-console/start-dash.sh --daemon
```
```bash
# 2) 或 systemd（FNOS 是 Debian 系，一般可用）
cp /your/path/hermes-console/hermes-console.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now hermes-console
```
> `start-dash.sh` 会读 `.env` 里的环境变量、检查依赖、写 pidfile；`service` 里路径按你实际放的位置改。

**方式 B（容器）天然有 `restart: unless-stopped`** —— compose 已写，docker 会自动拉起，无需额外操作。唯一注意：`group_add: ["999"]` 要填对宿主机 docker 组 GID（`getent group docker | cut -d: -f3`），否则容器内用户访问不到 `docker.sock`，网页对话会失败。

**方式 C（只读容器）** 同上，靠 compose 的 `restart` 即可。

---

## 六、国内镜像源（pip / docker / git / npm）

国内网络拉官方镜像和 PyPI 很容易超时。一次性配好四类源，后面省心：

| 工具 | 镜像 | 配置方式 |
|---|---|---|
| **pip** | 清华 `pypi.tuna.tsinghua.edu.cn` | `/etc/pip.conf` 写 `index-url`；或 `pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple` |
| **docker** | `docker.m.daocloud.io` / `hub-mirror.c.163.com` / `docker.1panel.top` | 写 `/etc/docker/daemon.json` 的 `registry-mirrors`（见下），重启 dockerd 生效 |
| **git** | `ghproxy.net` 代理 github | `git config --global url."https://ghproxy.net/https://github.com/".insteadOf "https://github.com/"` |
| **npm** | 淘宝 `registry.npmmirror.com` | `npm config set registry https://registry.npmmirror.com`（装 MCP 服务器用 npx 时需要） |

`/etc/docker/daemon.json` 示例（飞牛若有「镜像加速」UI，直接在那填更省事）：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://hub-mirror.c.163.com",
    "https://docker.1panel.top",
    "https://hub.rat.dev"
  ]
}
```

> 工作台镜像构建时已经在 `pip install` 加了清华源（`Dockerfile` 里），所以自己拉包也不卡。
> 嫌一条条敲麻烦，直接跑仓库里的 **`fnos-setup.sh`**，四类源 + hermes 用户 + 数据目录一次配齐。

---

## 七、Hermes 和工作台，要在一个用户里吗？怎么连？

**先给结论：不强制同一用户，但我强烈建议工作台也以 `hermes`（UID 1001）身份跑。**

### 它们到底靠什么连起来

就两根线，画出来很简单：

```
                    ┌──────────────────── 飞牛 NAS 宿主机 ───────────────────┐
                    │                                                        │
   Hermes 容器      │   数据目录（唯一真相源）                                │   工作台容器
   (user 1001)      │   /path/to/hermes/data  ◀──共用──▶  /opt/data        │   (user 1001)
   ┌──────────┐     │        │   config.yaml / SOUL.md / memories            │   ┌──────────┐
   │ hermes   │     │        │   skills / cron / logs / sessions            │   │ dashboard│
   │ gateway  │─────┼──(B)──▶│  docker exec hermes ...                      │   │ :8080    │
   └──────────┘     │   对话/探测时工作台用 docker exec 去敲它                │   └──────────┘
                    └────────────────────────────────────────────────────────┘
```

- **线 (A) 共用数据目录**：Hermes 和工作台挂的是**同一份**数据目录（如 `/path/to/hermes/data`）。
  这是它们真正的连接点——所有配置、记忆、技能、定时任务都在这里，两边读写同一份。
- **线 (B) 运行时对话**：你要网页里给 Hermes 下指令，工作台就 `docker exec hermes hermes run "..."`
  （`HERMES_MODE=docker`）。这让工作台不用在宿主机装 Hermes CLI，直接复用正在跑的容器。

### 为什么建议工作台也用 1001 这个用户

| 如果不对齐用户（比如都跑 root） | 对齐成 hermes/1001 |
|---|---|
| 工作台写的文件变成 root 所有，Hermes 容器（1001）可能读不到/写不进 | 文件归属一致，两边随便读写 |
| 10G 配额是按 **UID** 计的，**root 写入不算进 hermes 配额**，工作台能把磁盘撑爆而你不报警 | 工作台写入自动计入 hermes 的 10G，撑满了你会看到配额告警 |
| 权限混乱，回滚/审计时对不上是谁改的 | 归属清楚 |

所以 `docker-compose.yml`（工作台）里已经写了 `user: "1001:1001"`，和 Hermes 的 compose 对齐。

### docker.sock 那条线（对话必须，但有代价）

网页对话要 `docker exec`，工作台就得碰 `docker.sock`。`docker.sock` 等于宿主机 root，
所以：

- 工作台容器里挂了宿主机 **docker 组**（compose 里 `group_add` 填 GID，用 `getent group docker | cut -d: -f3` 查）
- 仍然用 `no-new-privileges:true` 兜底，且只在信任的局域网里开

如果你**坚决不要 docker.sock**：把 `HERMES_MODE` 设成 `local`，并在宿主机也装一份 Hermes CLI，
对话就走本地命令（前提是宿主机有 `hermes` 可执行）。但更省事的做法通常是：**Hermes 本来就跑容器，
那就接受 docker.sock**，只要面板不暴露公网就行（详见[第十一节](#十一安全权衡这部分请务必读)）。

### 一键接好

仓库里的 `fnos-setup.sh` 会把上面这些都做掉：配国内源、建 hermes 用户、建并修正数据目录归属、
查好 docker 组 GID 提示你填进 `group_add`。跑完按它结尾的 5 步起服务即可。

---

## 八、环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HERMES_DIR` | `/opt/data` | Hermes 数据目录。**容器内**是挂载点（固定 `/opt/data`）；**宿主机部署**时填真实路径，`install.sh --hermes-dir` 默认 `/opt/hermes/data` |
| `HERMES_MODE` | `auto` | `docker` / `local` / `auto`；`auto` 会扫 `docker ps` 里名字带 hermes 的容器 |
| `HERMES_CONTAINER` | `hermes` | docker 模式下的容器名 |
| `QUOTA_MB` | `10240` | 你给 Hermes 设的配额，用于算百分比和告警阈值 |
| `CHAT_TIMEOUT` | `180` | 对话超时秒数；复杂任务调到 300 |
| `SCRIPT_DIR` | app 所在目录 | 巡检脚本目录 |
| `PORT` | `8080` | 监听端口 |
| **`DASH_READ_ONLY`** | `0` | 设 `1` = 工作台彻底只读，配置中心只能看不能改 |
| **`DASH_DANGER_TOKEN`** | 空 | 重启/升级必须填对。**强烈建议设置**，否则任何能打开页面的人都能重启你的 agent |
| `COMPOSE_DIR` | 空 | Hermes 的 compose 目录，填了才能用「升级」按钮 |
| **`BUDGET_DAILY`** | `0` | 每日预算（元），0 = 不限制。超 80% 预警 / 100% 告警 |
| **`BUDGET_MONTHLY`** | `0` | 每月预算（元） |
| `ALERT_INTERVAL` | `600` | 告警巡检间隔（秒） |
| **`DASH_AUTH`** | `1` | 登录鉴权开关。`0` = 关闭（仅限隔离内网/调试）。部署后首个密码写入 `HERMES_DIR/DASHBOARD_PASSWORD.txt` |
| `SESSION_HOURS` | `24` | 登录会话有效期（小时） |
| `DASH_SECURE_COOKIE` | `0` | 走 HTTPS 反代设 `1`，Cookie 仅加密通道 |
| `HERMES_API` | `http://127.0.0.1:9119` | Hermes 官方仪表盘后端地址。Docker 模式用 `http://172.17.0.1:9119` 或 `http://hermes:9119` |
| `HERMES_API_TOKEN` | 空 | 官方后端认证 token（可选，官方后端开启认证时填） |
| `PROXY_TIMEOUT` | `300` | 代理转发超时（秒） |
| `UPDATE_REPO` | 空 | 工作台自更新比对用的远端仓库 `owner/repo`；容器内部署无需配，改用 compose pull |

---

## 九、可持续升级（不用再手敲 git）

工作台把"升级"也做进了页面（顶部「系统」页），分两种：

1. **升级 Hermes 本体** —— 点「升级 Hermes」，后台执行 `hermes update`（docker 模式是 `docker exec hermes hermes update`）。
   等价官方 `hermes update`，修 bug 的第一手段。

2. **升级工作台自身** —— 点「升级工作台（git pull）」，后台 `git pull --ff-only` 拉最新代码，
   成功后会**自动重启进程**加载新代码（靠 `start-dash.sh` 看门狗 / systemd / 容器编排拉起）。
   - 方式 A（宿主机）：以 **git 仓库**方式部署即可 `git pull` 自更新。
   - 方式 B（容器）：容器内部署请用 `docker compose pull && docker compose up -d` 拉新镜像，
     或把 `UPDATE_REPO` 配上后在页面比对上游版本号。

> 升级前建议先点「运行 hermes doctor」自检一遍；所有升级动作都记进变更审计。

---

## 十、官方仪表盘嵌入（代理模式）

工作台新增「仪表盘」页，**整页嵌入 Hermes 官方 Web 仪表盘**（FastAPI + React SPA，19 个页面）——会话浏览、文件管理、实时日志、用量分析、多身份 Profile、IM 渠道、Cron 蓝图编排、技能内容编辑等，一次全有。

### 前提：启动官方后端

```bash
# 在 Hermes 环境里启动官方仪表盘后端（默认 :9119）
hermes dashboard
# 或指定端口
hermes dashboard --port 9119
```

### 网络配置

| 部署方式 | `HERMES_API` 值 | 说明 |
|---|---|---|
| 宿主机直跑 | `http://127.0.0.1:9119` | 最简单 |
| Docker（工作台也是容器） | `http://172.17.0.1:9119` | 走 docker0 网桥访问宿主机 |
| Docker（共享 network） | `http://hermes:9119` | 工作台和 Hermes 放同一个 docker network |

> 代理层自动继承工作台的登录鉴权——未登录访问 `/proxy/*` 的**普通 HTTP** 返回 401，不会把官方后端裸暴露。
> 但 WebSocket（官方 dashboard 的实时聊天 / 终端）是 **WebSocket 协议**，Flask 是 WSGI 处理不了升级握手，
> 因此由**前置的 Caddy 反代**直接终结 WS 并连到官方后端 `HERMES_API`；其鉴权沿用官方后端自身的 `ws-ticket`
>（iframe 内先走 HTTP 拿 ticket，再开 WS）。详见下方「Docker 部署：Caddy 前置反代」。

---

## 十一、安全权衡（这部分请务必读）

工作台默认**只读**：所有采集都是 `du` / `find` / 读 `/proc`。
但一旦你要用配置中心，就有三处例外，**都是你主动点按钮才会发生**：

1. **网页对话** —— 等价于你在终端敲 `hermes run "..."`。
   Hermes 能干的事，网页里也能干。**所以这个面板绝不能暴露到公网**，
   只在局域网 / Tailscale / 飞牛反代 + 强认证后面用。

2. **`/opt/data` 必须改成 `rw` 挂载** —— 这是配置中心的硬性前提。
   补偿措施（见[四道护栏](#四道护栏没有这些我就不敢做网页改配置)）已经把风险压到最低，但**挂载本身确实变宽了**。
   如果你只需要监控，**保持 `:ro` 并把 `DASH_READ_ONLY` 设成 1**，配置中心会显示"只读模式"。
   注意：备份和审计日志写在 `/opt/data/.dashboard/` 下，**会占 Hermes 的 10G 配额**，
   单个文件留 30 份，实测几百 KB 量级，可忽略。

3. **docker.sock**（仅方式 B）—— 这是**容器逃逸面**：拿到 socket 等于拿到宿主机 root。
   挂载前先问自己：面板被攻破的后果我接受吗？不接受就用方式 A 或 C。

一句话原则：**面板的权限 = Hermes 的权限**。别给它比 Hermes 更高的权限，
也别把它放在比 Hermes 更暴露的位置。

再补一条实践建议：**给 `DASH_DANGER_TOKEN` 设一个长随机串**。
没有它，页面上的「重启 Hermes」对任何能打开页面的人都是可点的 —— 包括你误点的自己。

### 11.1 登录鉴权（默认开启，安全优先）

工作台现在**默认需要登录**，而且是「单密码、无用户名」的设计：

- 部署后第一个密码**随机生成并写入 `HERMES_DIR/DASHBOARD_PASSWORD.txt`**，启动日志也会提示。
  打开页面用这个密码登录，**首次登录强制修改密码**（改完明文文件自动删除）。
- 密码用 **PBKDF2-HMAC-SHA256（20 万轮）+ 随机盐**存储，磁盘上只有哈希，没有明文。
- 登录态是 **Flask 签名 session**（Cookie 仅 httpOnly），`secret_key` 持久化在 `.dashboard/secret_key`，
  所以**重启 / 重建容器后登录态依然有效**，不会被踢下线。
- **失败锁定**：同一来源 15 分钟内 5 次密码错误，锁定 15 分钟，防爆破。
- 改密码在「系统 → 登录与账户 → 修改登录密码」里做；也可 `rm .dashboard/auth.json` 让下次访问重新生成初始密码（运维兜底）。
- 完全隔离的内网想关掉鉴权：`DASH_AUTH=0`。**但公网/反代场景务必保持开启，并叠一层 HTTPS。**

> 即便有登录鉴权，第 4 节开头那句话依然成立：**面板的权限 = Hermes 的权限**。
> 鉴权只是第一道门，不要把面板裸奔到公网。

---

## 十二、告警阈值（改代码里的这几行即可）

在 `static/app.js` 的 `renderOverview()`：

| 指标 | 当前阈值 | 建议 |
|---|---|---|
| 配额用量 | ≥80% 黄 / ≥90% 红 | 10G 配额下，8G 就该清理了 |
| 记忆文件数 | >80 个黄 | 记忆膨胀比技能膨胀更危险 |
| 活跃技能数 | >60 个黄 | 有 Curator 的话交给它自动归档 |
| 24h 错误 | >5 黄 / >50 红 | 关键看错误"类型"是否重复 |
| 系统负载 | ≥90% 黄 | N150 四核，长期 >3 就该查 |

**别把阈值调松来消除告警** —— 那是把温度计砸了，不是退烧了。

---

## 十三、四个"反直觉"设计

1. **进程检测不用 `pgrep -f hermes`**
   任何命令行里带 "hermes" 字样的进程都会被算进去（本工作台自己就叫 hermes-console），
   结果是"明明没启动却显示运行中"。这里改成扫 `/proc/*/cmdline` 判断 argv[0]，
   只有真正的 hermes 主程序才算数。

2. **health-check.sh 健康时零输出**
   这是为 cron 设计的 —— 每天顺利的时候不该给你发一封空邮件。
   所以面板里跑完如果是空的，别慌，那就是"一切正常"。

3. **告警"全失败不冷却"**
   早期版本里，只要广播过一次就标记冷却，结果 webhook 地址配错时，第一次失败后
   6 小时内不再重试 —— 你以为它正常，其实它从没发出去过。现在改成：**至少有一个渠道
   发出成功才记冷却**；全失败就一直重试，直到你修好渠道为止。

4. **邮件告警收件人缺省是发件人自己**
   自用的告警通常是"发到我自己的邮箱"，所以 `to` 不填时自动用 `user`。
   要发给别人，在告警渠道里填 `to` 字段即可。

---

## 十四、文件清单

```
hermes-console/
├── app.py                  # Flask 后端：采集 + 登录守卫 + 56 个 API（1564 行）
├── auth.py                 # 登录鉴权：PBKDF2 哈希 + 初始密码文件 + 强制改密 + 失败锁定
├── hermes_ctl.py           # 控制层：文件/MCP/env/cron/技能/备份/审计/配置开关/Hermes 命令 + 会话/智能体存储
├── cost.py                 # token 与成本统计、价格表、预算
├── notify.py               # 告警推送（12 种渠道：飞书加签/Slack/Bark/PushPlus/Server酱/Gotify/自定义…）+ 冷却
├── VERSION                 # 当前版本号（页面「系统」展示，自更新比对用）
├── templates/index.html    # 单页，14 个视图 + 登录层
├── static/
│   ├── style.css           # 深色科技风 + 亮色主题，纯 CSS 变量
│   ├── app.js              # Canvas 手绘趋势图 + 流式对话 + 多会话 + 智能体编排 + CodeMirror 接入
│   └── vendor/codemirror/  # CodeMirror 5 本地 vendor（约 500KB，离线可用，无 CDN 依赖）
├── install.sh              # ★ 通用一键部署脚本（747 行）：自动识别系统/架构/国内源，三选一模式
├── health-check.sh         # 运行时体检
├── security-check.sh       # 安全基线自检
├── start-dash.sh           # 启动 + 看门狗（30s 保活），支持 --daemon
├── fnos-setup.sh           # 飞牛一键准备：国内源 + hermes 用户 + 数据目录 + 连接自检
├── hermes-console.service  # systemd 单元模板（开机自启，FNOS 可用）
├── Dockerfile
├── docker-compose.yml      # 工作台容器：user 1001 + 数据目录 rw + docker.sock（对话用）
├── .env.example            # 环境变量模板
├── test_smoke.py           # 冒烟测试：29 项（含鉴权、代理层、SSE、配置读写）
├── requirements.txt        # 只依赖 Flask + ruamel.yaml + requests（告警全用标准库）
├── docs/
│   ├── screenshots/        # 15 张真实截图
│   └── PROMOTION.md        # 推广物料：上游 PR 草稿 + Reddit/HN/博客文案
├── .github/
│   ├── workflows/          # ci.yml（语法 + 测试）、docker.yml（Docker Hub 多架构构建）
│   ├── ISSUE_TEMPLATE/     # Bug / Feature 模板（中英双语）
│   └── PULL_REQUEST_TEMPLATE.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── LICENSE                 # MIT
├── README.md               # 英文版
└── README.zh-CN.md         # 本文件
```

## 十五、API

**监控类**

| 路径 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 页面 |
| `/api/overview` | GET | 全量快照（含 60 点历史） |
| `/api/probe` | GET/POST | 活体探测，`{"deep":true}` 触发 L3 |
| `/api/chat` | POST | `{"message":"..."}` 转发给 Hermes |
| `/api/chat/stream` | POST | 流式对话（SSE）：逐 token 返回 + 工具调用事件 |
| `/api/sessions` | GET/POST | **多会话**：列表 / 创建（历史逐会话落盘到 `sessions/`） |
| `/api/sessions/<sid>/…` | GET/POST | 会话详情 / 重命名 / 删除 / 对话（`/chat/stream` 为 SSE 流式） |
| `/proxy/<path>` | ANY | 代理转发到 Hermes 官方仪表盘后端（FastAPI :9119）；普通 HTTP 继承工作台鉴权，WebSocket 升级由前置 Caddy 直连上游 |
| `/api/skills` | GET | 技能列表 |
| `/api/memories` | GET | 记忆文件列表 |
| `/api/scan` | POST | `{"kind":"health"\|"security"}` 跑巡检脚本 |
| `/api/config` | GET | 当前配置自检 |

**配置类**（`DASH_READ_ONLY=1` 时全部拒绝）

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/files` | GET | 可编辑文件清单 |
| `/api/file` | GET/POST | 读 / 写配置（自动备份 + 语法校验） |
| `/api/backups` | GET | 某文件的备份历史 |
| `/api/rollback` | POST | 回滚（回滚前先存当前状态） |
| `/api/workspace` | GET | **工作区**：列出 Hermes 数据目录下的任意目录（文件树浏览器） |
| `/api/workspace/file` | GET/POST | **工作区**：读 / 写任意文本文件（自动备份 + 语法校验 + 越界防护） |
| `/api/mcp` | GET/POST | MCP 列表 / 保存（保序保注释） |
| `/api/mcp/delete` `/api/mcp/toggle` | POST | 删除 / 启停 |
| `/api/mcp/reload` | POST | 热加载，不重启 |
| `/api/mcp/test` | POST | 单个 MCP 服务器连通性测试（`hermes mcp test <name>`，best-effort） |
| `/api/env` | GET/POST | .env 读写（密钥脱敏） |
| `/api/providers` | GET | Provider 预设 |
| `/api/providers/apply` | POST | 一键切换 Provider |
| `/api/chatapi` | GET/POST | **对话接口**：读 / 写 `config.yaml` 的 `model` + `.env` 密钥 / Base URL |
| `/api/skills/toggle` `/api/skills/install` | POST | 归档/恢复 / 从 Hub 安装 |
| `/api/skills/archived` | GET | 已归档技能列表 |
| `/api/cron` `/api/cron/toggle` | GET/POST | 定时任务列表 / 启停 |
| `/api/action` | POST | `restart` / `upgrade` / `reload-mcp` |
| `/api/audit` | GET | 变更审计（最近 120 条） |

**智能体编排类**（v1.6.0 新增）

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/agents` | GET/POST | 智能体定义（id / 名称 / 角色 / 人设 / 模型）；`DELETE /api/agents/<aid>` 删除 |
| `/api/teams` | GET/POST | 团队定义（成员 + `sequential` / `pipeline` / `parallel`）；`DELETE /api/teams/<tid>` 删除 |
| `/api/teams/<tid>/run/stream` | POST | 运行团队编排（SSE：逐个智能体流式输出 + 耗时；pipeline 模式上游产出注入下一位上下文） |

> 共 **56 个 API 端点**（另有 `/` 页面 与 `/proxy/<path>` 代理层）。

**成本与告警**

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/cost` | GET | 用量与预算报告 |
| `/api/cost/record` | POST | 主动上报 `{"model":"","in":0,"out":0}` |
| `/api/cost/pricing` | GET/POST | 价格表（元/百万 token），**必须按真实账单校准** |
| `/api/notify` | GET/POST | 告警渠道与规则（GET 返回 `schema`，凭证脱敏；POST 按下标对齐保留原密钥） |
| `/api/notify/test` | POST | 发一条测试消息，绕开冷却 |

**登录 / 版本 / 功能接口（v3 新增）**

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/login` | POST | `{"password":"..."}` 登录；返回 `must_change` 提示是否强制改密 |
| `/api/change_password` | POST | `{"old":"","new":""}` 改密（≥8 位）；成功后删初始明文文件 |
| `/api/logout` | POST | 登出（清 session） |
| `/api/version` | GET | 当前版本 + 上游版本（配 `UPDATE_REPO` 才比对）+ 是否需改密 |
| `/api/dash-update` | POST | 工作台自更新：`git pull --ff-only`，成功后台重启加载新代码 |
| `/api/doctor` | POST | 跑 `hermes doctor` 自检，返回输出 |
| `/api/hermes` | POST | `{"args":["doctor"]}` 等**白名单内**的 Hermes 子命令（doctor/update/memory/session/curator/skills/mcp/tools/model/profile） |
| `/api/cfg` | GET/POST | 读 / 写 `config.yaml` 点号路径（白名单：`tools/memory/approvals/terminal/...`），改动记审计 |

> **把 Hermes 的功能接口都搬进网页了**：`功能` 页是命令台（curated 按钮 + 手动输入，白名单放行），
> `系统` 页是版本 / 升级 / 自检 / 登录密码。Hermes CLI 能干的（自检、更新、整理记忆、会话管理、
> 多身份、技能治理、MCP 目录），在控制台里点点就行，**不用再进后台**。
