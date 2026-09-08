#!/usr/bin/env bash
# ============================================================
# Hermes Console 通用一键部署脚本
# 自动识别系统 / 三选一菜单 / 交互+参数双模 / 国内源自动检测
# ============================================================
set -euo pipefail

INSTALL_VERSION="1.3.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 彩色输出 ----------
green() { printf "\033[32m%s\033[0m\n" "$*"; }
info()  { printf "\033[36m%s\033[0m\n" "$*"; }
warn()  { printf "\033[33m%s\033[0m\n" "$*"; }
error() { printf "\033[31m%s\033[0m\n" "$*" >&2; }

# ---------- 默认值 ----------
ACTION=""
MODE=""
HERMES_DIR="/opt/hermes/data"
PORT=8080
HERMES_UID=1001
QUOTA_MB=10240
HERMES_CONTAINER="hermes"
DANGER_TOKEN=""
CN_MIRROR=""          # 空=自动检测
BUDGET_DAILY=0
BUDGET_MONTHLY=0
TZ="Asia/Shanghai"
UPDATE_REPO=""
ASSUME_YES=false

# ============================================================
# 1. 帮助
# ============================================================
show_help() {
  cat <<'EOF'
Hermes Console 通用一键部署脚本 v1.3.0

用法: ./install.sh [参数]   (无参数时交互式问答)

核心参数:
  --action ACTION       install | hermes+dash | update
  --mode MODE           docker | host | systemd
  --hermes-dir PATH     Hermes 数据目录 (默认 /opt/hermes/data)
  --port PORT           工作台端口 (默认 8080)
  --uid UID             运行用户 UID (默认 1001)
  --quota MB            配额 MB (默认 10240)
  --container NAME      Hermes 容器名 (默认 hermes)
  --danger-token TOKEN   危险动作令牌 (默认自动生成)
  --budget-daily 元     每日预算 (默认 0=不限)
  --budget-monthly 元   每月预算 (默认 0=不限)
  --tz TZ               时区 (默认 Asia/Shanghai)
  --repo OWNER/REPO     自更新仓库
  --cn-mirror           强制配国内源
  --no-cn-mirror        强制不配国内源
  -y / --yes            跳过所有确认提示
  --help                显示此帮助

示例:
  # 交互式部署
  ./install.sh

  # Docker 模式一键部署工作台
  ./install.sh --action install --mode docker --yes

  # Hermes + 工作台一起装
  ./install.sh --action hermes+dash --mode docker --port 8080

  # 只更新工作台
  ./install.sh --action update

  # 宿主机模式，自定义路径
  ./install.sh --mode host --hermes-dir /data/hermes --port 9000
EOF
}

# ============================================================
# 2. 系统检测
# ============================================================
detect_os() {
  if [ -f /etc/fnos-release ] || [ -f /etc/feinos-release ]; then
    echo "fnos"
  elif [ "$(uname -s)" = "Darwin" ]; then
    echo "macos"
  elif [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
      debian|ubuntu) echo "debian" ;;
      centos|rhel|fedora|rocky|almalinux) echo "centos" ;;
      alpine) echo "alpine" ;;
      *) echo "unknown" ;;
    esac
  else
    echo "unknown"
  fi
}

detect_arch() {
  local a
  a="$(uname -m)"
  case "$a" in
    x86_64|amd64)  echo "x86_64" ;;
    arm64|aarch64) echo "arm64" ;;
    armv7l)        echo "armv7l" ;;
    *)             echo "$a" ;;
  esac
}

detect_cn() {
  # 尝试 ip.cip.cc，超时 3s
  local body
  body="$(curl -sS --max-time 3 http://ip.cip.cc 2>/dev/null || true)"
  if echo "$body" | grep -qi "China"; then
    echo "yes"
    return
  fi
  # 备用：按时区判断
  if [ -n "${LANG:-}" ] && echo "$LANG" | grep -qi "zh"; then
    echo "yes"
    return
  fi
  echo "no"
}

detect_docker_gid() {
  if command -v getent &>/dev/null; then
    getent group docker 2>/dev/null | cut -d: -f3 || echo ""
  else
    echo ""
  fi
}

detect_python() {
  if command -v python3 &>/dev/null; then
    local v
    v="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
    local major="${v%%.*}"
    local minor="${v#*.}"
    if [ "$major" -ge 3 ] && [ "${minor:-0}" -ge 10 ]; then
      echo "$v"
      return
    fi
  fi
  echo ""
}

