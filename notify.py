#!/usr/bin/env python3
"""
告警推送。

设计原则：
  1. 只用标准库（urllib / smtplib），不引第三方 —— 少一个依赖少一个漏洞面
  2. 渠道凭证脱敏返回，页面上看不到完整 webhook 地址
  3. 同一类告警有冷却，避免"配额 91%"每分钟发一条把你逼疯
  4. 推送失败不能拖垮工作台，全部吞掉并记录
"""
import os
import re
import json
import time
import hmac
import base64
import hashlib
import smtplib
import threading
import urllib.request
import urllib.error
import urllib.parse
from email.mime.text import MIMEText
from email.header import Header

CONF_FILE = "notify.json"
STATE_FILE = "alert_state.json"

# 渠道类型 → 展示名。新增渠道只需在这里加一行 + 在 CHANNEL_FIELDS 补字段
# + 在 send_one 加一段发送逻辑。"未来不止 email/微信/钉钉"靠这个注册表兜底。
CHANNEL_TYPES = {
    "webhook":    "通用 Webhook（POST JSON）",
    "wecom":      "企业微信机器人",
    "dingtalk":   "钉钉机器人",
    "telegram":   "Telegram Bot",
    "smtp":       "邮件（SMTP）",
    "feishu":     "飞书 / Lark 机器人",
    "slack":      "Slack Incoming Webhook",
    "bark":       "Bark（iOS 推送）",
    "pushplus":   "PushPlus 推送加",
    "serverchan": "Server 酱",
    "gotify":     "Gotify（自建）",
    "custom":     "自定义 Webhook（可配模板）",
}

# 哪些字段是凭证 —— 返回前端时打码，落盘时若值含 •• 则沿用旧值
SECRET_FIELDS = ("url", "pass", "password", "token", "key",
                 "secret", "sendkey", "webhook", "devicekey")

# 每种渠道需要填的字段。前端按这个动态渲染表单，新增渠道零前端改动。
# 字段规格：(name, label, placeholder, secret, optional, kind)
#   secret=True    → 输入框 type=password，且返回前端时打码
#   optional=True  → 非必填
#   kind="number"  → 数字输入
CHANNEL_FIELDS = {
    "webhook":  [("url", "Webhook 地址", "https://example.com/hook", True, False, "")],
    "wecom":    [("url", "企业微信机器人地址",
                  "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...", True, False, "")],
    "dingtalk": [("url", "钉钉机器人地址",
                  "https://oapi.dingtalk.com/robot/send?access_token=...", True, False, "")],
    "telegram": [("token", "Bot Token", "123456:ABCdefGHI...", True, False, ""),
                 ("chat_id", "Chat ID", "-1001234567890 或 用户名", False, False, "")],
    "smtp":     [("host", "SMTP 主机", "smtp.qq.com", False, False, ""),
                 ("port", "端口（默认 465）", "465", False, True, "number"),
                 ("user", "发件账号", "me@qq.com", False, False, ""),
                 ("pass", "密码 / 授权码", "", True, False, "")],
    "feishu":   [("url", "飞书自定义机器人地址",
                  "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx", True, False, ""),
                 ("secret", "签名密钥（可选，开启「加签」时填）", "", True, True, "")],
    "slack":    [("url", "Slack Incoming Webhook",
                  "https://hooks.slack.com/services/T000/B000/XXXX", True, False, "")],
    "bark":     [("server", "Bark 服务器（末尾带 /）",
                  "https://api.day.app/ 或自建 https://bark.example.com/", False, False, ""),
                 ("key", "设备 Key", "你的 Bark 设备推送 key", True, False, "")],
    "pushplus": [("token", "PushPlus Token", "你的 pushplus token", True, False, ""),
                 ("topic", "群组 / 主题（可选）", "留空发给本人", False, True, "")],
    "serverchan": [("sendkey", "Server 酱 SCT Key", "SCTxxxxxxxxxxxxxxxxxxxx", True, False, "")],
    "gotify":   [("url", "Gotify 服务器地址", "https://gotify.example.com", False, False, ""),
                 ("token", "应用 Token", "", True, False, ""),
                 ("title", "标题前缀（可选）", "Hermes 告警", False, True, "")],
    "custom":   [("url", "Webhook 地址", "https://example.com/hook", True, False, ""),
                 ("method", "方法 GET / POST（默认 POST）", "POST", False, True, ""),
                 ("template", "消息体模板（JSON，{title}/{text} 占位，可选）",
                  '{"title":"{title}","content":"{text}"}', False, True, "")],
}


def _dash(base):
    d = os.path.join(base, ".dashboard")
    os.makedirs(d, exist_ok=True)
    return d


def schema():
    """返回渠道类型 + 每种渠道的字段规格，前端据此动态渲染表单。
    新增一种渠道 = 这里加描述 + CHANNEL_FIELDS 加字段 + send_one 加发送逻辑，
    前端无需改动（这是'未来不止微信钉钉'能成立的关键）。"""
    fields = {}
    for k, specs in CHANNEL_FIELDS.items():
        fields[k] = [
            {"name": n, "label": lbl, "placeholder": ph,
             "secret": bool(sec), "optional": bool(opt), "kind": kind}
            for (n, lbl, ph, sec, opt, kind) in specs
        ]
    return {"types": CHANNEL_TYPES, "fields": fields}


