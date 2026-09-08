#!/usr/bin/env bash
# Hermes 运行时健康检查（只读，不修改任何文件）
#
# 用法:
#   bash health-check.sh                 # 完整输出
#   bash health-check.sh --quiet         # 仅在发现问题时输出（适合 cron + 通知）
#   bash health-check.sh --no-probe      # 跳过活体探测（省钱省时间）
#
# 可调环境变量:
#   HERMES_DIR=/path/to/.hermes  默认 $HOME/.hermes
#   QUOTA_MB=10240               配额上限(MB)，默认 10G
#
# cron 示例（每天 9 点，异常才输出）:
#   0 9 * * * /path/health-check.sh --quiet | mail -s "Hermes 异常" you@example.com

HERMES_DIR="${HERMES_DIR:-$HOME/.hermes}"
QUOTA_MB="${QUOTA_MB:-10240}"

QUIET=0
NO_PROBE=0
for arg in "$@"; do
  case "$arg" in
    --quiet)   QUIET=1 ;;
    --no-probe) NO_PROBE=1 ;;
  esac
done

WARN_COUNT=0
RISK_COUNT=0

ok()   { [ "$QUIET" = "1" ] || printf '[ OK ] %s\n' "$1"; }
info() { [ "$QUIET" = "1" ] || printf '[ .. ] %s\n' "$1"; }
warn() { WARN_COUNT=$((WARN_COUNT+1)); printf '[WARN] %s\n' "$1"; }
risk() { RISK_COUNT=$((RISK_COUNT+1)); printf '[RISK] %s\n' "$1"; }
# 章节标题：quiet 模式下完全静默，避免 cron 邮件里出现一堆空标题
section() { [ "$QUIET" = "1" ] || printf '\n--- %s ---\n' "$1"; }

# ---------- 0. 目录 ----------
if [ ! -d "$HERMES_DIR" ]; then
  risk "Hermes 目录不存在: $HERMES_DIR（设置 HERMES_DIR 或检查挂载）"
  exit 1
fi

[ "$QUIET" = "1" ] || {
  echo "=============================================="
  echo " Hermes 健康检查  $(date '+%F %T %Z')"
  echo " 目录: $HERMES_DIR"
  echo "=============================================="
  echo
}

# ---------- 1. 存活 ----------
section "1. 进程存活"
CNAME=""
if command -v docker >/dev/null 2>&1; then
  CNAME=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i hermes | head -1)
fi

if [ -n "$CNAME" ]; then
  ok "容器运行中: $CNAME"
  MODE="docker"
  # 容器重启次数（异常重启是重要信号）
  RESTARTS=$(docker inspect -f '{{.RestartCount}}' "$CNAME" 2>/dev/null)
  if [ -n "$RESTARTS" ] && [ "$RESTARTS" -gt 3 ] 2>/dev/null; then
    warn "容器已重启 $RESTARTS 次 —— 可能存在崩溃循环"
  fi
elif pgrep -f hermes >/dev/null 2>&1; then
  ok "进程运行中"
  MODE="process"
else
  risk "Hermes 未运行"
  MODE="down"
fi
[ "$QUIET" = "1" ] || echo

# ---------- 2. 活体探测（真能干活，不只是进程在） ----------
section "2. 活体探测"
if [ "$NO_PROBE" = "1" ]; then
  info "已跳过（--no-probe）"
elif [ "$MODE" = "down" ]; then
  risk "进程不在，跳过探测"
else
  PROBE_OK=0
  if [ "$MODE" = "docker" ]; then
    timeout 90 docker exec "$CNAME" hermes run "ping" >/dev/null 2>&1 && PROBE_OK=1
  else
    timeout 90 hermes run "ping" >/dev/null 2>&1 && PROBE_OK=1
  fi

  if [ "$PROBE_OK" = "1" ]; then
    ok "能响应并完成任务"
  else
    risk "进程在但无响应（超时或 API 故障）—— 这是最容易漏掉的假活状态"
  fi
fi
[ "$QUIET" = "1" ] || echo

# ---------- 3. 配额 / 磁盘 ----------
section "3. 存储用量"
USED_MB=$(du -sm "$HERMES_DIR" 2>/dev/null | cut -f1)
USED_MB=${USED_MB:-0}
PCT=$((USED_MB * 100 / QUOTA_MB))

if [ "$PCT" -ge 90 ]; then
  risk "已用 ${USED_MB}MB / ${QUOTA_MB}MB (${PCT}%) —— 即将写满，它会行为异常而非报错"
elif [ "$PCT" -ge 80 ]; then
  warn "已用 ${USED_MB}MB / ${QUOTA_MB}MB (${PCT}%) —— 接近上限"
else
  ok "已用 ${USED_MB}MB / ${QUOTA_MB}MB (${PCT}%)"
fi

