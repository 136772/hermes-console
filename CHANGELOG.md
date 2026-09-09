# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.5.0] - 2026-09-09

### Added
- **工作区文件树浏览器**（新导航「工作区」）：浏览整个 Hermes 数据目录的任意子目录，读 / 写任意文本文件。复用既有自动备份、语法校验、目录穿越防护；与「配置文件」白名单编辑器互补——前者只改核心配置，后者可看全貌。
- **MCP 一键连通测试**：MCP 管理页每个服务器新增「测试连接」按钮，调用 `hermes mcp test <name>`（复用 docker exec 机制），输出原样展示。
- 新增 API：`/api/workspace`（列目录）、`/api/workspace/file`（GET/POST 读写）、`/api/mcp/test`（POST）。API 端点 40 → 44。

### Changed
- 中文 README 的 `/proxy` 与 API 章节同步 WebSocket 经前置 Caddy 透传的说明。

## [1.4.0] - 2026-09-09

### Added
- **WebSocket 代理补全**：嵌入的官方 dashboard 之前 chat/terminal 实时功能失效（Flask 是 WSGI，处理不了 WS 升级）。`docker-compose.yml` 新增 `caddy` 前置反代服务，由它对外发布 `8080` 并把 `/proxy/*` 的 WebSocket 升级直连官方后端 `HERMES_API`，剥掉 `/proxy` 前缀。
- 工作台容器改为只监听内部 `8081`（不再直接对公网暴露），新增 `Caddyfile` 反代配置。

### Changed
- 修正文档中「`/proxy/*` 全部继承工作台鉴权」的失真表述：普通 HTTP 仍继承控制台登录鉴权；WebSocket 路径由前置 Caddy 终结、鉴权沿用官方后端自身的 `ws-ticket`。

## [1.3.1] - 2026-09-09

### Added
- **英文 README**：主 README 改为英文（面向国际用户重写，非直译），中文版保留为 `README.zh-CN.md`，两版顶部互相链接
- **社区文件**：`CONTRIBUTING.md`、Issue 模板（Bug / Feature，中英双语）、PR 模板
- **Docker Hub 自动构建**：`.github/workflows/docker.yml`，打 `v*.*.*` tag 时构建并推送 **amd64 + arm64** 多架构镜像；未配置 secrets 时自动跳过，不影响 CI
- **推广物料**：`docs/PROMOTION.md` —— 上游 PR 草稿、Reddit / HN / X / 博客文案、Docker Hub 配置步骤

### Changed
- `Dockerfile` 的 PyPI 源改为 `ARG PIP_INDEX` 可配置，Docker Hub 构建时用官方 PyPI（`--build-arg PIP_INDEX=https://pypi.org/simple`）

## [1.3.0] - 2026-09-09

### Added
- **官方仪表盘代理嵌入**：新增「仪表盘」页，iframe 整页嵌入 Hermes 官方 Web 仪表盘（FastAPI + React SPA，19 个页面），代理层 `/proxy/<path>` 自动继承鉴权
- **流式对话（SSE）**：`POST /api/chat/stream` 逐 token 返回 + 工具调用可视化卡片，前端 `fetch` + `ReadableStream` 消费
- **12 种告警渠道**：新增飞书/Lark（含加签）、Slack、Bark、PushPlus、Server酱、Gotify、自定义 Webhook（可配模板），schema 驱动动态表单，逐条增删改/启停/一键测试
- **对话接口配置**：新增「配置 → 对话接口」子页，Provider 预设 / 自定义 OpenAI 兼容接口 + 模型 / Key / Base URL，直接落 `config.yaml` + `.env`
- **登录鉴权（安全优先）**：单密码、无用户名，初始密码随机生成写入文件，首次登录强制改密，PBKDF2-HMAC-SHA256（20 万轮）+ 失败锁定（5 次 / 15 分钟）
- **Hermes 全功能接口**：「功能」页命令台（doctor/update/memory/curator/session/skills/mcp/tools/model/profile），白名单放行 + 配置开关 + 网关白名单
- **可持续升级**：`VERSION` 文件 + 「系统」页（工作台 git pull 自更新、Hermes 升级、doctor 自检、改密）
- **成本与预算**：token 统计 / 按模型分解 / 预算告警（超 80% 预警 / 100% 告警）
- **亮色主题**：右上角切换，Canvas 图表配色跟随主题
- **开源项目文件**：LICENSE (MIT)、.gitignore、CHANGELOG、冒烟测试、GitHub Actions CI

### Fixed
- 鉴权守卫覆盖 `/proxy/*`（原先只拦截 `/api/*`）
- 编辑渠道改名时密钥按下标对齐保留（原先按 name 匹配会丢密钥）
- 告警全失败不冷却（至少一成功才记冷却）
- SMTP 收件人为空时缺省用发件人
- 备份同秒覆盖（加序号隔离）
- `pgrep -f hermes` 误判运行中（改扫 `/proc/*/cmdline`）
- Flask 单线程阻塞长对话（`threaded=True`）
- `TITLES` 缺 `cost` 键导致标题显示为英文

## [1.2.0] - 2026-09-08

### Added
- 配置中心：文件编辑器（白名单 + 备份 + 回滚 + diff + YAML 校验）
- MCP 服务器管理（增删改 + 热加载）
- Provider / Key 管理（5 个国内可用预设 + 脱敏显示）
- 变更审计日志
- 体检脚本集成（`health-check.sh` / `security-check.sh`）
- Docker Compose 部署 + 宿主机部署 + 只读监控三种方式
- 开机自启（`start-dash.sh` 看门狗 + systemd）
- 国内镜像源一键配置（`fnos-setup.sh`）

## [1.0.0] - 2026-09-07

### Added
- 初始版本：总览页（6 张状态卡 + 60 分钟趋势图）
- 网页对话（`hermes run`）
- 技能 / 记忆 / 定时任务列表
- 活体探测（三级）
- 深色科技风 UI，纯 Flask + 原生 Canvas