# ============================================================
# 配置读写
# ============================================================

def load(base):
    p = os.path.join(_dash(base), CONF_FILE)
    if not os.path.isfile(p):
        return {"channels": [], "rules": {}, "cooldown_hours": 6}
    try:
        with open(p, encoding="utf-8") as f:
            c = json.load(f)
    except Exception:                                        # noqa
        return {"channels": [], "rules": {}, "cooldown_hours": 6}
    c.setdefault("channels", [])
    c.setdefault("rules", {})
    c.setdefault("cooldown_hours", 6)
    return c


def mask(cfg):
    """把凭证打码后再返回给前端"""
    out = json.loads(json.dumps(cfg))
    for ch in out.get("channels", []):
        for k in list(ch.keys()):
            if k in SECRET_FIELDS and isinstance(ch[k], str) and ch[k]:
                v = ch[k]
                ch[k] = v[:12] + "••••••" + v[-6:] if len(v) > 24 else "••••••"
                ch[k + "_set"] = True
    return out


def save(base, cfg):
    """保存。带 _set 且值为掩码的字段 = 保持原值不动。

    回填策略：优先按"数组下标"对齐（编辑态渠道在下标不变），
    下标对不上（新增 / 改名）再退回按 name 找旧渠道。
    这样即便前端把脱敏串发回来，底层真实密钥也不会被圆点覆盖。"""
    old = load(base)
    old_by_name = {c.get("name"): c for c in old.get("channels", [])}
    old_by_idx = {i: c for i, c in enumerate(old.get("channels", []))}
    chans = []
    for i, c in enumerate(cfg.get("channels") or []):
        name = c.get("name") or c.get("type")
        oi = old_by_idx.get(i)
        old_c = oi if (oi and oi.get("type") == c.get("type")) else old_by_name.get(name, {})
        merged = dict(c)
        for k, v in list(c.items()):
            if k in SECRET_FIELDS and isinstance(v, str) and ("••" in v or not v):
                if old_c.get(k):
                    merged[k] = old_c[k]          # 未修改，沿用旧值
                else:
                    merged.pop(k, None)
        for k in list(merged.keys()):
            if k.endswith("_set"):
                merged.pop(k)
        chans.append(merged)
    data = {
        "channels": chans,
        "rules": cfg.get("rules") or {},
        "cooldown_hours": int(cfg.get("cooldown_hours") or 6),
    }
    p = os.path.join(_dash(base), CONF_FILE)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)                       # 里面有 webhook 和邮箱密码
    except OSError:
        pass
    return True


# ============================================================
# 发送
# ============================================================

def _post(url, payload, timeout=15):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")[:300]


def _get(url, timeout=15):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")[:300]