# 各子目录占用 Top3
if [ "$QUIET" = "0" ]; then
  du -sm "$HERMES_DIR"/* 2>/dev/null | sort -rn | head -3 | while read -r sz p; do
    printf '       %6s MB  %s\n' "$sz" "$p"
  done
fi

# 宿主磁盘余量
DISK_PCT=$(df "$HERMES_DIR" 2>/dev/null | awk 'NR==2{print $5}' | tr -d '%')
if [ -n "$DISK_PCT" ] && [ "$DISK_PCT" -ge 90 ] 2>/dev/null; then
  warn "宿主磁盘已用 ${DISK_PCT}% —— 不只是配额，整盘也快满了"
fi
[ "$QUIET" = "1" ] || echo

# ---------- 4. 最近 24h 日志错误 ----------
section "4. 日志异常"
if [ -d "$HERMES_DIR/logs" ]; then
  ERRCOUNT=$(find "$HERMES_DIR/logs" -type f -mtime -1 2>/dev/null \
    | xargs grep -ciE 'error|traceback|exception|failed' 2>/dev/null \
    | awk -F: '{s+=$NF} END {print s+0}')
  ERRCOUNT=${ERRCOUNT:-0}
  if [ "$ERRCOUNT" -gt 50 ]; then
    risk "24h 内日志错误约 $ERRCOUNT 处 —— 可能存在崩溃循环"
  elif [ "$ERRCOUNT" -gt 5 ]; then
    warn "24h 内日志错误约 $ERRCOUNT 处"
  else
    ok "24h 内日志错误 $ERRCOUNT 处"
  fi
else
  info "无 logs 目录"
fi
[ "$QUIET" = "1" ] || echo

# ---------- 5. 记忆膨胀 ----------
section "5. 记忆与技能"
if [ -d "$HERMES_DIR/memories" ]; then
  MEM_N=$(find "$HERMES_DIR/memories" -type f 2>/dev/null | wc -l | tr -d ' ')
  MEM_MB=$(du -sm "$HERMES_DIR/memories" 2>/dev/null | cut -f1)
  MEM_MB=${MEM_MB:-0}
  if [ "$MEM_N" -gt 80 ] || [ "$MEM_MB" -gt 100 ]; then
    warn "记忆 $MEM_N 个文件 / ${MEM_MB}MB —— 可能膨胀，检索精度会下降"
  else
    ok "记忆 $MEM_N 个文件 / ${MEM_MB}MB"
  fi

  # 单文件过大
  BIG=$(find "$HERMES_DIR/memories" -type f -size +100k 2>/dev/null | head -3)
  [ -n "$BIG" ] && warn "存在超过 100KB 的记忆文件（应拆分）: $(echo "$BIG" | tr '\n' ' ')"
fi

if [ -d "$HERMES_DIR/skills" ]; then
  SK_N=$(find "$HERMES_DIR/skills" -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ')
  AR_N=$(find "$HERMES_DIR/skills/.archive" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [ "$SK_N" -gt 60 ]; then
    warn "活跃技能 $SK_N 个 —— 过多会互相干扰触发（已归档 $AR_N）"
  else
    ok "活跃技能 $SK_N 个（已归档 $AR_N）"
  fi
fi
[ "$QUIET" = "1" ] || echo

# ---------- 6. 定时任务 ----------
section "6. 定时任务"
if [ -d "$HERMES_DIR/cron" ]; then
  CR_N=$(find "$HERMES_DIR/cron" -type f 2>/dev/null | wc -l | tr -d ' ')
  [ "$CR_N" -gt 0 ] && ok "已配置 $CR_N 个定时任务" || info "无定时任务"
  # 提醒人工确认来源（安全）
  [ "$CR_N" -gt 0 ] && info "确认这些任务全部由你创建"
else
  info "无 cron 目录"
fi
[ "$QUIET" = "1" ] || echo

# ---------- 7. 系统资源 ----------
section "7. 系统资源"
LOAD=$(awk '{print $1}' /proc/loadavg 2>/dev/null)
NCPU=$(nproc 2>/dev/null || echo 4)
if [ -n "$LOAD" ]; then
  BUSY=$(awk -v l="$LOAD" -v c="$NCPU" 'BEGIN{printf "%d", (l/c)*100}')
  if [ "$BUSY" -ge 150 ]; then
    warn "负载 ${LOAD}（${NCPU} 核，约 ${BUSY}%）—— 偏高"
  else
    ok "负载 ${LOAD}（${NCPU} 核，约 ${BUSY}%）"
  fi
fi

MEM_AVAIL=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo 2>/dev/null)
if [ -n "$MEM_AVAIL" ]; then
  if [ "$MEM_AVAIL" -lt 500 ]; then
    warn "可用内存仅 ${MEM_AVAIL}MB —— 有 OOM 风险"
  else
    ok "可用内存 ${MEM_AVAIL}MB"
  fi
fi

# Docker 容器内存（如适用）
if [ -n "$CNAME" ]; then
  CMEM=$(docker stats --no-stream --format '{{.MemUsage}}' "$CNAME" 2>/dev/null)
  [ -n "$CMEM" ] && info "容器内存占用: $CMEM"
fi
[ "$QUIET" = "1" ] || echo

# ---------- 汇总 ----------
if [ "$QUIET" = "1" ]; then
  # quiet 模式：只有 warn/risk 已经打印过，这里给一行汇总
  if [ "$RISK_COUNT" -gt 0 ] || [ "$WARN_COUNT" -gt 0 ]; then
    echo "--"
    echo "汇总: RISK=$RISK_COUNT WARN=$WARN_COUNT  ($(date '+%F %T'))"
  fi
else
  echo "=============================================="
  echo " 汇总: RISK=$RISK_COUNT  WARN=$WARN_COUNT"
  if [ "$RISK_COUNT" -gt 0 ]; then
    echo " 存在严重问题，建议立即处理"
  elif [ "$WARN_COUNT" -gt 0 ]; then
    echo " 有告警项，建议关注"
  else
    echo " 一切正常"
  fi
  echo "=============================================="
fi
