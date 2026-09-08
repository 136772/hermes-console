#!/usr/bin/env bash
# Hermes Agent 安全基线自检（只读，不修改任何文件）
# 用法: bash security-check.sh
# 可选: HERMES_DIR=/path/to/.hermes bash security-check.sh

HERMES_DIR="${HERMES_DIR:-$HOME/.hermes}"

ok()   { printf '[ OK ] %s\n'   "$1"; }
warn() { printf '[WARN] %s\n'   "$1"; WARN_COUNT=$((WARN_COUNT+1)); }
risk() { printf '[RISK] %s\n'   "$1"; RISK_COUNT=$((RISK_COUNT+1)); }
info() { printf '[ .. ] %s\n'   "$1"; }

WARN_COUNT=0
RISK_COUNT=0

echo "=============================================="
echo " Hermes 安全基线自检"
echo " 目录: $HERMES_DIR"
echo " 时间: $(date '+%F %T %Z')"
echo "=============================================="
echo

# ---------- 0. 目录存在 ----------
if [ ! -d "$HERMES_DIR" ]; then
  risk "目录不存在: $HERMES_DIR —— 请确认路径，或设置 HERMES_DIR 环境变量"
  exit 1
fi
ok "Hermes 目录存在"

# ---------- 1. 运行用户 ----------
echo; echo "--- 1. 运行身份 ---"
if [ "$(id -u)" = "0" ]; then
  risk "当前以 root 运行 —— agent 应以非 root 用户运行"
else
  ok "非 root 运行 (uid=$(id -u))"
fi

# ---------- 2. 目录与敏感文件权限 ----------
echo; echo "--- 2. 文件权限 ---"
DPERM=$(stat -c '%a' "$HERMES_DIR" 2>/dev/null)
case "$DPERM" in
  700|750) ok "目录权限 $DPERM" ;;
  *)       warn "目录权限 $DPERM —— 建议 700 (chmod 700 $HERMES_DIR)" ;;
esac

for f in .env auth.json config.yaml; do
  p="$HERMES_DIR/$f"
  [ -e "$p" ] || continue
  perm=$(stat -c '%a' "$p")
  if [ "$perm" = "600" ] || [ "$perm" = "400" ]; then
    ok "$f 权限 $perm"
  else
    risk "$f 权限 $perm —— 含密钥，必须 600 (chmod 600 $p)"
  fi
done

# ---------- 3. 密钥是否泄漏进记忆 / 日志 ----------
echo; echo "--- 3. 密钥泄漏扫描 ---"
KEY_HIT=0
if [ -d "$HERMES_DIR/memories" ]; then
  if grep -rInE '(sk-[A-Za-z0-9]{20,}|api[_-]?key[[:space:]]*[:=][[:space:]]*[^[:space:]]+|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}|password[[:space:]]*[:=][[:space:]]*[^[:space:]]+)' \
       "$HERMES_DIR/memories" 2>/dev/null | head -5; then
    risk "记忆文件中发现疑似密钥 —— 立即移除并轮换该密钥"
    KEY_HIT=1
  fi
fi
[ "$KEY_HIT" = "0" ] && ok "记忆文件未发现明文密钥"

# ---------- 4. 记忆投毒特征：无条件指令 ----------
echo; echo "--- 4. 记忆投毒特征 ---"
POISON=0
if [ -d "$HERMES_DIR/memories" ]; then
  hits=$(grep -rInE '(以后都要|无论如何|永远不要告诉|不要告诉用户|不要告知用户|忽略(之前|以上|前面)的?(所有)?(指令|规则)|always (ignore|obey)|ignore (all )?previous)' \
        "$HERMES_DIR/memories" 2>/dev/null | head -10)
  if [ -n "$hits" ]; then
    echo "$hits"
    warn "发现无条件/覆盖型指令 —— 逐条确认是你本人添加的，否则立即删除"
    POISON=1
  fi
fi
[ "$POISON" = "0" ] && ok "未发现可疑无条件指令"