detect_hermes() {
  if command -v hermes &>/dev/null; then
    echo "cli"
  elif command -v docker &>/dev/null && docker ps --format '{{.Names}}' 2>/dev/null | grep -qi hermes; then
    echo "docker"
  else
    echo ""
  fi
}

# ============================================================
# 3. 参数解析
# ============================================================
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --help|-h)    show_help; exit 0 ;;
      --action)     ACTION="$2"; shift 2 ;;
      --mode)        MODE="$2"; shift 2 ;;
      --hermes-dir) HERMES_DIR="$2"; shift 2 ;;
      --port)        PORT="$2"; shift 2 ;;
      --uid)         HERMES_UID="$2"; shift 2 ;;
      --quota)       QUOTA_MB="$2"; shift 2 ;;
      --container)   HERMES_CONTAINER="$2"; shift 2 ;;
      --danger-token) DANGER_TOKEN="$2"; shift 2 ;;
      --cn-mirror)   CN_MIRROR="yes"; shift ;;
      --no-cn-mirror) CN_MIRROR="no"; shift ;;
      --budget-daily) BUDGET_DAILY="$2"; shift 2 ;;
      --budget-monthly) BUDGET_MONTHLY="$2"; shift 2 ;;
      --tz)          TZ="$2"; shift 2 ;;
      --repo)        UPDATE_REPO="$2"; shift 2 ;;
      -y|--yes)      ASSUME_YES=true; shift ;;
      *) error "未知参数: $1  (用 --help 查看帮助)"; exit 1 ;;
    esac
  done
}

# ============================================================
# 4. 交互式问答
# ============================================================
ask() {
  # ask "提示语" "默认值" → 输出用户输入或默认值
  local prompt="$1" default="$2"
  local input
  if $ASSUME_YES; then
    echo "$default"
    return
  fi
  read -rp "$(printf "\033[36m%s\033[0m [%s]: " "$prompt" "$default")" input || true
  echo "${input:-$default}"
}

ask_menu() {
  # ask_menu "提示语" "选项1" "选项2" "选项3" → 输出选中项的索引(1-3)
  local prompt="$1"; shift
  local options=("$@")
  local i=1
  echo ""
  for opt in "${options[@]}"; do
    echo "  $i) $opt"
    i=$((i + 1))
  done
  local choice
  if $ASSUME_YES; then
    choice=1
  else
    read -rp "$(printf "\033[36m%s\033[0m [1]: " "$prompt")" choice || true
    choice="${choice:-1}"
  fi
  echo "$choice"
}

interactive_setup() {
  # 1. 动作
  if [ -z "$ACTION" ]; then
    local c
    c=$(ask_menu "要做什么？" "只装工作台" "Hermes + 工作台一起装" "只更新工作台")
    case "$c" in
      1) ACTION="install" ;;
      2) ACTION="hermes+dash" ;;
      3) ACTION="update" ;;
    esac
  fi

  # 更新模式不需要问部署方式
  if [ "$ACTION" = "update" ]; then
    info "更新模式：自动检测现有部署方式"
    if [ -f "$SCRIPT_DIR/.dash.pid" ]; then
      MODE="host"
    elif systemctl is-active hermes-console &>/dev/null; then
      MODE="systemd"
    else
      MODE="docker"
    fi
    return
  fi

  # 2. 部署方式
  if [ -z "$MODE" ]; then
    local c
    c=$(ask_menu "部署方式？" "Docker Compose（推荐）" "宿主机直跑" "systemd 服务")
    case "$c" in
      1) MODE="docker" ;;
      2) MODE="host" ;;
      3) MODE="systemd" ;;
    esac
  fi

  # 3. 数据目录
  HERMES_DIR=$(ask "Hermes 数据目录" "$HERMES_DIR")

  # 4. 端口
  PORT=$(ask "工作台端口" "$PORT")

  # 5. UID
  HERMES_UID=$(ask "运行用户 UID" "$HERMES_UID")

  # 6. 容器名（docker 模式才问）
  if [ "$MODE" = "docker" ]; then
    HERMES_CONTAINER=$(ask "Hermes 容器名" "$HERMES_CONTAINER")
  fi

  # 7. 配额
  QUOTA_MB=$(ask "配额 MB" "$QUOTA_MB")

  # 8. 危险令牌
  if [ -z "$DANGER_TOKEN" ]; then
    local c
    c=$(ask_menu "危险动作令牌" "自动生成（推荐）" "手动输入")
    if [ "$c" = "1" ]; then
      DANGER_TOKEN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
    else
      DANGER_TOKEN=$(ask "输入令牌" "")
    fi
  fi

  # 9. 预算
  BUDGET_DAILY=$(ask "每日预算（元，0=不限）" "$BUDGET_DAILY")
  BUDGET_MONTHLY=$(ask "每月预算（元，0=不限）" "$BUDGET_MONTHLY")

  # 10. 国内源
  if [ -z "$CN_MIRROR" ]; then
    local detected
    detected=$(detect_cn)
    if [ "$detected" = "yes" ]; then
      info "检测到中国网络 → 自动配置国内源"
      CN_MIRROR="yes"
    else
      info "未检测到中国网络 → 跳过国内源"
      CN_MIRROR="no"
    fi
  fi
}

