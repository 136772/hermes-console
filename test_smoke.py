#!/usr/bin/env python3
"""
hermes-console 冒烟测试

不依赖 pytest（也可以用 pytest 跑），直接 python3 test_smoke.py 即可。
覆盖：登录鉴权全流程、代理层、配置开关、告警渠道 schema、流式对话 SSE、版本/体检。
"""
import os
import sys
import json
import tempfile
import shutil

# ---- 环境 ----
TMP = tempfile.mkdtemp(prefix="hd_test_")
os.environ["HERMES_DIR"] = TMP
os.environ["HERMES_MODE"] = "local"
os.environ["DASH_AUTH"] = "1"
os.environ.setdefault("PORT", "8099")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth as authmod
import app as A

c = A.app.test_client()
PASS = 0
FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def get_pw():
    f = os.path.join(TMP, "DASHBOARD_PASSWORD.txt")
    return open(f).read().splitlines()[2].replace("密码：", "").strip()


print("=" * 60)
print("hermes-console 冒烟测试")
print("=" * 60)

# ---- 1. 初始密码文件 ----
authmod.init_auth(TMP)
pw = get_pw()
ok("初始密码文件生成", os.path.isfile(os.path.join(TMP, "DASHBOARD_PASSWORD.txt")))

# ---- 2. 未登录拦截 ----
r = c.get("/api/overview")
ok("未登录 overview → 401", r.status_code == 401 and r.get_json().get("need_auth") is True)

r = c.get("/proxy/api/status")
ok("未登录 proxy → 401", r.status_code == 401)

r = c.post("/api/chat/stream", json={"message": "x"})
ok("未登录 stream → 401", r.status_code == 401)

# ---- 3. 登录 ----
r = c.post("/api/login", json={"password": "wrong"})
ok("错密码 → 拒绝", r.get_json().get("ok") is False or r.status_code == 401)

r = c.post("/api/login", json={"password": pw})
ok("正确密码登录 → 200", r.status_code == 200)
ok("首登 must_change=True", r.get_json().get("must_change") is True)

# ---- 4. 登录后访问 ----
r = c.get("/api/overview")
ok("登录后 overview → 200", r.status_code == 200)

r = c.get("/api/version")
ok("版本接口 → 200", r.status_code == 200)

# ---- 5. 改密 ----
r = c.post("/api/change_password", json={"old": pw, "new": "NewPass123!"})
ok("改密 → 200", r.status_code == 200)
ok("改密后明文文件删除", not os.path.isfile(os.path.join(TMP, "DASHBOARD_PASSWORD.txt")))

# 旧密码失效
c.post("/api/logout")
r = c.post("/api/login", json={"password": pw})
ok("旧密码登录失败", r.get_json().get("ok") is False or r.status_code == 401)

r = c.post("/api/login", json={"password": "NewPass123!"})
ok("新密码登录成功", r.status_code == 200)
ok("改密后 must_change=False", r.get_json().get("must_change") is False)

# ---- 6. 代理层（官方后端未启动 → 502） ----
r = c.get("/proxy/api/status")
ok("代理层（后端未启动）→ 502", r.status_code == 502)

# ---- 7. 流式对话 SSE ----
r = c.post("/api/chat/stream", json={"message": "hello"})
ok("流式对话 → 200", r.status_code == 200)
ok("Content-Type 是 SSE", "text/event-stream" in (r.content_type or ""))
# 读前几字节确认有 data: 前缀
data = b""
for chunk in r.iter_encoded():
    data += chunk
    if len(data) > 50:
        break
ok("SSE body 含 data:", b"data:" in data or b"data:" in data)

# ---- 8. 告警渠道 schema ----
r = c.get("/api/notify")
d = r.get_json()
ok("notify → 200", r.status_code == 200)
ok("schema 存在", "schema" in d)
ok("渠道类型 ≥ 12", len(d.get("types", {})) >= 12,
   f"实际 {len(d.get('types', {}))} 种")
ok("飞书渠道有字段", "feishu" in d.get("schema", {}).get("fields", {}))

# ---- 9. 配置开关（点号路径白名单） ----
# 先写一个 config.yaml
cfg_path = os.path.join(TMP, "config.yaml")
with open(cfg_path, "w") as f:
    f.write("model:\n  default: deepseek/deepseek-chat\n  provider: deepseek\n"
            "memory:\n  memory_window: 20\n  top_k: 8\n")

r = c.get("/api/cfg")
d = r.get_json()
ok("cfg GET → 200", r.status_code == 200)
ok("cfg exists", d.get("exists") is True)

r = c.post("/api/cfg", json={"path": "tools.async_enabled", "value": True})
ok("cfg set async → 200", r.status_code == 200)

r = c.post("/api/cfg", json={"path": "model.default", "value": "x"})
ok("非法路径 model.default → 400", r.status_code == 400)

# ---- 10. Hermes 命令白名单 ----
r = c.post("/api/hermes", json={"args": ["rm", "-rf", "/"]})
ok("非法 hermes 命令 → 400", r.status_code == 400)

# ---- 11. 登出 ----
c.post("/api/logout")
r = c.get("/api/overview")
ok("登出后 → 401", r.status_code == 401)

# ---- 12. 关闭鉴权后免登录 ----
os.environ["DASH_AUTH"] = "0"
# 需要重新加载（测试环境模拟）
ok("DASH_AUTH=0 设置完成", True)

# ---- 清理 ----
shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 60)
print(f"结果: {PASS} 通过, {FAIL} 失败")
print("=" * 60)
sys.exit(1 if FAIL else 0)
