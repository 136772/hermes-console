#!/usr/bin/env python3
"""
Hermes 控制层：让工作台能"改配置"，而不只是"看配置"。

设计前提：网页改配置 = 给自己开了一个远程改生产系统的口子。
所以这里每一条写路径都必须同时满足四件事：
  1. 白名单 + 防目录穿越   —— 只能动该动的文件
  2. 写前自动备份 + 可回滚 —— 改崩了必须能一秒回来
  3. 语法校验先行          —— YAML/JSON 写错绝不落盘
  4. 全量审计              —— 谁在什么时候把什么从哪改到哪

任何一条不满足的操作，宁可不做。
"""
import os
import re
import io
import json
import time
import shutil
import difflib
import threading
import subprocess
import urllib.request
from datetime import datetime

try:
    from ruamel.yaml import YAML
    _yaml = YAML()
    _yaml.preserve_quotes = True
    _yaml.indent(mapping=2, sequence=4, offset=2)
    HAS_YAML = True
except ImportError:                                          # noqa
    HAS_YAML = False


# ============================================================
# 0. 常量与白名单
# ============================================================

#: 允许编辑的相对路径（相对 HERMES_DIR）。只列"配置"，不列"数据"。
EDITABLE = [
    ("config.yaml",    "主配置：模型、终端后端、审批模式、MCP"),
    (".env",           "密钥与 Provider（API Key 在页面上脱敏显示）"),
    ("SOUL.md",        "人格：它是谁、怎么说话、不做什么"),
    ("AGENTS.md",      "项目级约定（局部于目录）"),
    ("USER.md",        "关于你的事实"),
    ("PREFS.md",       "偏好与红线"),
    ("PROJECTS.md",    "在做什么项目"),
    ("MEMORY.md",      "长期记忆索引"),
]

#: 正则白名单（覆盖 memories/ 与 skills/ 下的同类文件）
EDITABLE_RE = [
    re.compile(r"^memories/[A-Za-z0-9_\-\u4e00-\u9fa5]+\.md$"),
    re.compile(r"^skills/[A-Za-z0-9_\-]+/SKILL\.md$"),
    re.compile(r"^cron/[A-Za-z0-9_\-]+$"),
]

#: 这些键在页面上永远不明文显示
SECRET_RE = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|ACCESS|PRIVATE)", re.I)

MAX_FILE_BYTES = 512 * 1024        # 单文件上限 512KB，防止把日志当配置写
BACKUP_KEEP = 30                   # 每个文件最多保留 30 份历史

#: 写锁：同一文件不允许并发写（两个标签页同时保存会互相覆盖）
_locks = {}
_locks_guard = threading.Lock()


def _lock_for(rel):
    with _locks_guard:
        if rel not in _locks:
            _locks[rel] = threading.Lock()
        return _locks[rel]


# ============================================================
# 1. 路径安全
# ============================================================

class CtlError(Exception):
    """可控错误：消息可以直接给用户看"""
    pass


def safe_path(base, rel):
    """
    把相对路径解析成绝对路径，并确保它没有跳出 base。
    目录穿越（../../etc/passwd）在这一层被彻底掐死。
    """
    if not rel or rel.strip() != rel:
        raise CtlError("非法路径")
    if rel.startswith("/") or rel.startswith("~"):
        raise CtlError("路径必须是相对路径")
    if ".." in rel.replace("\\", "/").split("/"):
        raise CtlError("路径不允许包含 ..")
    if "\x00" in rel:
        raise CtlError("非法字符")

    base_real = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base_real, rel))
    if full != base_real and not full.startswith(base_real + os.sep):
        raise CtlError("路径越界，已拒绝")
    return full


def check_editable(rel):
    """是否在白名单内"""
    if rel in [a for a, _ in EDITABLE]:
        return True
    for r in EDITABLE_RE:
        if r.match(rel):
            return True
    return False


# ============================================================
# 2. 备份 / 回滚 / 审计
# ============================================================

def _dash_dir(base):
    d = os.path.join(base, ".dashboard")
    os.makedirs(d, exist_ok=True)
    return d


def backup(base, rel):
    """写前备份，返回备份文件名"""
    src = safe_path(base, rel)
    if not os.path.isfile(src):
        return None
    bdir = os.path.join(_dash_dir(base), "backups",
                        rel.replace("/", "__"))
    os.makedirs(bdir, exist_ok=True)
    # 同一秒内多次修改会撞名 —— 加序号，否则后一次写入会覆盖掉前一次的备份，
    # 而"前一次"往往正是你需要的那份。
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(bdir, f"{stamp}.bak")
    n = 1
    while os.path.exists(dst):
        n += 1
        dst = os.path.join(bdir, f"{stamp}-{n}.bak")
    shutil.copy2(src, dst)

    # 只保留最近 N 份
    try:
        olds = sorted(os.listdir(bdir))[:-BACKUP_KEEP]
        for o in olds:
            os.remove(os.path.join(bdir, o))
    except Exception:                                        # noqa
        pass
    return f"{rel}@{stamp}"


