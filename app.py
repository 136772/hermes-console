#!/usr/bin/env python3
"""
Hermes 工作台后端
- 采集 Hermes / 容器 / 系统 的真实运行数据
- 转发对话到 Hermes（docker exec 或本地 CLI）
- 只依赖 Flask，无第三方监控库
"""
import os
import re
import time
import json
import shutil
import threading
import subprocess
from collections import deque
from datetime import timedelta
import hermes_ctl as ctl
import cost as costmod
import notify
import auth as authmod
from flask import (Flask, jsonify, request, render_template, session,
                   Response, stream_with_context)

app = Flask(__name__)

# ---------- 配置 ----------
HERMES_DIR = os.getenv("HERMES_DIR", "/opt/data")
HERMES_MODE = os.getenv("HERMES_MODE", "auto")      # docker | local | auto
CONTAINER = os.getenv("HERMES_CONTAINER", "hermes")
QUOTA_MB = int(os.getenv("QUOTA_MB", "10240"))
CHAT_TIMEOUT = int(os.getenv("CHAT_TIMEOUT", "180"))
HISTORY_LEN = 60
COMPOSE_DIR = os.getenv("COMPOSE_DIR", "")          # Hermes 的 compose 目录（用于升级）
BUDGET_DAILY = float(os.getenv("BUDGET_DAILY", "0"))     # 每日预算（元），0=不限制
BUDGET_MONTHLY = float(os.getenv("BUDGET_MONTHLY", "0")) # 每月预算（元）
ALERT_INTERVAL = int(os.getenv("ALERT_INTERVAL", "600"))  # 告警巡检间隔（秒）

#: 写操作总闸。设为 0 = 工作台彻底只读（只想监控时用它）
READ_ONLY = os.getenv("DASH_READ_ONLY", "0") == "1"

#: 危险动作（重启/升级/删除）需要二次确认令牌
DANGER_TOKEN = os.getenv("DASH_DANGER_TOKEN", "")

#: Hermes 官方仪表盘后端地址（FastAPI :9119）
HERMES_API = os.getenv("HERMES_API", "http://127.0.0.1:9119")
#: 官方后端认证 token（可选，官方后端开启认证时填）
HERMES_API_TOKEN = os.getenv("HERMES_API_TOKEN", "")
#: 代理转发超时（秒）
PROXY_TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "300"))

# ---------- 登录鉴权（安全优先） ----------
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "24"))
AUTH_ENABLED = os.getenv("DASH_AUTH", "1") != "0"      # 默认开启；DASH_AUTH=0 关闭
app.secret_key = authmod.load_or_create_secret_key(HERMES_DIR)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = timedelta(hours=SESSION_HOURS)
if os.getenv("DASH_SECURE_COOKIE", "0") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True
# 首次部署：生成随机初始密码 + 明文文件 + must_change
if AUTH_ENABLED:
    authmod.init_auth(HERMES_DIR)

# ---------- 历史采样（供前端图表） ----------
_history = deque(maxlen=HISTORY_LEN)
_lock = threading.Lock()