# ============================================================
# 5. 国内源配置
# ============================================================
setup_cn_mirror() {
  [ "$CN_MIRROR" != "yes" ] && return
  info "配置国内镜像源..."

  # pip
  if command -v pip3 &>/dev/null; then
    pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null || true
    green "  ✓ pip 清华源"
  fi

  # docker
  if [ "$MODE" = "docker" ] && [ -d /etc/docker ]; then
    local dj=/etc/docker/daemon.json
    if [ ! -f "$dj" ] || ! grep -q "registry-mirrors" "$dj" 2>/dev/null; then
      cat > "$dj" <<'JSON'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://hub-mirror.c.163.com",
    "https://docker.1panel.top",
    "https://hub.rat.dev"
  ]
}
JSON
      green "  ✓ docker 镜像加速"
    fi
  fi

  # git
  if command -v git &>/dev/null; then
    git config --global url."https://ghproxy.net/https://github.com/".insteadOf "https://github.com/" 2>/dev/null || true
    green "  ✓ git ghproxy"
  fi

  # npm
  if command -v npm &>/dev/null; then
    npm config set registry https://registry.npmmirror.com 2>/dev/null || true
    green "  ✓ npm 淘宝源"
  fi
}

# ============================================================
# 6. 依赖检查
# ============================================================
check_deps() {
  local missing=()

  # python3
  local pyv
  pyv=$(detect_python)
  if [ -z "$pyv" ]; then
    missing+=("python3>=3.10")
  else
    green "  ✓ Python $pyv"
  fi

  # git
  if ! command -v git &>/dev/null; then
    missing+=("git")
  else
    green "  ✓ git"
  fi

  # docker（docker 模式才需要）
  if [ "$MODE" = "docker" ] && ! command -v docker &>/dev/null; then
    missing+=("docker")
  fi

  if [ ${#missing[@]} -gt 0 ]; then
    error "缺少依赖: ${missing[*]}"
    error "请先安装，然后重新运行此脚本。"
    case "$(detect_os)" in
      debian|ubuntu) info "  sudo apt install -y ${missing[*]}" ;;
      centos)        info "  sudo yum install -y ${missing[*]}" ;;
      alpine)        info "  sudo apk add --no-cache ${missing[*]}" ;;
      macos)         info "  brew install ${missing[*]}" ;;
    esac
    exit 1
  fi
}

# ============================================================
# 7. 生成 .env
# ============================================================
gen_env() {
  local envfile="$SCRIPT_DIR/.env"
  local hermes_api
  if [ "$MODE" = "docker" ]; then
    hermes_api="http://172.17.0.1:9119"
  else
    hermes_api="http://127.0.0.1:9119"
  fi

  cat > "$envfile" <<EOF
# Hermes Console 环境变量 (由 install.sh v${INSTALL_VERSION} 生成)

# Hermes 数据目录
HERMES_DIR=$HERMES_DIR

# 运行模式: docker | local | auto
HERMES_MODE=$([ "$MODE" = "docker" ] && echo docker || echo local)
HERMES_CONTAINER=$HERMES_CONTAINER

# 配额与超时
QUOTA_MB=$QUOTA_MB
CHAT_TIMEOUT=180

# 脚本目录
SCRIPT_DIR=$SCRIPT_DIR
TZ=$TZ

# 配置中心: 1=只读 0=可改
DASH_READ_ONLY=0

# 危险动作令牌
DASH_DANGER_TOKEN=$DANGER_TOKEN

# Hermes compose 目录（可选）
COMPOSE_DIR=

# 预算
BUDGET_DAILY=$BUDGET_DAILY
BUDGET_MONTHLY=$BUDGET_MONTHLY

# 告警巡检间隔
ALERT_INTERVAL=600

# 端口
PORT=$PORT

# 登录鉴权
DASH_AUTH=1
SESSION_HOURS=24
DASH_SECURE_COOKIE=0

# 官方仪表盘代理
HERMES_API=$hermes_api
HERMES_API_TOKEN=
PROXY_TIMEOUT=300

# 自更新仓库
UPDATE_REPO=$UPDATE_REPO
EOF
  green "  ✓ .env 已生成 ($envfile)"
}