def list_backups(base, rel):
    bdir = os.path.join(_dash_dir(base), "backups", (rel or "").replace("/", "__"))
    if not os.path.isdir(bdir):
        return []
    out = []
    for f in sorted(os.listdir(bdir), reverse=True)[:50]:
        p = os.path.join(bdir, f)
        try:
            out.append({"name": f, "kb": round(os.path.getsize(p) / 1024, 1),
                        "mtime": int(os.path.getmtime(p))})
        except OSError:
            pass
    return out


def rollback(base, rel, backup_name, actor=""):
    """回滚：先把当前状态也备份一份，避免回滚本身不可逆"""
    if not re.match(r"^[\d\-]+\.bak$", backup_name or ""):
        raise CtlError("非法备份名")
    cur = safe_path(base, rel)
    bdir = os.path.join(_dash_dir(base), "backups", rel.replace("/", "__"))
    src = os.path.join(bdir, backup_name)
    if not os.path.isfile(src):
        raise CtlError("备份不存在")
    if os.path.isfile(cur):
        backup(base, rel)                    # 回滚前先存当前状态
    shutil.copy2(src, cur)
    audit(base, "rollback", f"{rel} <- {backup_name}", actor)
    return True


def audit(base, action, detail, actor=""):
    """审计日志：追加写，永不覆盖"""
    try:
        d = _dash_dir(base)
        with open(os.path.join(d, "audit.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "t": int(time.time()),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": action, "detail": detail, "actor": actor or "-",
            }, ensure_ascii=False) + "\n")
    except Exception:                                        # noqa
        pass


def read_audit(base, limit=100):
    p = os.path.join(_dash_dir(base), "audit.log")
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-limit:]
        out = []
        for l in lines:
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
        return list(reversed(out))
    except Exception:                                        # noqa
        return []


# ============================================================
# 3. 文件读写
# ============================================================

