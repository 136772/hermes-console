#!/usr/bin/env bash
# ============================================================================
# Hermes 工作台 · 启动 / 守护脚本（方式 A：宿主机直接跑，不用容器）
#
# 解决的问题：靠 `nohup python3 app.py &` 起的进程，NAS 一重启就没了，
# 而且崩了不会自己起来 —— 你以为在监控，其实监控已经挂了。
#
# 这个脚本带一只看门狗：每 30 秒看一眼进程在不在，不在就拉起来。
#
# 用法：
#   ./start-dash.sh            # 前台运行，Ctrl-C 退出（看日志用）
#   ./start-dash.sh --daemon   # 后台守护（推荐，NAS 上长期跑）
#
# 开机自启（二选一）：
#   1) crontab -e 加一行：  @reboot /path/start-dash.sh --daemon
#   2) 或把下面 [Install] 段的 systemd 单元启用（见 hermes-console.service）
# ============================================================================
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

PORT="${DASH_PORT:-8080}"
PIDFILE="$DIR/.dash.pid"
LOGFILE="$DIR/dash.log"
APP="$DIR/app.py"

# 从 .env 派生环境变量（没有就跳过，用脚本里默认值）
if [ -f "$DIR/.env" ]; then
  set -a
  # 只认白名单里的几个，避免把 DEEPSEEK_API_KEY 之类也塞进来（其实也没事，但干净点）
  while IFS='=' read -r k v; do
    case "$k" in
      HERMES_DIR|HERMES_MODE|HERMES_CONTAINER|QUOTA_MB|CHAT_TIMEOUT|\
      BUDGET_DAILY|BUDGET_MONTHLY|ALERT_INTERVAL|DASH_READ_ONLY|\
      DASH_DANGER_TOKEN|COMPOSE_DIR|SCRIPT_DIR|TZ|PORT|\
      DASH_AUTH|SESSION_HOURS|DASH_SECURE_COOKIE|UPDATE_REPO|\
      HERMES_API|HERMES_API_TOKEN|PROXY_TIMEOUT)
        v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
        export "$k=$v" ;;
    esac
  done < "$DIR/.env"
  set +a
fi

# 保证依赖在
python3 -c "import flask, ruamel.yaml" 2>/dev/null || {
  echo "[start-dash] 缺少依赖：pip3 install flask ruamel.yaml" >&2
  exit 1
}

is_running() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_one() {
  HERMES_DIR="${HERMES_DIR:-/opt/data}" \
  HERMES_MODE="${HERMES_MODE:-auto}" \
  QUOTA_MB="${QUOTA_MB:-10240}" \
  PORT="$PORT" \
  nohup python3 "$APP" >> "$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  echo "[start-dash] 已启动 pid=$(cat "$PIDFILE")  (日志: $LOGFILE)"
}

if [ "${1:-}" = "--daemon" ]; then
  echo "[start-dash] 看门狗启动，每 30s 检查一次（日志: $LOGFILE）"
  while true; do
    if ! is_running; then
      echo "[$(date '+%F %T')] 进程不在，重新拉起" >> "$LOGFILE"
      start_one
    fi
    sleep 30
  done
else
  is_running && { echo "[start-dash] 已在运行 pid=$(cat "$PIDFILE")"; exit 0; }
  start_one
  echo "[start-dash] 已前台启动，Ctrl-C 退出。要看后台守护请用 --daemon"
  # 前台模式直接把日志跟到终端
  tail -F "$LOGFILE" 2>/dev/null
fi