def _run(cmd, timeout=20):
    """安全执行命令，绝不 shell=True"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", "command not found"
    except Exception as e:                                  # noqa
        return -1, "", str(e)


def detect_mode():
    if HERMES_MODE in ("docker", "local"):
        return HERMES_MODE
    rc, out, _ = _run(["docker", "ps", "--format", "{{.Names}}"])
    if rc == 0 and out:
        names = [n.strip() for n in out.splitlines() if n.strip()]
        for n in names:
            if "hermes" in n.lower():
                return "docker"
    return "local"


MODE = detect_mode()


def hermes_exec(args, timeout=CHAT_TIMEOUT):
    """在 Hermes 环境里执行一条命令"""
    if MODE == "docker":
        return _run(["docker", "exec", CONTAINER] + args, timeout=timeout)
    return _run(args, timeout=timeout)


# ---------- 采集函数 ----------
def dir_size_mb(path):
    if not os.path.isdir(path):
        return 0
    rc, out, _ = _run(["du", "-sm", path])
    try:
        return int(out.split()[0])
    except Exception:                                        # noqa
        return 0


def count_files(path, pattern=None):
    if not os.path.isdir(path):
        return 0
    try:
        if pattern:
            n = sum(1 for f in os.listdir(path) if f.endswith(pattern))
        else:
            n = sum(1 for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)))
        return n
    except Exception:                                        # noqa
        return 0


def count_dirs(path, skip_hidden=True):
    """统计子目录数量（技能是"一个目录 = 一个技能"）"""
    if not os.path.isdir(path):
        return 0
    try:
        n = 0
        for f in os.listdir(path):
            if skip_hidden and f.startswith("."):
                continue
            if os.path.isdir(os.path.join(path, f)):
                n += 1
        return n
    except Exception:                                        # noqa
        return 0


def recent_log_errors(hours=24):
    logs = os.path.join(HERMES_DIR, "logs")
    if not os.path.isdir(logs):
        return 0, []
    rc, out, _ = _run(
        ["find", logs, "-type", "f", "-mtime", "-1", "-exec",
         "grep", "-icE", "error|traceback|exception|failed", "{}", ";"]
    )
    total = 0
    for line in (out or "").splitlines():
        try:
            total += int(line.strip())
        except ValueError:
            pass

    # 抓取最近几条错误样本
    samples = []
    rc2, out2, _ = _run(
        ["find", logs, "-type", "f", "-mtime", "-1", "-exec",
         "grep", "-ihE", "error|traceback|exception|failed", "{}", ";"],
        timeout=20,
    )
    for line in (out2 or "").splitlines():
        line = line.strip()
        if line and len(samples) < 8:
            samples.append(line[:200])
    return total, samples


def hermes_pids():
    """
    找 Hermes 进程 PID。

    为什么不用 pgrep -f hermes：任何命令行里带 hermes 字样的进程都会被算进去
    （本工作台叫 hermes-console，一条 curl 命令里出现 hermes 也会命中），
    结果是"明明没启动却显示运行中"的假阳性 —— 监控里最不能犯的错。

    判定规则（严格）：argv[0] 的文件名是 hermes / hermes-agent，
    或 comm 恰好等于 hermes。且排除自己。
    """
    me = os.getpid()
    found = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        if pid == me:
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
            with open(f"/proc/{d}/comm") as f:
                comm = f.read().strip()
        except Exception:                                    # noqa
            continue
        argv0 = os.path.basename(argv[0].decode("utf-8", "ignore")) if argv else ""
        if argv0 in ("hermes", "hermes-agent", "hermes.exe") or comm == "hermes":
            found.append(pid)
    return sorted(found)


def container_info():
    """容器/进程存活信息"""
    info = {"mode": MODE, "alive": False, "name": CONTAINER,
            "restarts": 0, "mem": "-", "cpu": "-", "status": "-", "pids": []}
    if MODE == "docker":
        rc, out, _ = _run(["docker", "inspect", "-f",
                           "{{.State.Status}}|{{.RestartCount}}", CONTAINER])
        if rc == 0 and "|" in out:
            st, rs = out.split("|", 1)
            info["status"] = st
            info["alive"] = st == "running"
            try:
                info["restarts"] = int(rs)
            except ValueError:
                pass
        rc2, out2, _ = _run(["docker", "stats", "--no-stream", "--format",
                             "{{.MemUsage}}|{{.CPUPerc}}", CONTAINER])
        if rc2 == 0 and "|" in out2:
            m, c = out2.split("|", 1)
            info["mem"] = m.strip()
            info["cpu"] = c.strip()
    else:
        pids = hermes_pids()
        info["alive"] = bool(pids)
        info["status"] = "running" if pids else "stopped"
        info["pids"] = pids[:5]
    return info


def system_stats():
    """读 /proc，零依赖"""
    s = {}
    try:
        with open("/proc/loadavg") as f:
            s["load1"] = float(f.read().split()[0])
    except Exception:                                        # noqa
        s["load1"] = 0.0
    s["ncpu"] = os.cpu_count() or 1
    try:
        with open("/proc/meminfo") as f:
            txt = f.read()
        tot = int(re.search(r"MemTotal:\s+(\d+)", txt).group(1))
        avail = int(re.search(r"MemAvailable:\s+(\d+)", txt).group(1))
        s["mem_total_mb"] = tot // 1024
        s["mem_avail_mb"] = avail // 1024
        s["mem_used_pct"] = round((tot - avail) * 100 / tot, 1)
    except Exception:                                        # noqa
        s.update({"mem_total_mb": 0, "mem_avail_mb": 0, "mem_used_pct": 0})
    try:
        st = os.statvfs(HERMES_DIR)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        s["disk_total_gb"] = round(total / 1024 ** 3, 1)
        s["disk_free_gb"] = round(free / 1024 ** 3, 1)
        s["disk_used_pct"] = round((total - free) * 100 / total, 1)
    except Exception:                                        # noqa
        s.update({"disk_total_gb": 0, "disk_free_gb": 0, "disk_used_pct": 0})
    return s


def collect():
    """汇总一份完整快照"""
    used = dir_size_mb(HERMES_DIR)
    pct = round(used * 100 / QUOTA_MB, 1) if QUOTA_MB else 0
    errs, samples = recent_log_errors()
    cinfo = container_info()
    sysx = system_stats()

    snap = {
        "ts": int(time.time()),
        "hermes_dir": HERMES_DIR,
        "quota": {"used_mb": used, "limit_mb": QUOTA_MB, "pct": pct},
        "memory": {
            "files": count_files(os.path.join(HERMES_DIR, "memories")),
            "mb": dir_size_mb(os.path.join(HERMES_DIR, "memories")),
        },
        "skills": {
            "active": count_dirs(os.path.join(HERMES_DIR, "skills")),
            "archived": count_dirs(os.path.join(HERMES_DIR, "skills", ".archive"),
                                   skip_hidden=False),
        },
        "logs": {"errors_24h": errs, "samples": samples},
        "cron": count_files(os.path.join(HERMES_DIR, "cron")),
        "sessions": count_files(os.path.join(HERMES_DIR, "sessions")),
        "container": cinfo,
        "system": sysx,
    }
    return snap


def sampler():
    """后台定时采样，喂给前端图表"""
    while True:
        try:
            s = collect()
            with _lock:
                _history.append({
                    "t": s["ts"],
                    "load": s["system"]["load1"],
                    "mem": s["system"]["mem_used_pct"],
                    "disk": s["quota"]["pct"],
                })
        except Exception:                                    # noqa
            pass
        time.sleep(60)


threading.Thread(target=sampler, daemon=True).start()
# 启动时先采一个点，避免图表空白
try:
    _s0 = collect()
    _history.append({"t": _s0["ts"], "load": _s0["system"]["load1"],
                     "mem": _s0["system"]["mem_used_pct"], "disk": _s0["quota"]["pct"]})
except Exception:                                            # noqa
    pass


# ---------- 登录守卫 ----------
#: 失败锁定：来源 IP -> [(时间戳)...]，15 分钟内 5 次失败锁 15 分钟
_LOCK = {"hits": {}, "guard": threading.Lock()}
LOCK_MAX = 5
LOCK_WINDOW = 15 * 60
LOCK_BAN = 15 * 60


def _fail(ip):
    with _LOCK["guard"]:
        now = time.time()
        hits = _LOCK["hits"].get(ip, [])
        hits = [t for t in hits if now - t < LOCK_WINDOW]
        hits.append(now)
        _LOCK["hits"][ip] = hits


def _reset_fail(ip):
    with _LOCK["guard"]:
        _LOCK["hits"].pop(ip, None)


def _locked(ip):
    with _LOCK["guard"]:
        now = time.time()
        hits = _LOCK["hits"].get(ip, [])
        hits = [t for t in hits if now - t < LOCK_WINDOW]
        _LOCK["hits"][ip] = hits
        if len(hits) >= LOCK_MAX:
            oldest = hits[0]
            left = int(LOCK_BAN - (now - oldest))
            return True, max(left, 1)
        return False, 0


@app.before_request
def _auth_guard():
    if not AUTH_ENABLED:
        return
    p = request.path
    if p == "/login" or p.startswith("/static/"):
        return
    if p in ("/api/login", "/api/change_password", "/api/logout"):
        return
    if not session.get("authed"):
        if p.startswith("/api/") or p.startswith("/proxy/"):
            return jsonify({"ok": False, "need_auth": True,
                            "error": "未登录或会话已过期"}), 401
        return  # 非 API（如首页 HTML）照常返回，前端会弹登录层


# ---------- API ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/overview")
def api_overview():
    try:
        snap = collect()
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500
    with _lock:
        snap["history"] = list(_history)
    snap["ok"] = True
    return jsonify(snap)


@app.route("/api/probe", methods=["GET", "POST"])
def api_probe():
    """
    活体探测：分两级，默认只做"零成本"那一级。
      L1 进程可达 —— 能执行 hermes --version 吗
      L2 数据可写 —— 记忆目录能落盘吗（写不进去 = 调教全部白费）
      L3 模型连通 —— 真正跑一轮（烧 token），需带 ?deep=1 才执行
    """
    deep = (request.args.get("deep") == "1") or \
           ((request.get_json(silent=True) or {}).get("deep") is True)
    steps, ok = [], True
    t0 = time.time()

    # L1 进程/容器可达
    rc, out, err = hermes_exec(["hermes", "--version"], timeout=30)
    ver = (out or err).strip().splitlines()[0] if (out or err) else ""
    steps.append({"name": "进程可达", "ok": rc == 0, "detail": ver[:120] or f"退出码 {rc}"})
    ok = ok and rc == 0

    # L2 数据目录可写（docker 模式要进到 Hermes 容器里试，否则测的是工作台自己的挂载）
    if MODE == "docker":
        rc2, out2, err2 = hermes_exec(
            ["sh", "-c", f"touch '{HERMES_DIR}/.dashboard_probe.tmp' "
                         f"&& rm -f '{HERMES_DIR}/.dashboard_probe.tmp' && echo WRITABLE"],
            timeout=30)
        steps.append({"name": "数据可写", "ok": rc2 == 0,
                      "detail": ((out2 or err2)[:160] or f"退出码 {rc2}")})
        ok = ok and rc2 == 0
    else:
        probe_file = os.path.join(HERMES_DIR, ".dashboard_probe.tmp")
        try:
            with open(probe_file, "w") as f:
                f.write(str(int(time.time())))
            os.remove(probe_file)
            steps.append({"name": "数据可写", "ok": True,
                          "detail": f"{HERMES_DIR} 写入/删除正常"})
        except OSError as e:
            if e.errno == 30:                                # EROFS 只读文件系统
                steps.append({"name": "数据可写", "ok": True,
                              "detail": f"{HERMES_DIR} 是只读挂载（工作台 ro 挂载属预期，"
                                        f"不代表 Hermes 写不了）"})
            else:
                ok = False
                steps.append({"name": "数据可写", "ok": False,
                              "detail": str(e)[:160]})
        except Exception as e:                               # noqa
            ok = False
            steps.append({"name": "数据可写", "ok": False, "detail": str(e)[:160]})

    # L3 模型连通（烧 token，默认不跑）
    if deep and ok:
        rc3, out3, err3 = hermes_exec(["hermes", "run", "回复两个字：正常"], timeout=120)
        steps.append({"name": "模型连通", "ok": rc3 == 0,
                      "detail": ((out3 or err3)[:200] or f"退出码 {rc3}")})
        ok = ok and rc3 == 0

    return jsonify({"ok": ok, "ms": int((time.time() - t0) * 1000),
                    "deep": deep, "steps": steps})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """转发对话到 Hermes"""
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "空消息"}), 400
    if len(msg) > 4000:
        return jsonify({"ok": False, "error": "消息过长"}), 400

    t0 = time.time()
    rc, out, err = hermes_exec(["hermes", "run", msg])
    text = out if out else err
    if rc != 0 and not text:
        text = f"（执行失败，退出码 {rc}）"
    return jsonify({
        "ok": rc == 0,
        "reply": text,
        "ms": int((time.time() - t0) * 1000),
    })


@app.route("/api/skills")
def api_skills():
    """列出技能名（从目录读，不进 Hermes）"""
    root = os.path.join(HERMES_DIR, "skills")
    items = []
    if os.path.isdir(root):
        try:
            for name in sorted(os.listdir(root)):
                p = os.path.join(root, name)
                if os.path.isdir(p) and not name.startswith("."):
                    desc = ""
                    sf = os.path.join(p, "SKILL.md")
                    if os.path.isfile(sf):
                        try:
                            with open(sf, encoding="utf-8", errors="ignore") as f:
                                head = f.read(1500)
                            m = re.search(r"^description:\s*(.+)$", head, re.M)
                            if m:
                                desc = m.group(1).strip()[:160]
                        except Exception:                    # noqa
                            pass
                    items.append({"name": name, "desc": desc})
        except Exception:                                    # noqa
            pass
    return jsonify({"ok": True, "items": items})


@app.route("/api/memories")
def api_memories():
    """列出记忆文件及大小"""
    root = os.path.join(HERMES_DIR, "memories")
    items = []
    if os.path.isdir(root):
        try:
            for f in sorted(os.listdir(root)):
                p = os.path.join(root, f)
                if os.path.isfile(p):
                    items.append({"name": f, "kb": round(os.path.getsize(p) / 1024, 1)})
        except Exception:                                    # noqa
            pass
    return jsonify({"ok": True, "items": items})


SCAN_SCRIPTS = {
    "health": "health-check.sh",
    "security": "security-check.sh",
}
SCRIPT_DIR = os.getenv("SCRIPT_DIR", os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 配置管理 API（让"不进后台改东西"成为可能）
# ============================================================

def _actor():
    return request.headers.get("X-Forwarded-For") or (request.remote_addr or "-")


def _writable_guard():
    if READ_ONLY:
        return jsonify({"ok": False,
                        "error": "工作台处于只读模式（DASH_READ_ONLY=1）"}), 403
    if not os.access(HERMES_DIR, os.W_OK):
        return jsonify({"ok": False,
                        "error": f"{HERMES_DIR} 不可写 —— 请把挂载从 :ro 改成 :rw，"
                                 f"或改用宿主机部署（见 README）"}), 403
    return None


@app.route("/api/files")
def api_files():
    try:
        return jsonify({"ok": True, "items": ctl.list_editable(HERMES_DIR),
                        "readonly": READ_ONLY})
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/file")
def api_file_get():
    rel = request.args.get("path", "")
    try:
        return jsonify({"ok": True, **ctl.read_file(HERMES_DIR, rel)})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/file", methods=["POST"])
def api_file_post():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    rel, content = d.get("path", ""), d.get("content", "")
    try:
        r = ctl.write_file(HERMES_DIR, rel, content, actor=_actor())
        return jsonify({"ok": True, **r,
                        "restart_required": rel in ("config.yaml", ".env")})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backups")
def api_backups():
    rel = request.args.get("path", "")
    try:
        return jsonify({"ok": True, "items": ctl.list_backups(HERMES_DIR, rel)})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/rollback", methods=["POST"])
def api_rollback():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        ctl.rollback(HERMES_DIR, d.get("path", ""), d.get("backup", ""),
                     actor=_actor())
        return jsonify({"ok": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------- 工作区文件树（不限白名单，任意文本文件）----------
@app.route("/api/workspace")
def api_workspace():
    rel = request.args.get("path", "")
    try:
        return jsonify({"ok": True, "readonly": READ_ONLY,
                        **ctl.ws_list_dir(HERMES_DIR, rel)})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/workspace/file")
def api_workspace_file_get():
    rel = request.args.get("path", "")
    try:
        return jsonify({"ok": True, **ctl.ws_read_file(HERMES_DIR, rel)})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/workspace/file", methods=["POST"])
def api_workspace_file_post():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    rel, content = d.get("path", ""), d.get("content", "")
    try:
        r = ctl.ws_write_file(HERMES_DIR, rel, content, actor=_actor())
        return jsonify({"ok": True, **r})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/audit")
def api_audit():
    return jsonify({"ok": True, "items": ctl.read_audit(HERMES_DIR, 120)})


# ---------- MCP ----------
@app.route("/api/mcp")
def api_mcp_get():
    try:
        return jsonify({"ok": True, **ctl.mcp_list(HERMES_DIR)})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mcp", methods=["POST"])
def api_mcp_post():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    env = d.get("env") or {}
    if not isinstance(env, dict):
        return jsonify({"ok": False, "error": "env 必须是对象"}), 400
    try:
        ctl.mcp_save(HERMES_DIR, d.get("name", ""), d.get("command", ""),
                     d.get("args", ""), bool(d.get("enabled", True)),
                     env, actor=_actor())
        return jsonify({"ok": True, "reload_hint": "MCP 改动可执行 /api/mcp/reload 热加载"})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/mcp/delete", methods=["POST"])
def api_mcp_delete():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        ctl.mcp_delete(HERMES_DIR, d.get("name", ""), actor=_actor())
        return jsonify({"ok": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/mcp/toggle", methods=["POST"])
def api_mcp_toggle():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        ctl.mcp_toggle(HERMES_DIR, d.get("name", ""),
                       bool(d.get("enabled", True)), actor=_actor())
        return jsonify({"ok": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/mcp/reload", methods=["POST"])
def api_mcp_reload():
    try:
        r = ctl.reload_mcp(MODE, CONTAINER, actor=_actor(), base=HERMES_DIR)
        return jsonify({"ok": r["ok"], "output": r["output"]})
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mcp/test", methods=["POST"])
def api_mcp_test():
    d = request.get_json(silent=True) or {}
    name = d.get("name", "")
    try:
        r = ctl.mcp_test(MODE, CONTAINER, name)
        return jsonify({"ok": True, **r})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------- .env / Provider ----------
@app.route("/api/env")
def api_env_get():
    try:
        return jsonify({"ok": True, **ctl.env_list(HERMES_DIR)})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/env", methods=["POST"])
def api_env_post():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        r = ctl.env_save(HERMES_DIR, d.get("updates") or {}, actor=_actor())
        return jsonify({"ok": True, **r, "restart_required": r.get("changed")})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/providers")
def api_providers():
    return jsonify({"ok": True, "items": ctl.PROVIDERS})


@app.route("/api/providers/apply", methods=["POST"])
def api_provider_apply():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        r = ctl.apply_provider(HERMES_DIR, d.get("provider", ""),
                               d.get("api_key", ""), actor=_actor())
        return jsonify({"ok": True, **r, "restart_required": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------- 技能 / cron ----------
@app.route("/api/skills/toggle", methods=["POST"])
def api_skill_toggle():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        ctl.skill_toggle(HERMES_DIR, d.get("name", ""),
                         bool(d.get("enable", True)), actor=_actor())
        return jsonify({"ok": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/skills/archived")
def api_skills_archived():
    return jsonify({"ok": True, "items": ctl.archived_skills(HERMES_DIR)})


@app.route("/api/skills/install", methods=["POST"])
def api_skill_install():
    """从 Skills Hub 安装。走 hermes CLI，不在网页里拼 shell。"""
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not re.match(r"^[A-Za-z0-9_\-/\.]{1,80}$", name):
        return jsonify({"ok": False, "error": "技能名不合法"}), 400
    rc, out, err = hermes_exec(["hermes", "skills", "install", name], timeout=180)
    ctl.audit(HERMES_DIR, "skill.install", f"{name} rc={rc}", _actor())
    return jsonify({"ok": rc == 0, "output": (out or err)[:1200]})


@app.route("/api/cron")
def api_cron():
    return jsonify({"ok": True, "items": ctl.cron_list(HERMES_DIR)})


@app.route("/api/cron/toggle", methods=["POST"])
def api_cron_toggle():
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        ctl.cron_toggle(HERMES_DIR, d.get("name", ""),
                        bool(d.get("enable", True)), actor=_actor())
        return jsonify({"ok": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------- 系统动作 ----------
@app.route("/api/action", methods=["POST"])
def api_action():
    """restart / upgrade / reload-mcp —— 全部记审计"""
    d = request.get_json(silent=True) or {}
    act = d.get("action", "")
    if DANGER_TOKEN and d.get("token") != DANGER_TOKEN:
        return jsonify({"ok": False, "error": "危险操作令牌不正确"}), 403
    try:
        if act == "restart":
            r = ctl.restart_hermes(MODE, CONTAINER, _actor(), HERMES_DIR)
        elif act == "reload-mcp":
            r = ctl.reload_mcp(MODE, CONTAINER, _actor(), HERMES_DIR)
        elif act == "upgrade":
            r = ctl.upgrade_hermes(MODE, CONTAINER, _actor(), HERMES_DIR, COMPOSE_DIR)
        else:
            return jsonify({"ok": False, "error": "未知动作"}), 400
        return jsonify({"ok": r["ok"], "output": r.get("output", "")})
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# 对话接口配置（provider / 密钥 / base_url / 模型）
# ============================================================

@app.route("/api/chatapi", methods=["GET", "POST"])
def api_chatapi():
    if request.method == "GET":
        try:
            return jsonify({"ok": True, **ctl.chat_api_get(HERMES_DIR)})
        except ctl.CtlError as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        r = ctl.chat_api_save(HERMES_DIR, d.get("provider", ""),
                              d.get("api_key", ""), d.get("model", ""),
                              d.get("base_url", ""), actor=_actor())
        return jsonify({"ok": True, **r, "restart_required": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# 成本 / 预算 / 告警
# ============================================================

@app.route("/api/cost")
def api_cost():
    try:
        r = costmod.report(HERMES_DIR, BUDGET_DAILY, BUDGET_MONTHLY)
        return jsonify({"ok": True, **r})
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/cost/record", methods=["POST"])
def api_cost_record():
    """主动上报一条用量（当 Hermes 日志里没有 usage 时用这个）"""
    d = request.get_json(silent=True) or {}
    try:
        row = costmod.record(HERMES_DIR, d.get("model", "unknown"),
                             int(d.get("in") or 0), int(d.get("out") or 0),
                             d.get("note", ""))
        return jsonify({"ok": True, "row": row})
    except (TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/cost/pricing", methods=["GET", "POST"])
def api_pricing():
    if request.method == "GET":
        return jsonify({"ok": True, "pricing": costmod.load_pricing(HERMES_DIR),
                        "default": costmod.DEFAULT_PRICING})
    g = _writable_guard()
    if g:
        return g
    try:
        costmod.save_pricing(HERMES_DIR, request.get_json(silent=True) or {})
        ctl.audit(HERMES_DIR, "pricing.save", "更新价格表", _actor())
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/notify", methods=["GET", "POST"])
def api_notify():
    if request.method == "GET":
        return jsonify({"ok": True, "config": notify.mask(notify.load(HERMES_DIR)),
                        "types": notify.CHANNEL_TYPES,
                        "schema": notify.schema(),
                        "alerts": notify.read_alerts(HERMES_DIR, 30)})
    g = _writable_guard()
    if g:
        return g
    try:
        notify.save(HERMES_DIR, request.get_json(silent=True) or {})
        ctl.audit(HERMES_DIR, "notify.save", "更新告警配置", _actor())
        return jsonify({"ok": True})
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():
    """测试推送 —— 不进冷却"""
    res = notify.broadcast(HERMES_DIR, "test",
                           "【Hermes 工作台】测试告警",
                           "这是一条测试消息。收到说明渠道配置正确。",
                           force=True)
    if not res:
        return jsonify({"ok": False, "error": "没有启用任何推送渠道"})
    notify.log_alert(HERMES_DIR, "test", "【测试】告警渠道连通性检查", res)
    return jsonify({"ok": all(r[1] for r in res),
                    "results": [{"channel": n, "ok": o, "msg": m} for n, o, m in res]})


def alert_watchdog():
    """
    后台巡检：每 ALERT_INTERVAL 秒跑一次，异常才推。
    冷却由 notify 层控制 —— 同一类问题不会反复打扰你。
    """
    while True:
        time.sleep(ALERT_INTERVAL)
        try:
            cfg = notify.load(HERMES_DIR)
            rules = cfg.get("rules") or {}
            if not cfg.get("channels"):
                continue

            snap = collect()
            pushes = []

            # 1) 进程挂了
            if rules.get("down", True) and not snap["container"]["alive"]:
                pushes.append(("down", "Hermes 已停止运行",
                               f"状态：{snap['container']['status']}\n"
                               f"模式：{snap['container']['mode']}"))

            # 2) 配额
            pct = snap["quota"]["pct"]
            if rules.get("quota", True) and pct >= 90:
                pushes.append(("quota", f"配额即将用尽（{pct}%）",
                               f"已用 {snap['quota']['used_mb']}MB / "
                               f"{snap['quota']['limit_mb']}MB\n"
                               f"写满后所有记忆与配置更新都会失败"))

            # 3) 24h 错误
            errs = snap["logs"]["errors_24h"]
            if rules.get("errors", True) and errs > 50:
                pushes.append(("errors", f"24h 内 {errs} 条错误",
                               "\n".join(snap["logs"]["samples"][:5])))

            # 4) 预算
            if rules.get("budget", True) and (BUDGET_DAILY or BUDGET_MONTHLY):
                try:
                    rep = costmod.report(HERMES_DIR, BUDGET_DAILY, BUDGET_MONTHLY)
                    b = rep["budget"]
                    if b["level"] in ("warn", "over"):
                        scope = "日" if BUDGET_DAILY else "月"
                        pushes.append((
                            "budget",
                            f"{scope}预算已用 {b['pct']}%"
                            f"{'（超支）' if b['level'] == 'over' else ''}",
                            f"今日 {b['used_today']} 元，本月 {b['used_month']} 元\n"
                            f"日预算 {BUDGET_DAILY or '—'}，月预算 {BUDGET_MONTHLY or '—'}"))
                except Exception:                            # noqa
                    pass

            for key, title, body in pushes:
                r = notify.broadcast(HERMES_DIR, key, title, body)
                if r:
                    notify.log_alert(HERMES_DIR, key, title, r)
        except Exception:                                    # noqa
            pass                                 # 巡检线程绝不能把工作台带崩


threading.Thread(target=alert_watchdog, daemon=True).start()


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """跑现成的巡检脚本（health-check.sh / security-check.sh）"""
    kind = (request.get_json(silent=True) or {}).get("kind", "health")
    fname = SCAN_SCRIPTS.get(kind)
    if not fname:
        return jsonify({"ok": False, "error": "未知巡检类型"}), 400
    path = os.path.join(SCRIPT_DIR, fname)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": f"未找到脚本：{path}",
                        "hint": "把脚本放到工作台同目录，或用 SCRIPT_DIR 指定"}), 404
    t0 = time.time()
    rc, out, err = _run(["bash", path], timeout=120)
    text = ((out or "") + ("\n" + err if err else "")).strip()
    return jsonify({"ok": True, "rc": rc, "name": fname,
                    "ms": int((time.time() - t0) * 1000),
                    "output": text[:12000] or "（脚本无输出 —— healthy 时 health-check.sh 就是静默的）"})


@app.route("/api/config")
def api_config():
    return jsonify({
        "ok": True,
        "hermes_dir": HERMES_DIR,
        "mode": MODE,
        "container": CONTAINER,
        "quota_mb": QUOTA_MB,
        "readonly": READ_ONLY,
        "writable": os.access(HERMES_DIR, os.W_OK),
        "has_yaml": ctl.HAS_YAML,
        "danger_token_set": bool(DANGER_TOKEN),
        "auth_enabled": AUTH_ENABLED,
        "must_change": authmod.needs_change(HERMES_DIR) if AUTH_ENABLED else False,
        "compose_dir": COMPOSE_DIR,
        "budget": {"daily": BUDGET_DAILY, "monthly": BUDGET_MONTHLY},
        "scripts": {k: os.path.isfile(os.path.join(SCRIPT_DIR, v))
                    for k, v in SCAN_SCRIPTS.items()},
        "script_dir": SCRIPT_DIR,
    })


# ============================================================
# 登录 / 改密 / 登出
# ============================================================

@app.route("/api/login", methods=["POST"])
def api_login():
    if not AUTH_ENABLED:
        session["authed"] = True
        return jsonify({"ok": True, "must_change": False, "auth_disabled": True})
    ip = request.remote_addr or "-"
    banned, left = _locked(ip)
    if banned:
        return jsonify({"ok": False,
                        "error": f"尝试次数过多，请 {left} 秒后再试"}), 429
    d = request.get_json(silent=True) or {}
    pw = (d.get("password") or "").strip()
    if not pw:
        return jsonify({"ok": False, "error": "请输入密码"}), 400
    if not authmod.verify_login(HERMES_DIR, pw):
        _fail(ip)
        return jsonify({"ok": False, "error": "密码错误"})
    _reset_fail(ip)
    session["authed"] = True
    session.permanent = True
    return jsonify({"ok": True, "must_change": authmod.needs_change(HERMES_DIR)})


@app.route("/api/change_password", methods=["POST"])
def api_change_password():
    if not session.get("authed"):
        return jsonify({"ok": False, "need_auth": True}), 401
    d = request.get_json(silent=True) or {}
    old = d.get("old", "")
    new = d.get("new", "")
    if len(new) < 8:
        return jsonify({"ok": False, "error": "新密码至少 8 位"}), 400
    a = authmod.load_auth(HERMES_DIR)
    if not a or not authmod.verify(old, a.get("hash", "")):
        return jsonify({"ok": False, "error": "原密码错误"}), 400
    authmod.set_password(HERMES_DIR, new)
    return jsonify({"ok": True})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# ============================================================
# 版本 / 升级 / 自检 / Hermes 命令台 / 配置开关
# ============================================================

@app.route("/api/version")
def api_version():
    try:
        return jsonify({"ok": True, "auth": AUTH_ENABLED,
                        "must_change": authmod.needs_change(HERMES_DIR)
                        if AUTH_ENABLED else False,
                        **ctl.version_info(HERMES_DIR)})
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/dash-update", methods=["POST"])
def api_dash_update():
    """升级工作台自身（git pull），成功后后台重启以加载新代码。"""
    r = ctl.dash_update(HERMES_DIR, actor=_actor())
    if r.get("ok") and r.get("restart"):
        def _bye():
            time.sleep(1.2)
            os._exit(0)
        threading.Thread(target=_bye, daemon=True).start()
    return jsonify({"ok": r.get("ok", False), **r})


@app.route("/api/doctor", methods=["POST"])
def api_doctor():
    try:
        return jsonify({"ok": True,
                        **ctl.doctor(HERMES_DIR, mode=MODE, container=CONTAINER)})
    except Exception as e:                                   # noqa
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/hermes", methods=["POST"])
def api_hermes():
    """Hermes 命令台：跑白名单内的 hermes 子命令。"""
    d = request.get_json(silent=True) or {}
    args = d.get("args") or []
    if not isinstance(args, list):
        args = [str(args)]
    ok, err = ctl.check_hermes_args(args)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    rc, out, errs = ctl.hermes_run(args, base=HERMES_DIR, mode=MODE,
                                  container=CONTAINER)
    ctl.audit(HERMES_DIR, "hermes.cmd", " ".join(str(x) for x in args),
              _actor())
    return jsonify({"ok": rc == 0, "rc": rc,
                    "output": ((out or "") + ("\n" + errs if errs else ""))[:4000]})


@app.route("/api/cfg", methods=["GET", "POST"])
def api_cfg():
    if request.method == "GET":
        try:
            return jsonify({"ok": True, **ctl.cfg_read(HERMES_DIR)})
        except ctl.CtlError as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        r = ctl.cfg_set(HERMES_DIR, d.get("path", ""), d.get("value"),
                       actor=_actor())
        return jsonify({"ok": True, **r, "restart_required": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ============================================================
# 流式对话（SSE）
# ============================================================
@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    """流式对话：用 SSE 逐 token 返回 Hermes 回复 + 工具调用事件。"""
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "空消息"}), 400
    if len(msg) > 4000:
        return jsonify({"ok": False, "error": "消息过长"}), 400

    def generate():
        t0 = time.time()
        try:
            # hermes run --json --stream 输出 JSONL，每行一个事件
            cmd = (["docker", "exec", CONTAINER, "hermes", "run", "--json", "--stream", msg]
                   if MODE == "docker"
                   else ["hermes", "run", "--json", "--stream", msg])
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            import queue, select
            # 逐行读 stdout，解析 JSON 事件，转 SSE
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    # 非 JSON 行当普通文本
                    evt = {"type": "token", "content": line}
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            proc.wait(timeout=CHAT_TIMEOUT)
            rc = proc.returncode
            err = (proc.stderr.read() or "").strip()
        except subprocess.TimeoutExpired:
            proc.kill()
            yield f"data: {json.dumps({'type':'error','content':'执行超时'}, ensure_ascii=False)}\n\n"
            return
        except FileNotFoundError:
            yield f"data: {json.dumps({'type':'error','content':'hermes 命令不存在'}, ensure_ascii=False)}\n\n"
            return
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','content':str(e)}, ensure_ascii=False)}\n\n"
            return
        ms = int((time.time() - t0) * 1000)
        yield f"data: {json.dumps({'type':'done','ms':ms,'rc':rc}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(generate()),
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ============================================================
# 多会话聊天（消息历史持久化到 HERMES_DIR/sessions）
# ============================================================

@app.route("/api/sessions", methods=["GET", "POST"])
def api_sessions():
    if request.method == "POST":
        g = _writable_guard()
        if g:
            return g
        d = request.get_json(silent=True) or {}
        try:
            s = ctl.create_session(HERMES_DIR, d.get("name", ""), d.get("model", ""))
            return jsonify({"ok": True, "session": s})
        except ctl.CtlError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **ctl.list_sessions(HERMES_DIR)})


@app.route("/api/sessions/<sid>", methods=["GET"])
def api_session_get(sid):
    try:
        s = ctl.get_session(HERMES_DIR, sid)
        return jsonify({"ok": True, **s})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 404


@app.route("/api/sessions/<sid>/rename", methods=["POST"])
def api_session_rename(sid):
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    try:
        s = ctl.rename_session(HERMES_DIR, sid, d.get("name", ""), _actor())
        return jsonify({"ok": True, "session": s})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/sessions/<sid>/delete", methods=["POST"])
def api_session_delete(sid):
    g = _writable_guard()
    if g:
        return g
    try:
        ctl.delete_session(HERMES_DIR, sid, _actor())
        return jsonify({"ok": True})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/sessions/<sid>/chat", methods=["POST"])
def api_session_chat(sid):
    g = _writable_guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    msg = (d.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "空消息"}), 400
    if len(msg) > 4000:
        return jsonify({"ok": False, "error": "消息过长"}), 400
    try:
        ctl.append_message(HERMES_DIR, sid, "me", msg)
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    t0 = time.time()
    rc, out, err = hermes_exec(["hermes", "run", msg])
    text = out if out else err
    if rc != 0 and not text:
        text = f"（执行失败，退出码 {rc}）"
    ms = int((time.time() - t0) * 1000)
    ctl.append_message(HERMES_DIR, sid, "ai", text, ms)
    return jsonify({"ok": rc == 0, "reply": text, "ms": ms})


@app.route("/api/sessions/<sid>/chat/stream", methods=["POST"])
def api_session_chat_stream(sid):
    """流式会话对话：先把用户消息落盘，再逐 token 回流，结束再落盘 AI 回复。"""
    d = request.get_json(silent=True) or {}
    msg = (d.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "空消息"}), 400
    if len(msg) > 4000:
        return jsonify({"ok": False, "error": "消息过长"}), 400
    try:
        ctl.append_message(HERMES_DIR, sid, "me", msg)
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 404

    def generate():
        t0 = time.time()
        ai_text = ""
        rc = 1
        try:
            cmd = (["docker", "exec", CONTAINER, "hermes", "run", "--json", "--stream", msg]
                   if MODE == "docker"
                   else ["hermes", "run", "--json", "--stream", msg])
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    evt = {"type": "token", "content": line}
                if evt.get("type") == "token":
                    ai_text += evt.get("content", "")
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            proc.wait(timeout=CHAT_TIMEOUT)
            rc = proc.returncode
            if rc != 0 and not ai_text:
                ai_text = (proc.stderr.read() or "").strip() or f"（执行失败，退出码 {rc}）"
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:                                       # noqa
                pass
            rc = 124
            ai_text += "\n[执行超时]"
            yield f"data: {json.dumps({'type': 'error', 'content': '执行超时'}, ensure_ascii=False)}\n\n"
        except FileNotFoundError:
            rc = 127
            yield f"data: {json.dumps({'type': 'error', 'content': 'hermes 命令不存在'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            rc = 1
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        ms = int((time.time() - t0) * 1000)
        try:
            ctl.append_message(HERMES_DIR, sid, "ai", ai_text, ms)
        except Exception:                                           # noqa
            pass
        yield f"data: {json.dumps({'type': 'done', 'ms': ms, 'rc': rc}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(generate()),
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ============================================================
# 多智能体编排（agents.yaml）
# ============================================================

@app.route("/api/agents", methods=["GET", "POST"])
def api_agents():
    if request.method == "POST":
        g = _writable_guard()
        if g:
            return g
        d = request.get_json(silent=True) or {}
        try:
            a = ctl.save_agent(HERMES_DIR, d, _actor())
            return jsonify({"ok": True, "agent": a})
        except ctl.CtlError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **ctl.list_agents(HERMES_DIR)})


@app.route("/api/agents/<aid>", methods=["DELETE"])
def api_agent_del(aid):
    g = _writable_guard()
    if g:
        return g
    try:
        r = ctl.delete_agent(HERMES_DIR, aid, _actor())
        return jsonify({"ok": True, **r})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/teams", methods=["GET", "POST"])
def api_teams():
    if request.method == "POST":
        g = _writable_guard()
        if g:
            return g
        d = request.get_json(silent=True) or {}
        try:
            t = ctl.save_team(HERMES_DIR, d, _actor())
            return jsonify({"ok": True, "team": t})
        except ctl.CtlError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **ctl.list_agents(HERMES_DIR)})


@app.route("/api/teams/<tid>", methods=["DELETE"])
def api_team_del(tid):
    g = _writable_guard()
    if g:
        return g
    try:
        r = ctl.delete_team(HERMES_DIR, tid, _actor())
        return jsonify({"ok": True, **r})
    except ctl.CtlError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/teams/<tid>/run/stream", methods=["POST"])
def api_team_run(tid):
    """流式编排：按团队模式依次/流水线驱动各智能体，逐 token 回流。"""
    d = request.get_json(silent=True) or {}
    task = (d.get("task") or "").strip()
    if not task:
        return jsonify({"ok": False, "error": "空任务"}), 400
    info = ctl.list_agents(HERMES_DIR)
    team = next((t for t in info.get("teams", []) if t.get("id") == tid), None)
    if not team:
        return jsonify({"ok": False, "error": "团队不存在"}), 404
    agents_map = {a["id"]: a for a in info.get("agents", [])}
    members = [agents_map[x] for x in team.get("agents", []) if x in agents_map]
    if not members:
        return jsonify({"ok": False, "error": "团队没有可用的智能体成员"}), 400
    mode = team.get("mode", "pipeline")

    def generate():
        t0 = time.time()
        prev = ""
        yield f"data: {json.dumps({'type': 'team_start', 'team': team.get('name', tid), 'mode': mode, 'n': len(members)}, ensure_ascii=False)}\n\n"
        for ag in members:
            prompt = ctl.build_agent_prompt(ag, task, prev if mode == "pipeline" else "")
            yield f"data: {json.dumps({'type': 'agent_start', 'agent': ag.get('name', ag['id']), 'id': ag['id']}, ensure_ascii=False)}\n\n"
            atext = ""
            rc = 1
            try:
                cmd = ctl.agent_run_cmd(prompt, MODE, CONTAINER)
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        evt = {"type": "token", "content": line}
                    if evt.get("type") == "token":
                        atext += evt.get("content", "")
                        yield f"data: {json.dumps({'type': 'token', 'aid': ag['id'], 'content': evt.get('content', '')}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                proc.wait(timeout=CHAT_TIMEOUT)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:                               # noqa
                    pass
                rc = 124
                yield f"data: {json.dumps({'type': 'error', 'content': '执行超时'}, ensure_ascii=False)}\n\n"
            except FileNotFoundError:
                rc = 127
                yield f"data: {json.dumps({'type': 'error', 'content': 'hermes 命令不存在'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                rc = 1
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'agent_done', 'aid': ag['id'], 'rc': rc}, ensure_ascii=False)}\n\n"
            prev = atext
        ms = int((time.time() - t0) * 1000)
        yield f"data: {json.dumps({'type': 'team_done', 'ms': ms}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(generate()),
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ============================================================
# 代理层：转发到 Hermes 官方 FastAPI 仪表盘后端
# ============================================================
import requests as _requests

#: hop-by-hop 头不可转发
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate",
                "proxy-authorization", "te", "trailers",
                "transfer-encoding", "upgrade", "content-encoding",
                "content-length"}


@app.route("/proxy/", defaults={"path": ""})
@app.route("/proxy/<path:path>")
def proxy_hermes(path):
    """通用代理：转发到 Hermes 官方仪表盘后端（FastAPI :9119）。

    自动继承 before_request 鉴权守卫，未登录 401。
    支持流式（SSE / chunked）、静态资源（HTML/JS/CSS）、API JSON。
    """
    target = f"{HERMES_API}/{path}" if path else HERMES_API + "/"

    # 透传 query string
    if request.query_string:
        target += "?" + request.query_string.decode("utf-8", "ignore")

    # 构造转发 headers
    fwd_headers = {}
    for k, v in request.headers:
        kl = k.lower()
        if kl in _HOP_BY_HOP or kl == "host":
            continue
        fwd_headers[k] = v
    # 官方后端认证 token
    if HERMES_API_TOKEN:
        fwd_headers["X-Hermes-Session-Token"] = HERMES_API_TOKEN

    # 取 body
    body = request.get_data() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None

    try:
        resp = _requests.request(
            request.method, target,
            headers=fwd_headers,
            data=body,
            stream=True,
            timeout=PROXY_TIMEOUT,
            allow_redirects=False,
        )
    except _requests.ConnectionError:
        # 官方后端未启动
        return (jsonify({"ok": False,
                         "error": "Hermes 官方仪表盘未启动。请在 Hermes 环境执行 `hermes dashboard` 或设 HERMES_API 环境变量。"}),
                502)
    except _requests.Timeout:
        return jsonify({"ok": False, "error": "代理请求超时"}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": f"代理错误：{e}"}), 502

    # 过滤 hop-by-hop 响应头
    out_headers = [(k, v) for k, v in resp.headers.items()
                   if k.lower() not in _HOP_BY_HOP]

    return Response(stream_with_context(resp.iter_content(chunk_size=8192)),
                    status=resp.status_code,
                    headers=out_headers)


if __name__ == "__main__":
    # threaded=True：开发服务器也能扛并发，避免长对话阻塞采样/读取
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")),
            debug=False, threaded=True)