def list_editable(base):
    """列出白名单里存在的文件 + 自动发现的记忆/技能/cron"""
    out = []
    for rel, desc in EDITABLE:
        # 记忆类文件实际在 memories/ 下
        for cand in (rel, f"memories/{rel}"):
            p = os.path.join(base, cand)
            if os.path.isfile(p):
                out.append({"path": cand, "desc": desc,
                            "kb": round(os.path.getsize(p) / 1024, 1),
                            "mtime": int(os.path.getmtime(p))})
                break
    # 自动发现
    for sub, rx, kind in (
        ("memories", r"\.md$", "记忆"),
        ("cron", None, "定时任务"),
    ):
        d = os.path.join(base, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.startswith("."):
                continue
            if rx and not re.search(rx, f):
                continue
            rel = f"{sub}/{f}"
            if any(o["path"] == rel for o in out):
                continue
            p = os.path.join(d, f)
            if os.path.isfile(p):
                out.append({"path": rel, "desc": f"{kind}文件",
                            "kb": round(os.path.getsize(p) / 1024, 1),
                            "mtime": int(os.path.getmtime(p))})
    # 技能
    sd = os.path.join(base, "skills")
    if os.path.isdir(sd):
        for s in sorted(os.listdir(sd)):
            if s.startswith("."):
                continue
            p = os.path.join(sd, s, "SKILL.md")
            if os.path.isfile(p):
                out.append({"path": f"skills/{s}/SKILL.md", "desc": "技能定义",
                            "kb": round(os.path.getsize(p) / 1024, 1),
                            "mtime": int(os.path.getmtime(p))})
    return out


def read_file(base, rel):
    if not check_editable(rel):
        raise CtlError(f"该文件不可编辑：{rel}")
    p = safe_path(base, rel)
    if not os.path.isfile(p):
        raise CtlError("文件不存在")
    sz = os.path.getsize(p)
    if sz > MAX_FILE_BYTES:
        raise CtlError(f"文件过大（{sz} 字节），拒绝在网页编辑")
    with open(p, encoding="utf-8", errors="replace") as f:
        content = f.read()
    return {"path": rel, "content": content, "bytes": sz,
            "mtime": int(os.path.getmtime(p)),
            "backups": list_backups(base, rel)}


def write_file(base, rel, content, actor="", validate=True):
    """
    写文件。顺序：白名单 → 语法校验 → 备份 → 落盘 → 审计。
    校验不过绝不落盘 —— 这是"网页改配置"最容易翻车的地方。
    """
    if not check_editable(rel):
        raise CtlError(f"该文件不可编辑：{rel}")
    if content is None:
        raise CtlError("内容为空")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise CtlError("内容超过 512KB，拒绝写入")

    if validate:
        msg = validate_content(rel, content)
        if msg:
            raise CtlError(f"语法校验未通过，已拒绝保存：\n{msg}")

    with _lock_for(rel):
        p = safe_path(base, rel)
        os.makedirs(os.path.dirname(p) or base, exist_ok=True)
        old = ""
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                old = f.read()
        if old == content:
            return {"changed": False, "backup": None, "diff": ""}

        bak = backup(base, rel)
        # 原子写：先写临时文件再 rename，避免写一半崩掉留下半个文件
        tmp = p + ".dashboard.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)

        diff = "".join(difflib.unified_diff(
            old.splitlines(True), content.splitlines(True),
            fromfile=f"旧 {rel}", tofile=f"新 {rel}", n=1))
        audit(base, "write", f"{rel}（{len(diff.splitlines())} 行变更，备份 {bak}）", actor)
        return {"changed": True, "backup": bak, "diff": diff[:8000]}


def validate_content(rel, content):
    """语法校验，返回错误信息或 None"""
    low = rel.lower()
    if low.endswith((".yaml", ".yml")):
        if not HAS_YAML:
            return None                       # 没装库就放过，但会在页面提示
        try:
            list(_yaml.load_all(content))     # 支持多文档
        except Exception as e:                # noqa
            return f"YAML 语法错误：{e}"
    elif low.endswith(".json"):
        try:
            json.loads(content)
        except Exception as e:                # noqa
            return f"JSON 语法错误：{e}"
    return None


# ============================================================
# 3.1 工作区文件树浏览（不限 EDITABLE 白名单，可浏览 base 内任意文本文件）
# ============================================================

#: 工作区编辑器允许打开的文本类型；其余（二进制/大日志）不进编辑器，避免误改。
WS_TEXT_EXT = {
    ".md", ".yaml", ".yml", ".json", ".txt", ".toml", ".ini", ".cfg",
    ".conf", ".env", ".sh", ".bash", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".css", ".html", ".htm", ".csv", ".log", ".xml", ".sql", ".gitignore",
    ".dockerfile", ".lock", ".toml",
}
#: 工作区里直接跳过的目录（我们的备份目录、版本库元数据）
WS_SKIP_DIRS = {".dashboard", ".git"}


def ws_list_dir(base, rel=""):
    """列出 base 下某目录（目录优先，再按名排序）。rel 为空 = 根目录。"""
    full = safe_path(base, rel) if rel else os.path.realpath(base)
    if not os.path.isdir(full):
        raise CtlError(f"不是目录：{rel or '/'}")
    out = []
    for name in sorted(os.listdir(full)):
        if name in WS_SKIP_DIRS:
            continue
        p = os.path.join(full, name)
        is_dir = os.path.isdir(p)
        try:
            st = os.stat(p)
            sz = 0 if is_dir else st.st_size
            mtime = int(st.st_mtime)
        except OSError:
            sz, mtime = 0, 0
        relpath = (rel + "/" + name) if rel else name
        out.append({"name": name, "path": relpath,
                    "type": "dir" if is_dir else "file",
                    "kb": None if is_dir else round(sz / 1024, 1),
                    "mtime": mtime, "hidden": name.startswith(".")})
    out.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    return {"path": rel or "", "items": out}


def _ws_ext_ok(rel):
    ext = os.path.splitext(rel)[1].lower()
    # 无扩展名也放行（Dockerfile、LICENSE 等）；有扩展名必须在白名单内
    return ext in WS_TEXT_EXT or ext == ""


def ws_read_file(base, rel):
    """读工作区内任意文本文件（不卡 EDITABLE 白名单，但卡越界/大小/类型）。"""
    if not rel:
        raise CtlError("未指定文件")
    p = safe_path(base, rel)
    if not os.path.isfile(p):
        raise CtlError("文件不存在")
    if not _ws_ext_ok(rel):
        raise CtlError(f"该类型不在可编辑文本类型内：{os.path.splitext(rel)[1] or '无扩展名'}")
    sz = os.path.getsize(p)
    if sz > MAX_FILE_BYTES:
        raise CtlError(f"文件过大（{sz} 字节），拒绝在网页编辑")
    with open(p, encoding="utf-8", errors="replace") as f:
        content = f.read()
    return {"path": rel, "content": content, "bytes": sz,
            "mtime": int(os.path.getmtime(p)),
            "backups": list_backups(base, rel)}


def ws_write_file(base, rel, content, actor=""):
    """写工作区内任意文本文件（备份 + 校验 + 原子写，与 write_file 同款保护）。"""
    if not rel:
        raise CtlError("未指定文件")
    if content is None:
        raise CtlError("内容为空")
    p = safe_path(base, rel)
    if not _ws_ext_ok(rel):
        raise CtlError(f"该类型不在可编辑文本类型内：{os.path.splitext(rel)[1] or '无扩展名'}")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise CtlError("内容超过 512KB，拒绝写入")
    msg = validate_content(rel, content)
    if msg:
        raise CtlError(f"语法校验未通过，已拒绝保存：\n{msg}")
    with _lock_for(rel):
        os.makedirs(os.path.dirname(p) or base, exist_ok=True)
        old = ""
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                old = f.read()
        if old == content:
            return {"changed": False, "backup": None, "diff": ""}
        bak = backup(base, rel)
        tmp = p + ".dashboard.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)
        diff = "".join(difflib.unified_diff(
            old.splitlines(True), content.splitlines(True),
            fromfile=f"旧 {rel}", tofile=f"新 {rel}", n=1))
        audit(base, "ws.write", f"{rel}（备份 {bak}）", actor)
        return {"changed": True, "backup": bak, "diff": diff[:8000]}


# ============================================================
# 4. MCP 服务器管理（保序保注释地改 config.yaml）
# ============================================================

def _load_cfg(base):
    if not HAS_YAML:
        raise CtlError("缺少 ruamel.yaml，无法安全编辑 config.yaml（pip install ruamel.yaml）")
    p = safe_path(base, "config.yaml")
    if not os.path.isfile(p):
        return None, p
    with open(p, encoding="utf-8") as f:
        return _yaml.load(f), p


def _dump_cfg(cfg, path):
    buf = io.StringIO()
    _yaml.dump(cfg, buf)
    return buf.getvalue()


def mcp_list(base):
    cfg, _ = _load_cfg(base)
    if cfg is None:
        return {"exists": False, "servers": [], "warn": "config.yaml 不存在"}
    servers = cfg.get("mcp_servers") or {}
    if servers is None:
        servers = {}
    out = []
    for name, s in servers.items():
        s = s or {}
        envs = s.get("env") or {}
        out.append({
            "name": name,
            "command": s.get("command", ""),
            "args": " ".join(str(a) for a in (s.get("args") or [])),
            "enabled": bool(s.get("enabled", True)),
            "env_keys": sorted(envs.keys()) if isinstance(envs, dict) else [],
        })
    # 常见坑：写成了 mcp: servers:
    warn = ""
    if not servers and isinstance(cfg.get("mcp"), dict):
        warn = ("检测到你写的是 `mcp:` 而不是 `mcp_servers:` —— "
                "这是最常见的错误，MCP 会静默不生效")
    return {"exists": True, "servers": out, "warn": warn}


def mcp_save(base, name, command, args, enabled, env, actor=""):
    """
    新增/更新一个 MCP 服务器。
    只动 mcp_servers 这一段，其余配置和注释原样保留。
    """
    if not re.match(r"^[A-Za-z0-9_\-]{1,40}$", name or ""):
        raise CtlError("服务器名只能包含字母数字下划线短横线（1-40 字符）")
    cfg, path = _load_cfg(base)
    if cfg is None:
        cfg = {}
    servers = cfg.get("mcp_servers")
    if servers is None:
        servers = {}
        cfg["mcp_servers"] = servers

    node = {"command": command}
    if args:
        node["args"] = [a for a in args.split() if a]
    if not enabled:
        node["enabled"] = False
    if env:
        node["env"] = env
    servers[name] = node

    content = _dump_cfg(cfg, path)
    write_file(base, "config.yaml", content, actor=actor)
    audit(base, "mcp.save", name, actor)
    return True


def mcp_delete(base, name, actor=""):
    cfg, path = _load_cfg(base)
    if cfg is None:
        raise CtlError("config.yaml 不存在")
    servers = cfg.get("mcp_servers") or {}
    if name not in servers:
        raise CtlError(f"不存在 MCP 服务器：{name}")
    del servers[name]
    write_file(base, "config.yaml", _dump_cfg(cfg, path), actor=actor)
    audit(base, "mcp.delete", name, actor)
    return True


def mcp_toggle(base, name, enabled, actor=""):
    cfg, path = _load_cfg(base)
    servers = cfg.get("mcp_servers") or {}
    if name not in servers:
        raise CtlError(f"不存在 MCP 服务器：{name}")
    servers[name] = servers[name] or {}
    if enabled:
        servers[name].pop("enabled", None)
    else:
        servers[name]["enabled"] = False
    write_file(base, "config.yaml", _dump_cfg(cfg, path), actor=actor)
    audit(base, "mcp.toggle", f"{name} -> {'启用' if enabled else '禁用'}", actor)
    return True


def mcp_test(mode, container, name):
    """
    对单个 MCP 服务器做一次连通测试（best-effort）。

    直接复用 run_cmd + docker exec 机制，跑 `hermes mcp test <name>`。
    不同 Hermes 版本子命令可能略有差异——输出原样返回，用户能直接看到发生了什么。
    """
    if not name:
        raise CtlError("未指定服务器名")
    cmd = ["hermes", "mcp", "test", name]
    if mode == "docker":
        rc, out, err = run_cmd(["docker", "exec", container or "hermes"] + cmd,
                               timeout=90)
    else:
        rc, out, err = run_cmd(cmd, timeout=90)
    text = (out or "") + (("\n" + err) if err else "")
    return {"ok": rc == 0, "rc": rc, "output": text[:2000]}


# ============================================================
# 5. .env（密钥脱敏）
# ============================================================

def env_list(base):
    p = safe_path(base, ".env")
    if not os.path.isfile(p):
        return {"exists": False, "items": []}
    items = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            secret = bool(SECRET_RE.search(k))
            if secret and v:
                shown = v[:4] + "•" * 8 + v[-4:] if len(v) > 12 else "•" * 8
            else:
                shown = v
            items.append({"key": k, "value": shown, "secret": secret})
    return {"exists": True, "items": items}


def env_save(base, updates, actor=""):
    """
    更新 .env。约定：secret 字段若值仍是脱敏样式（含 •）或为 __KEEP__，
    表示"不改"，保留原值 —— 否则用户一打开页面保存，所有 Key 就被圆点覆盖了。
    """
    p = safe_path(base, ".env")
    lines = []
    if os.path.isfile(p):
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    original = {}
    order = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            original[k.strip()] = (i, v.strip())
            order.append(k.strip())

    changed = []
    for k, v in (updates or {}).items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k or ""):
            raise CtlError(f"非法环境变量名：{k}")
        v = (v or "").strip()
        if v == "__KEEP__" or "•" in v:
            continue                                  # 保持不变
        if k in original:
            idx, _old = original[k]
            lines[idx] = f"{k}={v}"
        else:
            lines.append(f"{k}={v}")
        changed.append(k if not SECRET_RE.search(k) else f"{k}(密文)")

    if not changed:
        return {"changed": False, "changed_keys": []}
    content = "\n".join(lines) + "\n"
    write_file(base, ".env", content, actor=actor, validate=False)
    audit(base, "env.save", ", ".join(changed), actor)
    return {"changed": True, "changed_keys": changed}


