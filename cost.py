#!/usr/bin/env python3
"""
成本与 token 统计。

诚实说明：Hermes 的日志格式没有公开标准，所以这里做的是
"尽力解析 + 兜底上报"两条路：
  1. 扫描 logs/ 与 sessions/ 里的 JSON 行，找 usage / tokens 字段
  2. 解析不到就返回 0 并明确告知 —— 绝不编数字。
     这时你可以用 /api/cost/record 主动上报（把计费钩子接到 Hermes 上）

价格表是预估值，必须在页面上按你的真实账单校准，否则数字没有意义。
"""
import os
import re
import json
import time
import glob
from datetime import datetime, timedelta
from collections import defaultdict

PRICING_FILE = "pricing.json"
RECORD_FILE = "usage.jsonl"        # 自己上报的原始流水

#: 默认价格：元 / 每百万 token。预估值，务必校准。
DEFAULT_PRICING = {
    "deepseek/deepseek-chat":     {"in": 2.0,  "out": 8.0},
    "deepseek/deepseek-reasoner": {"in": 4.0,  "out": 16.0},
    "moonshot/moonshot-v1-128k":  {"in": 6.0,  "out": 6.0},
    "moonshot/moonshot-v1-32k":   {"in": 2.0,  "out": 2.0},
    "qwen/qwen-plus":             {"in": 0.8,  "out": 2.0},
    "qwen/qwen-max":              {"in": 20.0, "out": 60.0},
    "glm-4.6":                    {"in": 2.0,  "out": 6.0},
    "glm-4.5-air":                {"in": 0.5,  "out": 1.5},
    "openrouter/auto":            {"in": 3.0,  "out": 15.0},
    "_default":                   {"in": 3.0,  "out": 15.0},
}

#: 单条 usage 可能长这样（尽力兼容）
NUM = re.compile(r'"?(?:prompt_tokens|input_tokens|prompt)"?\s*[:=]\s*(\d+)')
NUM_OUT = re.compile(r'"?(?:completion_tokens|output_tokens|completion)"?\s*[:=]\s*(\d+)')
MODEL = re.compile(r'"?(?:model)"?\s*[:=]\s*"([^"]{1,80})"')
TS = re.compile(r'"?(?:ts|time|timestamp|created)"?\s*[:=]\s*"?(\d{9,13})')


def _dash(base):
    d = os.path.join(base, ".dashboard")
    os.makedirs(d, exist_ok=True)
    return d


def load_pricing(base):
    p = os.path.join(_dash(base), PRICING_FILE)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:                                    # noqa
            pass
    return dict(DEFAULT_PRICING)


