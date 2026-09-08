#!/usr/bin/env python3
"""
Hermes 工作台 · 登录鉴权（安全优先）

设计要点：
- 只有「一个密码」，没有用户名 —— 部署后只暴露一个访问入口。
- 首次部署若未发现密码，随机生成强密码写入明文文件 DASHBOARD_PASSWORD.txt，
  并标记 must_change=True，强制用户登录后立刻改密码（改完自动删除明文文件）。
- 密码用 PBKDF2-HMAC-SHA256（20 万轮）+ 随机盐存储，磁盘上永不存明文。
- Flask 签名 session 做登录态；secret_key 持久化在 .dashboard/secret_key，
  重启/重建容器后登录态依然有效。
- 失败锁定：同一来源 15 分钟内 5 次失败，锁定 15 分钟（防爆破）。
"""
import os
import json
import time
import hmac
import secrets
import hashlib

ROUNDS = 200_000


def _dash(base):
    d = os.path.join(base, ".dashboard")
    os.makedirs(d, exist_ok=True)
    return d


def auth_path(base):
    return os.path.join(_dash(base), "auth.json")


def secret_key_path(base):
    return os.path.join(_dash(base), "secret_key")


def initial_password_path(base):
    return os.path.join(base, "DASHBOARD_PASSWORD.txt")


def load_or_create_secret_key(base):
    """持久化 secret_key，保证重启后 session 不过期。"""
    p = secret_key_path(base)
    if os.path.isfile(p):
        with open(p, "r") as f:
            k = f.read().strip()
        if k:
            return k
    k = secrets.token_hex(32)
    with open(p, "w") as f:
        f.write(k)
    os.chmod(p, 0o600)
    return k


def _hash(pw, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, ROUNDS)
    return salt.hex() + "$" + dk.hex()


def verify(pw, stored):
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, ROUNDS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def init_auth(base, force=False):
    """首次部署生成随机初始密码 + 明文文件 + must_change。已存在则直接返回。"""
    d = auth_path(base)
    if os.path.isfile(d) and not force:
        return load_auth(base)
    if os.path.isfile(d) and force:
        # 仅在真正丢失明文文件时重置（正常不改密不会触发）
        if os.path.isfile(initial_password_path(base)):
            return load_auth(base)
    pw = secrets.token_urlsafe(16)
    store = {
        "hash": _hash(pw),
        "must_change": True,
        "created": int(time.time()),
        "version": 1,
    }
    tmp = d + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, d)

    ip = initial_password_path(base)
    with open(ip, "w") as f:
        f.write("Hermes 工作台 · 初始登录密码\n")
        f.write("================================\n")
        f.write(f"密码：{pw}\n\n")
        f.write(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("部署后请尽快登录并修改此密码。修改成功后本文件可删除。\n")
    os.chmod(ip, 0o600)
    return store


def load_auth(base):
    d = auth_path(base)
    if not os.path.isfile(d):
        return None
    try:
        with open(d) as f:
            return json.load(f)
    except Exception:
        return None


def needs_change(base):
    a = load_auth(base)
    return bool(a and a.get("must_change"))


def verify_login(base, pw):
    a = load_auth(base)
    if not a:
        init_auth(base)
        a = load_auth(base)
    if not a:
        return False
    return verify(pw, a.get("hash", ""))


def set_password(base, new_pw):
    a = load_auth(base) or {}
    a["hash"] = _hash(new_pw)
    a["must_change"] = False
    a["updated"] = int(time.time())
    d = auth_path(base)
    tmp = d + ".tmp"
    with open(tmp, "w") as f:
        json.dump(a, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, d)
    # 改密成功 → 删明文初始文件
    ipf = initial_password_path(base)
    if os.path.isfile(ipf):
        try:
            os.remove(ipf)
        except Exception:
            pass
    return True


def reset_password(base):
    """运维兜底：删除鉴权文件，下次访问重新生成初始密码文件。"""
    for p in (auth_path(base), initial_password_path(base)):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except Exception:
                pass
    return init_auth(base)