# ============================================================
# 6. 技能管理
# ============================================================

def skill_toggle(base, name, enable, actor=""):
    """
    禁用 = 移进 skills/.archive/（Hermes 不再加载，但没删）
    启用 = 移回来。永远不做真删除 —— 这是有意的。
    """
    if not re.match(r"^[A-Za-z0-9_\-]{1,60}$", name or ""):
        raise CtlError("非法技能名")
    sd = safe_path(base, "skills")
    arc = os.path.join(sd, ".archive")
    src = os.path.join(arc if enable else sd, name)
    dst = os.path.join(sd if enable else arc, name)
    if not os.path.isdir(src):
        raise CtlError("技能不存在")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    audit(base, "skill." + ("enable" if enable else "disable"), name, actor)
    return True


def archived_skills(base):
    arc = os.path.join(base, "skills", ".archive")
    if not os.path.isdir(arc):
        return []
    return sorted(d for d in os.listdir(arc)
                  if os.path.isdir(os.path.join(arc, d)) and not d.startswith("."))


# ============================================================
# 7. cron
# ============================================================

CRON_DISABLE_SUFFIX = ".disabled"


def cron_list(base):
    d = os.path.join(base, "cron")
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if not os.path.isfile(p):
            continue
        disabled = f.endswith(CRON_DISABLE_SUFFIX)
        with open(p, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        out.append({"name": f, "disabled": disabled,
                    "body": body[:2000], "mtime": int(os.path.getmtime(p))})
    return out


def cron_toggle(base, name, enable, actor=""):
    d = safe_path(base, "cron")
    src = os.path.join(d, name)
    if not os.path.isfile(src):
        # 容忍传入"带后缀/不带后缀"的两种名字，避免前端缓存导致的空操作
        alt = name + CRON_DISABLE_SUFFIX if not name.endswith(CRON_DISABLE_SUFFIX) \
            else name[:-len(CRON_DISABLE_SUFFIX)]
        if os.path.isfile(os.path.join(d, alt)):
            name = alt
            src = os.path.join(d, name)
    if enable:
        dst = os.path.join(d, name[:-len(CRON_DISABLE_SUFFIX)]
                           if name.endswith(CRON_DISABLE_SUFFIX) else name)
    else:
        dst = os.path.join(d, name + CRON_DISABLE_SUFFIX
                           if not name.endswith(CRON_DISABLE_SUFFIX) else name)
    if not os.path.isfile(src) or src == dst:
        raise CtlError("任务不存在或状态未变")
    os.rename(src, dst)
    audit(base, "cron." + ("enable" if enable else "disable"), name, actor)
    return True


# ============================================================
# 8. Provider 预设（国内可用 + 已知的坑）
# ============================================================

PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek/deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
        "tip": "模型名必须带 deepseek/ 前缀，否则工具调用会静默失效",
    },
    "moonshot": {
        "label": "Kimi / Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot/moonshot-v1-128k",
        "key_env": "MOONSHOT_API_KEY",
        "tip": "128K 上下文，长会话友好",
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen/qwen-plus",
        "key_env": "DASHSCOPE_API_KEY",
        "tip": "注意用兼容模式 endpoint",
    },
    "zai": {
        "label": "z.ai / GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.6",
        "key_env": "ZAI_API_KEY",
        "tip": "GLM 对长工具链支持较好",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-3.5-sonnet",
        "key_env": "OPENROUTER_API_KEY",
        "tip": "一个 Key 打通所有模型，适合先横向对比再定",
    },
}