# ============================================================
# 8. Docker 部署
# ============================================================
deploy_docker() {
  local docker_gid
  docker_gid=$(detect_docker_gid)
  if [ -z "$docker_gid" ]; then
    warn "未检测到 docker 组 GID，docker.sock 可能无法访问"
    warn "如果需要网页对话，请手动查 GID: getent group docker | cut -d: -f3"
    docker_gid=999
  fi

  # 生成 override
  local override="$SCRIPT_DIR/docker-compose.override.yml"
  cat > "$override" <<EOF
services:
  hermes-console:
    user: "$HERMES_UID:$HERMES_UID"
    ports:
      - "$PORT:8080"
    volumes:
      - $HERMES_DIR:/opt/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    group_add:
      - "$docker_gid"
    environment:
      HERMES_DIR: /opt/data
      HERMES_MODE: docker
      HERMES_CONTAINER: $HERMES_CONTAINER
      QUOTA_MB: "$QUOTA_MB"
      TZ: $TZ
      DASH_DANGER_TOKEN: "$DANGER_TOKEN"
      BUDGET_DAILY: "$BUDGET_DAILY"
      BUDGET_MONTHLY: "$BUDGET_MONTHLY"
      HERMES_API: "http://172.17.0.1:9119"
      PROXY_TIMEOUT: "300"
EOF
  green "  ✓ docker-compose.override.yml 已生成"

  info "构建并启动容器..."
  cd "$SCRIPT_DIR"
  docker compose up -d --build
  green "  ✓ 容器已启动"

  # 健康检查
  info "等待服务启动..."
  local i
  for i in $(seq 1 10); do
    if curl -s "http://localhost:$PORT/api/version" &>/dev/null; then
      green "  ✓ 服务已就绪 (第 ${i} 次探测)"
      return
    fi
    sleep 2
  done
  warn "服务探测未就绪，可能需要几秒，请稍后访问 http://localhost:$PORT"
}

# ============================================================
# 9. 宿主机部署
# ============================================================
# 装依赖 + 生成 .env（不启动进程，供 systemd 模式复用）
prepare_host() {
  info "安装 Python 依赖..."
  cd "$SCRIPT_DIR"
  pip3 install -r requirements.txt 2>&1 | tail -3
  green "  ✓ 依赖已安装"
  gen_env
}

deploy_host() {
  prepare_host

  info "启动工作台..."
  # 如果有旧进程，先停掉
  if [ -f "$SCRIPT_DIR/.dash.pid" ]; then
    local oldpid
    oldpid=$(cat "$SCRIPT_DIR/.dash.pid" 2>/dev/null || true)
    if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
      kill "$oldpid" 2>/dev/null || true
      info "  旧进程已停止"
    fi
  fi

  # 加载 .env
  set -a; . "$SCRIPT_DIR/.env"; set +a
  nohup python3 app.py > "$SCRIPT_DIR/dashboard.log" 2>&1 &
  echo $! > "$SCRIPT_DIR/.dash.pid"
  green "  ✓ 工作台已启动 (PID: $(cat "$SCRIPT_DIR/.dash.pid"))"

  # 健康检查
  local i
  for i in $(seq 1 8); do
    if curl -s "http://localhost:$PORT/api/version" &>/dev/null; then
      green "  ✓ 服务已就绪 (第 ${i} 次探测)"
      return
    fi
    sleep 2
  done
  warn "服务可能需要几秒，请稍后访问 http://localhost:$PORT"
}

# ============================================================
# 10. systemd 部署
# ============================================================
deploy_systemd() {
  # 只装依赖 + 生成 .env，绝不起 nohup 进程
  # （否则会和 systemd 抢同一端口，Restart=always 导致无限重启失败）
  prepare_host

  local svcfile="/etc/systemd/system/hermes-console.service"
  info "生成 systemd 服务..."
  cat > "$svcfile" <<EOF
[Unit]
Description=Hermes Console
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$(which python3) $SCRIPT_DIR/app.py
EnvironmentFile=$SCRIPT_DIR/.env
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now hermes-console
  green "  ✓ systemd 服务已启用"
}

