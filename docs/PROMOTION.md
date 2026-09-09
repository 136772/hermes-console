# 推广物料 / Promotion Kit

按性价比排序。**第 1 项效果最好、成本最低，强烈建议先做。**

---

## 1. 给上游提 PR（⭐ 最推荐）

[Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 README 有 `## Community` 区块，专门列社区项目。
改一行就能拿到**最精准的流量** —— 上游用户就是你的目标用户。

### 改哪里

文件：`README.md`，第 250 行 `## Community` 下面，紧跟最后一条 `HermesClaw` 之后。

### 加这一行

```markdown
- 🖥️ [hermes-console](https://github.com/136772/hermes-console) — Web console for Hermes: monitoring, browser chat, config editing, cost/budget tracking, 12 alert channels, and one-click upgrades. Plain Flask with zero frontend build; also embeds the official dashboard behind its own auth.
```

> 格式对齐上游：`- emoji [名称](链接) — 一句话描述`
> 上游已有 `🔌`（集成类），我们属于面板类，用 `🖥️` 区分。

### PR 标题与正文

**标题**：`docs: add hermes-console to Community section`

**正文**：

```markdown
Adds [hermes-console](https://github.com/136772/hermes-console) to the Community list — a web console for managing a running Hermes instance.

**What it does**
- Monitoring: container status, resource usage, session stats, 60-min trend, cost/budget tracking with alerts
- Browser chat with SSE streaming and tool-call cards (no SSH needed to give it an instruction)
- Config editing for `config.yaml` / `.env` / `SOUL.md` / skills / cron — with auto-backup, YAML validation, one-click rollback, and full audit log
- 12 alert channels (Feishu, Slack, Telegram, Bark, Gotify, generic webhook, …), all stdlib-only
- One-click `hermes update` / `hermes doctor` from the UI
- Embeds the official `hermes dashboard` behind its own auth proxy, so users get both in one place

**Why it fits the Community list**

It targets people already running Hermes on a NAS / home server who currently have to SSH in to check on it or change config. Plain Flask, no frontend build, MIT licensed.

Happy to adjust wording or placement if you'd prefer a different emoji or phrasing.
```

### 怎么提

1. Fork https://github.com/NousResearch/hermes-agent
2. 编辑 `README.md`，在 Community 区块加上面那行
3. 提 PR，标题正文照抄上面
4. **PR 描述里不要提"给我 star"** —— 上游 maintainer 反感纯引流，描述要站在"对用户有用"的角度

> ⚠️ 被拒也正常。如果被拒，可以改成去他们的 [Discord](https://discord.gg/NousResearch) 的 showcase 频道发一条，效果类似。

### 当前状态（2026-09-09）

PR [#106093](https://github.com/NousResearch/hermes-agent/pull/106093) **已提交、open、未合并、`mergeable=True`（无冲突）**。
现在就是等上游 maintainer 合并。你可以：

- **礼貌顶一次**：在 PR 下留一条友善评论（如「Hi, any chance for a review? Happy to adjust wording.」），别刷屏、别催。
- **别重复提**：已经 open 就不要再开第二个 PR，会被当 spam。
- **兜底**：若两周无响应，去 Discord showcase 频道发一条（文案见第 2 节 Reddit 版改个开头即可）。

---

## 2. Reddit

推荐 `r/LocalLLM`（用户最对口）、`r/selfhosted`、`r/homelab`。
**三个版别同时发一模一样的内容** —— 会被当 spam。至少改标题和开头。

### r/LocalLLM 版本

**标题**：
```
Built a web console for my Hermes Agent — turns out "process is running" doesn't mean "it can still work"
```

**正文**：
```
I've been running Hermes Agent on a home server for a few months. Two things kept biting me:

1. I'd find out it broke three days after it broke.
2. Checking on it meant SSH-ing in and running four different commands.

So I built a web console: https://github.com/136772/hermes-console

The part I wish someone had told me earlier: **"process is running" and "agent is functional" are different things.** A container can be up while its memory directory silently stops accepting writes — you lose every bit of tuning you did and nothing tells you. So the liveness probe has three tiers:

- L1: process responds
- L2: can it actually write to memory (this is the one that bites you)
- L3: real model round-trip (costs tokens, so it's Shift-click only)

Other things that turned out to matter more than I expected:

- **Cost tracking.** Monitoring tells you it broke; cost tells you whether to keep feeding it. Per-model breakdown + daily/monthly budgets with 80%/100% alerts.
- **Alerts only on anomalies, with 6h suppression per class.** First version alerted every minute at 91% quota. I muted it within two hours.
- **Config editing with guardrails.** Auto-backup (30 per file), YAML validated before write, one-click rollback, full audit log. Without those four I wouldn't trust a web UI to touch config.

Plain Flask + hand-drawn Canvas. No build step, no chart library, no node_modules, 3 pip deps. It also proxies the official `hermes dashboard` behind its own auth, so you get both in one tab.

MIT. Happy to answer questions — and if you run it, I'd love to hear what's missing.
```

### r/selfhosted 版本（标题改一下，开头改成自托管视角）

**标题**：
```
A lightweight web console for managing a self-hosted AI agent (Flask, no build step, ARM-friendly)
```

开头换成：
```
If you're running an AI agent on a NAS or home box, this is a single-panel way to monitor it, talk to it, edit its config, and track what it costs to run.
```

---

## 3. Hacker News（Show HN）

**标题**（HN 标题有 80 字符限制，要克制）：
```
Show HN: A web console for Hermes Agent – monitor, chat, config, cost, alerts
```

**正文**（第一条评论，自己发）：
```
I run Hermes Agent on a home server and kept SSH-ing in to check on it, so I built a web console.

The design decision I'd most defend: a three-tier liveness probe. Most dashboards check "is the process up" and stop there. But an agent can have a live process and a memory directory that silently stopped accepting writes — you lose all your tuning and nothing alerts you. So:

- L1 process responds (free)
- L2 memory dir actually writable (free, catches the nasty one)
- L3 real model round-trip (costs tokens, opt-in only)

Second thing: alerts only fire on anomalies, and the same class is suppressed for 6 hours. My first version alerted every minute when disk quota hit 91%. I muted it in two hours, which made it worse than no alerting at all.

Cost tracking matters more than I expected — monitoring tells you it broke, cost tells you whether to keep feeding it.

Stack is deliberately boring: Flask + hand-drawn Canvas, 3 pip deps, no build step, no node_modules. Runs on ARM so it works on NAS boxes. It also proxies the official dashboard behind its own auth.

MIT licensed. Would genuinely like to hear what's missing — especially from people running agents unattended for weeks at a time.
```

> HN 上**别放链接在正文**，URL 单独填在 url 字段。发完自己抢第一条评论补充上下文，效果比正文好。

---

## 4. X / Twitter

```
Ran @NousResearch's Hermes Agent on my NAS for months. Two problems:

- found out it broke 3 days later
- checking it meant SSH + 4 commands

So I built a web console. Flask, no build step, no node_modules.

The bit I'd defend: "process running" ≠ "agent works". Memory dir can silently stop accepting writes. github.com/136772/hermes-console
```

分成 3-4 条 thread 更好：第 2 条讲三级探测，第 3 条讲告警降噪，第 4 条放链接 + 截图。

---

## 5. 博客（中文，NAS 圈传播力强）

标题候选：
- 《飞牛 NAS 上给 Hermes Agent 装个网页控制台》
- 《养 AI Agent 三个月后，我把它搬进了浏览器》
- 《"进程还在"不等于"它还能干活"——一个 Agent 监控面板的设计取舍》

结构建议：
1. **痛点开场**：半夜 SSH 进 NAS 改配置
2. **反直觉发现**：三级探测（这段最容易被引用来引用去）
3. **告警降噪**：每分钟一条的教训
4. **成本视角**：监控告诉你坏了没，成本告诉你值不值得养
5. **安全权衡**：`docker.sock` 是逃逸面，四道护栏
6. **部署**：飞牛上 5 分钟跑起来
7. 链接 + 求 star

发在知乎 / 少数派 / 什么值得买 / 飞牛社区 / NAS 相关的 Telegram & QQ 群。

---

## 6. Docker Hub（降低试用门槛）

已配好自动构建 `.github/workflows/docker.yml`（打 `v*.*.*` tag 时触发，amd64 + arm64）。

**你需要做一次**：

1. 注册/登录 https://hub.docker.com
2. Account Settings → Security → **New Access Token**（Read/Write/Delete）
3. 到 GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret：
   - `DOCKERHUB_USERNAME` = 你的 Docker Hub 用户名
   - `DOCKERHUB_TOKEN` = 上面那个 token
4. 打一个新 tag 触发构建（当前最新 release 是 `v1.5.0`，下次更新打 `v1.5.1` 之类）：
   `git tag v1.5.1 && git push origin v1.5.1`

没配 secret 时 workflow 会**自动跳过**，不会让 CI 变红，所以现在不配也没事。

---

## 发之前检查一遍

- [ ] README 里没有 `<你的用户名>` 这类占位符残留
- [ ] 截图能正常显示
- [ ] CI 徽章是绿的
- [ ] 安装命令在新机器上真的能跑通（拿台干净机器试一次）
- [ ] 没在任何地方留下真实 API Key / token