def apply_provider(base, key, api_key, actor=""):
    """一键切换 Provider：写 .env，并提示还需改 config.yaml 里的 model"""
    p = PROVIDERS.get(key)
    if not p:
        raise CtlError("未知 Provider")
    updates = {}
    if api_key and "•" not in api_key and api_key != "__KEEP__":
        updates[p["key_env"]] = api_key
    r = env_save(base, updates, actor=actor) if updates else {"changed": False}
    audit(base, "provider.apply", key, actor)
    return {
        "provider": p,
        "env_changed": r.get("changed", False),
        "next": f"还需把 config.yaml 里的模型改成 {p['model']}（配置页可改，改完重启生效）",
    }


# ============================================================
# 8.5 对话接口（跟 Hermes 聊天用的 API：provider / 密钥 / base_url / 模型）
# ============================================================

#: 在 PROVIDERS 基础上加一个"自定义 OpenAI 兼容接口"，让任意中转 / 本地 vLLM 都能用
CHAT_API_PROVIDERS = dict(PROVIDERS)
CHAT_API_PROVIDERS["openai"] = {
    "label": "自定义 OpenAI 兼容接口",
    "base_url": "（自定义，写入 OPENAI_BASE_URL）",
    "model": "gpt-4o-mini",
    "key_env": "OPENAI_API_KEY",
    "tip": "填你自己的 Base URL（第三方中转 / 本地 vLLM / One API 等），"
           "模型名按那家的写法填，base_url 写入 OPENAI_BASE_URL",
}