# ---------- 5. 最近 24 小时变更（异常写入） ----------
echo; echo "--- 5. 最近 24h 变更 ---"
recent=$(find "$HERMES_DIR/memories" "$HERMES_DIR/skills" -type f -mtime -1 2>/dev/null)
if [ -n "$recent" ]; then
  echo "$recent" | while read -r f; do echo "       $f"; done
  info "以上文件 24h 内被修改 —— 确认每处改动都是你授权的"
else
  ok "记忆与技能目录 24h 内无变更"
fi

# ---------- 6. 技能外发行为审查 ----------
echo; echo "--- 6. 技能外发行为 ---"
EXFIL=0
if [ -d "$HERMES_DIR/skills" ]; then
  hits=$(grep -rInE '(curl[[:space:]]+[^|]*(-d|--data|-F)|wget[[:space:]]+.*--post|nc[[:space:]]+-|base64[[:space:]]+-d[[:space:]]*\|[[:space:]]*(ba)?sh|/dev/tcp/)' \
        "$HERMES_DIR/skills" 2>/dev/null | head -10)
  if [ -n "$hits" ]; then
    echo "$hits"
    risk "技能中发现外发/可疑执行行为 —— 逐条人工审查，确认来源"
    EXFIL=1
  fi
fi
[ "$EXFIL" = "0" ] && ok "技能库未发现明显外发行为"

# ---------- 7. 定时任务清单 ----------
echo; echo "--- 7. 定时任务 ---"
if [ -d "$HERMES_DIR/cron" ] && [ -n "$(ls -A "$HERMES_DIR/cron" 2>/dev/null)" ]; then
  ls -1 "$HERMES_DIR/cron" | while read -r c; do echo "       $c"; done
  info "确认以上任务全部由你创建 —— 攻击者常在此留后门"
else
  ok "未发现定时任务"
fi

# ---------- 8. 版本控制（回滚能力） ----------
echo; echo "--- 8. 记忆回滚能力 ---"
if [ -d "$HERMES_DIR/.git" ]; then
  ok "已纳入 git —— 可用 git diff / git checkout 回滚"
else
  warn "未纳入版本控制 —— 建议: cd $HERMES_DIR && git init && git add -A && git commit -m 'baseline'"
fi

# ---------- 9. 容器逃逸风险 ----------
echo; echo "--- 9. 容器隔离 ---"
if [ -f /proc/1/cgroup ] && grep -qE 'docker|kubepod' /proc/1/cgroup 2>/dev/null; then
  info "当前运行在容器内"
  if [ -S /var/run/docker.sock ]; then
    risk "容器内可见 /var/run/docker.sock —— 等于把宿主机 root 交给它，必须移除该挂载"
  else
    ok "未挂载 docker.sock"
  fi
  # 检查是否挂载了根目录级数据卷
  if grep -qE '^[^ ]+ /($|/volume|/mnt) ' /proc/mounts 2>/dev/null; then
    warn "疑似挂载了根目录或整个存储卷 —— 建议收窄到具体服务目录"
  fi
else
  info "非容器环境（物理机/虚拟机直接运行）—— 更需限制运行用户与目录权限"
fi

# ---------- 10. 备份 ----------
echo; echo "--- 10. 备份 ---"
backup=$(find "$(dirname "$HERMES_DIR")" -maxdepth 1 -name 'hermes-backup-*.tar.gz' -mtime -30 2>/dev/null | head -1)
if [ -n "$backup" ]; then
  ok "发现 30 天内备份: $(basename "$backup")"
else
  warn "未发现 30 天内的备份 —— 建议: tar czf hermes-backup-\$(date +%F).tar.gz $HERMES_DIR"
fi

# ---------- 汇总 ----------
echo
echo "=============================================="
echo " 汇总: RISK=$RISK_COUNT  WARN=$WARN_COUNT"
if [ "$RISK_COUNT" -gt 0 ]; then
  echo " 存在高危项，请优先处理 [RISK]"
elif [ "$WARN_COUNT" -gt 0 ]; then
  echo " 无高危项，建议处理 [WARN]"
else
  echo " 全部通过"
fi
echo "=============================================="