def save_pricing(base, data):
    if not isinstance(data, dict):
        raise ValueError("价格表必须是对象")
    for k, v in data.items():
        if not isinstance(v, dict) or "in" not in v or "out" not in v:
            raise ValueError(f"{k} 需要形如 {{\"in\":2.0,\"out\":8.0}}")
        float(v["in"]); float(v["out"])
    with open(os.path.join(_dash(base), PRICING_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True


def price_of(pricing, model):
    if model in pricing:
        return pricing[model]
    # 模糊匹配：deepseek-chat -> deepseek/deepseek-chat
    for k, v in pricing.items():
        if k.startswith("_"):
            continue
        if k.split("/")[-1] == model or model.endswith(k.split("/")[-1]):
            return v
    return pricing.get("_default", {"in": 3.0, "out": 15.0})


def cost_of(pricing, model, tin, tout):
    p = price_of(pricing, model)
    return (tin or 0) * p["in"] / 1_000_000 + (tout or 0) * p["out"] / 1_000_000


# ============================================================
# 采集
# ============================================================

def _walk_files(base):
    out = []
    for pat in ("logs/*.log", "logs/*.jsonl", "sessions/*.jsonl", "sessions/*.log"):
        out += glob.glob(os.path.join(base, pat))
    return sorted(out)[:200]                    # 最多扫 200 个文件，别把 IO 打满


def _parse_line(line, fallback_ts):
    """从一行里抠出 (ts, model, in, out)；解析不到返回 None"""
    if not line or "{" not in line and "token" not in line.lower():
        return None
    ts = ts_hit = None
    m = TS.search(line)
    if m:
        v = int(m.group(1))
        ts = v / 1000 if v > 10_000_000_000 else v
        ts_hit = ts
    model, tin, tout = None, None, None

    try:                                        # 优先当 JSON 解析
        obj = json.loads(line)
        if isinstance(obj, dict):
            u = obj.get("usage") or obj.get("tokens") or {}
            if isinstance(u, dict):
                tin = u.get("prompt_tokens") or u.get("input_tokens") or u.get("prompt")
                tout = u.get("completion_tokens") or u.get("output_tokens") or u.get("completion")
            model = obj.get("model") or (obj.get("response") or {}).get("model")
            for k in ("ts", "time", "timestamp", "created"):
                if isinstance(obj.get(k), (int, float)):
                    v = obj[k]
                    ts = v / 1000 if v > 10_000_000_000 else v
                    break
    except Exception:                           # noqa
        pass                                    # 不是纯 JSON 就走正则

    if tin is None:
        mm = NUM.search(line)
        if mm:
            tin = int(mm.group(1))
    if tout is None:
        mm = NUM_OUT.search(line)
        if mm:
            tout = int(mm.group(1))
    if not model:
        mm = MODEL.search(line)
        if mm:
            model = mm.group(1)

    if tin is None and tout is None:
        return None
    return (ts or fallback_ts), (model or "unknown"), int(tin or 0), int(tout or 0)


def scan_usage(base, days=30):
    """扫日志文件，返回 [(ts, model, in, out)]"""
    cutoff = time.time() - days * 86400
    rows = []
    for f in _walk_files(base):
        try:
            mt = os.path.getmtime(f)
            if mt < cutoff - 86400:
                continue
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if "token" not in line.lower():
                        continue
                    r = _parse_line(line.strip(), mt)
                    if r and r[0] >= cutoff:
                        rows.append(r)
        except Exception:                       # noqa
            continue
    return rows


def load_records(base, days=30):
    """读自己上报的流水"""
    p = os.path.join(_dash(base), RECORD_FILE)
    if not os.path.isfile(p):
        return []
    cutoff = time.time() - days * 86400
    out = []
    with open(p, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("ts", 0) >= cutoff:
                out.append((o["ts"], o.get("model", "unknown"),
                            int(o.get("in", 0)), int(o.get("out", 0))))
    return out


def record(base, model, tin, tout, note=""):
    p = os.path.join(_dash(base), RECORD_FILE)
    row = {"ts": int(time.time()), "model": model or "unknown",
           "in": int(tin or 0), "out": int(tout or 0)}
    if note:
        row["note"] = note[:120]
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# ============================================================
# 聚合
# ============================================================

def _sum(rows, pricing):
    cost = tin = tout = 0.0
    calls = 0
    for _ts, model, i, o in rows:
        cost += cost_of(pricing, model, i, o)
        tin += i; tout += o; calls += 1
    return {"cost": round(cost, 4), "in": int(tin), "out": int(tout), "calls": calls}


def report(base, daily_budget=0, monthly_budget=0):
    pricing = load_pricing(base)
    scanned = scan_usage(base, 30)
    recorded = load_records(base, 30)
    allrows = scanned + recorded

    now = time.time()
    t0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    d7 = now - 7 * 86400
    d30 = now - 30 * 86400

    today = _sum([r for r in allrows if r[0] >= t0], pricing)
    week = _sum([r for r in allrows if r[0] >= d7], pricing)
    month = _sum([r for r in allrows if r[0] >= d30], pricing)

    by_model = defaultdict(lambda: {"in": 0, "out": 0, "cost": 0.0, "calls": 0})
    by_day = defaultdict(float)
    for ts, model, i, o in allrows:
        c = cost_of(pricing, model, i, o)
        b = by_model[model]
        b["in"] += i; b["out"] += o; b["cost"] += c; b["calls"] += 1
        by_day[datetime.fromtimestamp(ts).strftime("%m-%d")] += c

    month_start = datetime.now().replace(day=1, hour=0, minute=0,
                                         second=0, microsecond=0).timestamp()
    month_cost = sum(cost_of(pricing, m, i, o)
                     for ts, m, i, o in allrows if ts >= month_start)

    budget = {"daily": daily_budget, "monthly": monthly_budget,
              "used_today": today["cost"], "used_month": round(month_cost, 4)}
    if daily_budget:
        pct = today["cost"] * 100 / daily_budget
    elif monthly_budget:
        pct = month_cost * 100 / monthly_budget
    else:
        pct = 0
    budget["pct"] = round(pct, 1)
    budget["level"] = "over" if pct >= 100 else "warn" if pct >= 80 else "ok"

    models = []
    for k, v in by_model.items():
        item = {"model": k}
        for kk, vv in v.items():
            item[kk] = round(vv, 4) if kk == "cost" else vv
        models.append(item)
    models.sort(key=lambda x: -x["cost"])

    return {
        "today": today, "week": week, "month": month,
        "by_model": models[:12],
        "by_day": [{"date": k, "cost": round(v, 4)} for k, v in sorted(by_day.items())],
        "budget": budget,
        "pricing": pricing,
        "sources": {"scanned": len(scanned), "recorded": len(recorded)},
        "note": "" if allrows else
                "没有采集到 usage 数据 —— Hermes 日志里可能没有 token 记录。"
                "可用 /api/cost/record 主动上报，或把用法写进日志。",
    }