def env_get(base, key):
    """读 .env 里某个键的原始值（用于回显，注意调用方负责脱敏）"""
    p = safe_path(base, ".env")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    return ""


def chat_api_get(base):
    """读取当前对话接口配置：provider / 模型 / 密钥(脱敏) / base_url"""
    if not HAS_YAML:
        return {"error": "缺少 ruamel.yaml（pip install ruamel.yaml）"}
    cfg, _ = _load_cfg(base)
    mb = (cfg or {}).get("model") or {}
    provider = mb.get("provider") or ""
    model = mb.get("default") or ""
    api_key = ""
    base_url = ""
    if provider == "openai":
        raw = env_get(base, "OPENAI_API_KEY")
        api_key = raw
        base_url = env_get(base, "OPENAI_BASE_URL")
    elif provider in CHAT_API_PROVIDERS:
        kenv = CHAT_API_PROVIDERS[provider].get("key_env")
        api_key = env_get(base, kenv) if kenv else ""
    key_set = bool(api_key)
    if key_set:
        api_key = (api_key[:4] + "•" * 8 + api_key[-4:]) if len(api_key) > 8 else "•" * 8
    preset_base = (CHAT_API_PROVIDERS.get(provider, {}) or {}).get("base_url", "") \
        if provider in CHAT_API_PROVIDERS else ""
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "key_set": key_set,
        "base_url": base_url,
        "presets": CHAT_API_PROVIDERS,
        "preset_base_url": preset_base,
    }