def send_one(ch, title, body):
    t = ch.get("type")
    text = f"{title}\n\n{body}"
    try:
        if not ch.get("enabled", True):
            return False, "已禁用"
        if t == "webhook":
            s, r = _post(ch["url"], {"title": title, "text": text,
                                     "msgtype": "text", "body": body})
            return 200 <= s < 300, f"HTTP {s}"
        if t == "wecom":
            s, r = _post(ch["url"], {"msgtype": "text",
                                     "text": {"content": text}})
            return ("ok" in r.lower()) or 200 <= s < 300, f"HTTP {s} {r[:80]}"
        if t == "dingtalk":
            s, r = _post(ch["url"], {"msgtype": "text",
                                     "text": {"content": text}})
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"
        if t == "telegram":
            url = f"https://api.telegram.org/bot{ch['token']}/sendMessage"
            s, r = _post(url, {"chat_id": ch["chat_id"], "text": text})
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"
        if t == "smtp":
            # 收件人缺省为发件人自己（自用告警通常是"发到我自己的邮箱"）
            to = ch.get("to") or ch.get("user", "")
            if not to:
                return False, "缺少收件人（to 或 user）"
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(title, "utf-8")
            msg["From"] = ch.get("user", "")
            msg["To"] = to
            if int(ch.get("port") or 465) == 465:
                srv = smtplib.SMTP_SSL(ch["host"], 465, timeout=20)
            else:
                srv = smtplib.SMTP(ch["host"], int(ch.get("port") or 25), timeout=20)
                try:
                    srv.starttls()
                except Exception:                # noqa
                    pass
            try:
                if ch.get("user"):
                    srv.login(ch.get("user"), ch.get("pass", ""))
                srv.sendmail(ch.get("user", ""), [to], msg.as_string())
            finally:
                try:
                    srv.quit()
                except Exception:                # noqa
                    pass
            return True, "已发送"

        # ---- 飞书 / Lark（自定义机器人，支持加签）----
        if t == "feishu":
            payload = {"msg_type": "text", "content": {"text": text}}
            secret = ch.get("secret")
            if secret:
                # 加签：timestamp + secret 做 HMAC-SHA256，结果 base64
                ts = str(int(time.time()))
                string_to_sign = ts + "\n" + secret
                hmac_code = hmac.new(secret.encode("utf-8"),
                                     string_to_sign.encode("utf-8"),
                                     hashlib.sha256).digest()
                sign = base64.b64encode(hmac_code).decode("utf-8")
                payload["timestamp"] = ts
                payload["sign"] = sign
            s, r = _post(ch["url"], payload)
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"

        # ---- Slack Incoming Webhook ----
        if t == "slack":
            s, r = _post(ch["url"], {"text": text})
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"

        # ---- Bark（iOS 推送，走 GET）----
        if t == "bark":
            server = ch["server"].rstrip("/") + "/"
            # URL 编码标题与正文，避免中文 / 空格截断
            url = (server + urllib.parse.quote(str(ch.get("key", "")), safe="")
                   + "/" + urllib.parse.quote(title, safe="")
                   + "/" + urllib.parse.quote(body, safe=""))
            s, r = _get(url)
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"

        # ---- PushPlus 推送加 ----
        if t == "pushplus":
            payload = {"token": ch["token"], "title": title, "content": body}
            topic = ch.get("topic")
            if topic:
                payload["topic"] = topic
            s, r = _post("https://www.pushplus.plus/send", payload)
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"

        # ---- Server 酱 ----
        if t == "serverchan":
            s, r = _post(f"https://sctapi.ftqq.com/{ch['sendkey']}.send",
                         {"title": title, "desp": body})
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"

        # ---- Gotify（自建推送）----
        if t == "gotify":
            url = ch["url"].rstrip("/") + "/message?token=" + urllib.parse.quote(str(ch.get("token", "")), safe="")
            prefix = (ch.get("title") or "").strip()
            s, r = _post(url, {"title": (prefix + " " + title).strip(),
                              "message": body, "priority": 5})
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"

        # ---- 自定义 Webhook（方法 + 模板可配，兜底未来所有渠道）----
        if t == "custom":
            method = (ch.get("method") or "POST").upper()
            tpl = (ch.get("template") or "").strip()
            if tpl:
                # 用 replace 而非 str.format：JSON 里的大括号会被 format 误当成占位符
                try:
                    body_str = (tpl.replace("{title}", title)
                                .replace("{text}", body))
                    payload = json.loads(body_str)
                except Exception as e:                       # noqa
                    return False, f"模板解析失败（{e}）"
            else:
                payload = {"title": title, "text": text, "msgtype": "text"}
            if method == "GET":
                s, r = _get(ch["url"])
                return 200 <= s < 300, f"HTTP {s} {r[:80]}"
            s, r = _post(ch["url"], payload)
            return 200 <= s < 300, f"HTTP {s} {r[:80]}"

        return False, f"未知渠道类型 {t}"
    except urllib.error.URLError as e:
        return False, f"网络错误：{e}"
    except KeyError as e:
        return False, f"缺少字段 {e}"
    except Exception as e:                       # noqa
        return False, str(e)[:160]


def broadcast(base, key, title, body, force=False):
    """
    按冷却广播。返回 [(渠道名, ok, msg)]。

    关键修正：只有当"至少一个渠道成功"时才记冷却。
    否则会出这种坑——webhook 地址配错，第一次失败后 mark_sent 立刻把这条
    告警标记成"已处理"，6 小时内不再发；你以为它正常，其实它从来没发出去过。
    """
    cfg = load(base)
    if not force and not cooling_passed(base, key, cfg.get("cooldown_hours", 6)):
        return []
    results = []
    for ch in cfg.get("channels", []):
        ok, msg = send_one(ch, title, body)
        results.append((ch.get("name") or ch.get("type"), ok, msg))
    # 全失败（或压根没渠道）：不标记冷却，下次巡检继续重试
    if any(ok for _, ok, _ in results):
        mark_sent(base, key)
    return results


def cooling_passed(base, key, hours):
    p = os.path.join(_dash(base), STATE_FILE)
    if not os.path.isfile(p):
        return True
    try:
        with open(p, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:                            # noqa
        return True
    last = st.get(key, 0)
    return (time.time() - last) > hours * 3600


def mark_sent(base, key):
    p = os.path.join(_dash(base), STATE_FILE)
    st = {}
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:                        # noqa
            st = {}
    st[key] = int(time.time())
    with open(p, "w", encoding="utf-8") as f:
        json.dump(st, f)


def log_alert(base, key, title, results):
    """告警也要留痕 —— 否则你不知道它到底发没发出去"""
    p = os.path.join(_dash(base), "alerts.log")
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "t": int(time.time()),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "key": key, "title": title,
                "sent": [{"ch": n, "ok": o, "msg": m} for n, o, m in results],
            }, ensure_ascii=False) + "\n")
    except Exception:                            # noqa
        pass


def read_alerts(base, limit=50):
    p = os.path.join(_dash(base), "alerts.log")
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(l) for l in lines if l.strip()][::-1]
    except Exception:                            # noqa
        return []