# ============================================================
# 11. Hermes 联合部署
# ============================================================
deploy_hermes() {
  info "安装 Hermes Agent..."
  info "调用 Hermes 官方安装脚本..."
  if curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash; then
    green "  ✓ Hermes Agent 安装完成"
  else
    warn "Hermes 官方脚本执行失败（可能网络问题）"
    warn "请手动安装: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash"
    warn "安装后重新运行此脚本的 install 模式"
    return
  fi

  # 检测 hermes 命令
  local hstat
  hstat=$(detect_hermes)
  if [ -n "$hstat" ]; then
    green "  ✓ Hermes 检测到 ($hstat)"
  else
    warn "Hermes 命令未找到，可能需要 source ~/.bashrc 或重新登录"
  fi

  # 提示用户配置
  echo ""
  info "下一步（Hermes 配置）："
  echo "  1. hermes setup    # 配置模型 API Key"
  echo "  2. hermes dashboard  # 启动官方仪表盘后端（:9119）"
  echo ""

  # 启动 Hermes 官方仪表盘后端
  if [ -n "$hstat" ] && [ "$hstat" = "cli" ]; then
    info "启动 Hermes 官方仪表盘后端..."
    nohup hermes dashboard > "$SCRIPT_DIR/hermes-console-api.log" 2>&1 &
    green "  ✓ Hermes 仪表盘后端已启动 (:9119)"
  fi
}

# ============================================================
# 12. 更新工作台
# ============================================================
update_dashboard() {
  cd "$SCRIPT_DIR"
  info "拉取最新代码..."
  if git pull --ff-only 2>/dev/null; then
    green "  ✓ 代码已更新"
  else
    warn "git pull 失败，可能有本地修改。手动处理: git stash && git pull"
  fi

  case "$MODE" in
    docker)
      info "重建容器..."
      docker compose up -d --build
      green "  ✓ 容器已更新"
      ;;
    systemd)
      systemctl restart hermes-console
      green "  ✓ systemd 服务已重启"
      ;;
    host)
      if [ -f "$SCRIPT_DIR/.dash.pid" ]; then
        local pid
        pid=$(cat "$SCRIPT_DIR/.dash.pid" 2>/dev/null || true)
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
      fi
      set -a; . "$SCRIPT_DIR/.env" 2>/dev/null || true; set +a
      pip3 install -r requirements.txt 2>&1 | tail -2
      nohup python3 app.py > "$SCRIPT_DIR/dashboard.log" 2>&1 &
      echo $! > "$SCRIPT_DIR/.dash.pid"
      green "  ✓ 进程已重启 (PID: $(cat "$SCRIPT_DIR/.dash.pid"))"
      ;;
  esac
}

# ============================================================
# 13. 收尾摘要
# ============================================================
print_summary() {
  echo ""
  echo "================================================================"
  green "  Hermes Console v${INSTALL_VERSION} 部署完成！"
  echo "================================================================"
  echo ""

  # 初始密码位置
  local pwfile="$HERMES_DIR/DASHBOARD_PASSWORD.txt"
  if [ "$MODE" = "docker" ]; then
    pwfile="$HERMES_DIR/DASHBOARD_PASSWORD.txt (容器内 /opt/data/)"
  fi

  cat <<EOF
  部署模式:    $MODE
  工作台地址:  http://localhost:$PORT
  数据目录:    $HERMES_DIR
  初始密码:    $pwfile
  Hermes:      $HERMES_CONTAINER

  下一步:
  1. 查看初始密码: cat "$HERMES_DIR/DASHBOARD_PASSWORD.txt"
  2. 打开浏览器: http://localhost:$PORT
  3. 首次登录后强制改密
  4. 启动 Hermes 官方仪表盘（如未启动）: hermes dashboard
EOF

  echo ""
  echo "================================================================"
}

# ============================================================
# 14. 主流程
# ============================================================
main() {
  parse_args "$@"
  interactive_setup

  # 系统信息
  local os arch cn
  os=$(detect_os)
  arch=$(detect_arch)

  echo ""
  echo "================================================================"
  info "  Hermes Console 通用部署脚本 v${INSTALL_VERSION}"
  echo "================================================================"
  green "  系统: $os / $arch"
  if [ "$CN_MIRROR" = "yes" ]; then
    green "  国内源: 已配置"
  else
    info "  国内源: 跳过"
  fi
  echo ""

  # 更新模式
  if [ "$ACTION" = "update" ]; then
    update_dashboard
    print_summary
    exit 0
  fi

  # 检查依赖
  check_deps

  # 国内源
  setup_cn_mirror

  # Hermes 联合部署
  if [ "$ACTION" = "hermes+dash" ]; then
    deploy_hermes
  fi

  # 工作台部署
  case "$MODE" in
    docker)   deploy_docker ;;
    host)     deploy_host ;;
    systemd)  deploy_systemd ;;
    *)        error "未知模式: $MODE"; exit 1 ;;
  esac

  print_summary
}

main "$@"