def chat_api_save(base, provider, api_key, model, base_url, actor=""):
    """保存对话接口：写 config.yaml 的 model 块 + .env 密钥 / base_url。
    密钥若仍是脱敏样式或 __KEEP__ = 不改动原值。"""
    if not HAS_YAML:
        raise CtlError("缺少 ruamel.yaml，无法安全编辑 config.yaml（pip install ruamel.yaml）")
    if not re.match(r"^[A-Za-z0-9_\-]{1,40}$", provider or ""):
        raise CtlError("非法 provider")
    if not (model or "").strip():
        raise CtlError("模型名必填（带 provider 前缀，如 deepseek/deepseek-chat）")
    cfg, path = _load_cfg(base)
    if cfg is None:
        cfg = {}
    mb = cfg.get("model")
    if mb is None:
        mb = {}
        cfg["model"] = mb
    mb["default"] = model.strip()
    mb["provider"] = "openai" if provider == "openai" else provider
    write_file(base, "config.yaml", _dump_cfg(cfg, path), actor=actor)

    updates = {}
    if api_key and "•" not in api_key and api_key != "__KEEP__":
        if provider == "openai":
            updates["OPENAI_API_KEY"] = api_key
            if base_url and base_url.strip():
                updates["OPENAI_BASE_URL"] = base_url.strip().rstrip("/")
        else:
            kenv = CHAT_API_PROVIDERS.get(provider, {}).get("key_env")
            if kenv:
                updates[kenv] = api_key
    if updates:
        env_save(base, updates, actor=actor)
    audit(base, "chat_api.save", f"provider={provider} model={model}", actor)
    return {"provider": provider, "model": model,
            "next": "改完需重启 Hermes（或会话内 /reload / hermes model）生效"}


# ============================================================
# 9. 系统动作：重启 / 重载 / 升级
# ============================================================

def run_cmd(cmd, timeout=120, cwd=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "执行超时"
    except FileNotFoundError:
        return -1, "", "命令不存在"
    except Exception as e:                                   # noqa
        return -1, "", str(e)


def restart_hermes(mode, container, actor="", base=""):
    if mode == "docker":
        rc, out, err = run_cmd(["docker", "restart", container], timeout=120)
    else:
        rc, out, err = run_cmd(["systemctl", "restart", "hermes"], timeout=120)
    if base:
        audit(base, "restart", f"rc={rc} {out or err}"[:160], actor)
    return {"ok": rc == 0, "rc": rc, "output": (out or err)[:500]}


def reload_mcp(mode, container, actor="", base=""):
    """让 MCP 改动不重启就生效"""
    if mode == "docker":
        rc, out, err = run_cmd(["docker", "exec", container,
                                "hermes", "reload-mcp"], timeout=60)
    else:
        rc, out, err = run_cmd(["hermes", "reload-mcp"], timeout=60)
    if base:
        audit(base, "mcp.reload", f"rc={rc}", actor)
    return {"ok": rc == 0, "rc": rc, "output": (out or err)[:500]}


def upgrade_hermes(mode, container, actor="", base="", compose_dir=""):
    """升级 Hermes：拉新镜像 → 重建容器。失败不影响旧容器。"""
    if not compose_dir:
        return {"ok": False, "output": "未配置 COMPOSE_DIR，无法升级"}
    cmds = [["docker", "compose", "pull"], ["docker", "compose", "up", "-d"]]
    logs = []
    ok = True
    for c in cmds:
        rc, out, err = run_cmd(c, timeout=600, cwd=compose_dir or None)
        logs.append(f"$ {' '.join(c)}\n{out or err}")
        ok = ok and rc == 0
    if base:
        audit(base, "upgrade", f"rc_ok={ok}", actor)
    return {"ok": ok, "output": "\n\n".join(logs)[:1500]}


# ============================================================
# 10. 配置开关（点号路径白名单，安全改 config.yaml 里的常用旋钮）
# ============================================================

#: 允许网页直接改的 config.yaml 字段（路径 -> 类型）。其余一律拒绝。
CFG_ALLOW = {
    "tools.async_enabled": bool,
    "memory.compression.enabled": bool,
    "memory.memory_window": int,
    "memory.top_k": int,
    "memory.retrieval.hybrid_search": bool,
    "approvals.mode": str,
    "terminal.backend": str,
    "worker_pool_size": int,
    "model.streaming": bool,
    "agent.max_empty_retries": int,
    "tool_call_timeout": int,
}


def _get_dotted(cfg, path):
    cur = cfg
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _set_dotted(cfg, path, value):
    parts = path.split(".")
    cur = cfg
    for k in parts[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[parts[-1]] = value


def cfg_read(base):
    cfg, _ = _load_cfg(base)
    vals = {p: _get_dotted(cfg, p) for p in CFG_ALLOW}
    return {"exists": cfg is not None, "values": vals,
            "allow": {k: t.__name__ for k, t in CFG_ALLOW.items()}}


def cfg_set(base, path, value, actor=""):
    if path not in CFG_ALLOW:
        raise CtlError(f"不被允许修改的配置项：{path}")
    typ = CFG_ALLOW[path]
    if typ is bool:
        if isinstance(value, str):
            value = value.lower() in ("1", "true", "yes", "on", "启用", "enabled")
        value = bool(value)
    elif typ is int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise CtlError(f"{path} 必须是整数")
    cfg, path_ = _load_cfg(base)
    if cfg is None:
        cfg = {}
    _set_dotted(cfg, path, value)
    write_file(base, "config.yaml", _dump_cfg(cfg, path_), actor=actor)
    audit(base, "cfg.set", f"{path} = {value}", actor)
    return {"path": path, "value": value}


# ============================================================
# 11. Hermes 命令台（把 Hermes CLI 功能接口集成进网页，白名单放行）
# ============================================================

#: 子命令白名单：组 -> 允许的二级动作（空列表 = 仅该组无参数动作）。
HERMES_ALLOW = {
    "doctor": [],
    "update": [],
    "memory": ["consolidate", "cleanup", "setup"],
    "profile": ["list", "create", "switch"],
    "session": ["list", "prune"],
    "curator": ["status", "pin"],
    "skills": ["update", "catalog", "browse", "inspect"],
    "mcp": ["catalog", "test", "list"],
    "tools": ["list"],
    "model": ["list"],
}


def check_hermes_args(args):
    a = [str(x) for x in (args or [])]
    if a and a[0] == "hermes":
        a = a[1:]
    if not a:
        return False, "缺少子命令"
    grp = a[0]
    if grp not in HERMES_ALLOW:
        return False, f"不允许的子命令：{grp}"
    subs = HERMES_ALLOW[grp]
    sub = a[1] if len(a) > 1 else None
    if subs and sub not in subs:
        return False, f"{grp} 不允许的参数：{sub}"
    for x in a[1:]:
        if not re.match(r"^[A-Za-z0-9_.\-=/@: ]{0,240}$", x):
            return False, f"非法参数：{x}"
    return True, ""


def hermes_run(args, base="", mode=None, container=None, timeout=300):
    """在 Hermes 环境里跑一条（白名单内的）命令。"""
    a = [str(x) for x in (args or [])]
    if a and a[0] == "hermes":
        a = a[1:]
    cmd = ["hermes"] + a
    if mode == "docker":
        cmd = ["docker", "exec", container or "hermes"] + cmd
    cwd = base if (mode != "docker" and base) else None
    return run_cmd(cmd, timeout=timeout, cwd=cwd)


# ============================================================
# 12. 版本 / 自检 / 工作台自更新
# ============================================================

def version_info(base):
    here = os.path.dirname(os.path.abspath(__file__))
    ver = "dev"
    vp = os.path.join(here, "VERSION")
    if os.path.isfile(vp):
        ver = (open(vp).read().strip() or "dev")
    rc, out, _ = run_cmd(
        ["git", "-C", here, "describe", "--tags", "--always", "--dirty"], timeout=10)
    git_ver = out if rc == 0 else ""
    current = git_ver or ver

    # 上游版本检查（可选：配了 UPDATE_REPO 才查，避免无谓外联）
    upstream = None
    has_update = False
    repo = os.getenv("UPDATE_REPO", "").strip()
    if repo:
        try:
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            req = urllib.request.Request(  # noqa
                url, headers={"User-Agent": "hermes-console", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
            tag = (data.get("tag_name") or "").lstrip("v")
            upstream = tag
            # 粗略比较：能解析成数字版本才比
            import re as _re
            def _nums(s):
                return [int(x) for x in _re.findall(r"\d+", s)]
            if tag and _nums(tag) and _nums(current):
                has_update = _nums(tag) > _nums(current)
        except Exception:                                       # noqa
            upstream = None
    return {"version": current, "git": git_ver, "repo": repo or None,
            "upstream": upstream, "has_update": has_update}


def dash_update(base, actor=""):
    """
    工作台自更新：从 git 拉取最新代码（仅快进），成功则提示需要重启。
    真正的重启交给守护进程（start-dash.sh 看门狗 / systemd / 容器编排）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    rc, out, err = run_cmd(["git", "-C", here, "pull", "--ff-only"], timeout=120)
    if rc != 0:
        return {"ok": False, "output": (out or err)[:1500], "restart": False}
    audit(base, "dash.update", "git pull", actor)
    return {"ok": True, "output": out[:1500], "restart": True,
            "hint": "已拉取新代码，正在重启以生效…"}


def doctor(base, mode=None, container=None, timeout=120):
    rc, out, err = hermes_run(["doctor"], base=base, mode=mode,
                              container=container, timeout=timeout)
    return {"ok": rc == 0, "rc": rc, "output": (out or err)[:4000]}
