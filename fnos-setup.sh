#!/usr/bin/env bash
# =============================================================================
# 飞牛 NAS（FNOS）上部署 Hermes + 工作台 的「国内源 + 连接」一键准备脚本
# 作用：
#   1) 配置 pip / docker / git / npm 的国内可用镜像（国内拉包/拉镜像才不卡）
#   2) 创建 hermes 用户（UID 1001）与 10G 配额所需的数据目录，并修正归属
#   3) 把 Hermes 和工作台「连起来」：共用同一份数据目录 + 给工作台配好 docker 访问
# 用法：飞牛开 SSH 后，sudo bash fnos-setup.sh
# =============================================================================
set -euo pipefail

HERMES_USER="hermes"
HERMES_UID="1001"
HERMES_GID="1001"
DATA_DIR="/volume1/homes/hermes/data"          # Hermes 持久化目录（两件套共用）
HERMES_COMPOSE_DIR="/volume1/docker/hermes"
DASH_DIR="/volume1/docker/hermes-console"

green(){ echo -e "\033[32m[OK]\033[0m $*"; }
info(){ echo -e "\033[36m[..]\033[0m $*"; }
warn(){ echo -e "\033[33m[!!]\033[0m $*"; }

# -----------------------------------------------------------------------------
# 1) 国内镜像源
# -----------------------------------------------------------------------------
info "== 1. 配置国内镜像源 =="

# 1.1 pip：清华源（稳定、覆盖全）
mkdir -p /root/.pip /etc/pip.conf 2>/dev/null || true
cat > /etc/pip.conf <<'EOF'
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
timeout = 30
EOF
# 同时也给当前用户配一份（root 之外的用户也能用）
mkdir -p ~/.pip && cp /etc/pip.conf ~/.pip/pip.conf 2>/dev/null || true
green "pip -> 清华源 (pypi.tuna.tsinghua.edu.cn)"

# 1.2 docker：镜像加速器（pull 官方镜像用）
# 飞牛若自带「镜像加速」UI，直接在 UI 里填更稳妥；这里给出标准 daemon.json 写法。
# 下面给了几个国内公开加速地址，挑能通的（建议保留 2~3 个做兜底）。
DOCKER_JSON="/etc/docker/daemon.json"
mkdir -p /etc/docker
if [ -f "$DOCKER_JSON" ]; then
  warn "$DOCKER_JSON 已存在，已备份为 ${DOCKER_JSON}.bak"
  cp "$DOCKER_JSON" "${DOCKER_JSON}.bak"
fi
cat > "$DOCKER_JSON" <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://hub-mirror.c.163.com",
    "https://docker.1panel.top",
    "https://hub.rat.dev"
  ]
}
EOF
green "docker -> daemon.json 已写入镜像加速器（重启 dockerd 后生效）"
warn "生效方式：重启飞牛的 Docker 服务或重启 FNOS。nousresearch/hermes-agent 这种官方镜像靠它才拉得动。"

# 1.3 git：通过 ghproxy 加速 github.com 的 clone
git config --global url."https://ghproxy.net/https://github.com/".insteadOf "https://github.com/" 2>/dev/null || true
git config --global url."https://ghproxy.net/https://github.com/".insteadOf "git@github.com:" 2>/dev/null || true
green "git -> ghproxy.net 代理（clone github 仓库加速）"

# 1.4 npm：装 MCP 服务器（npx 类）时需要
if command -v npm >/dev/null 2>&1; then
  npm config set registry https://registry.npmmirror.com 2>/dev/null || true
  green "npm -> 淘宝源 (registry.npmmirror.com)"
else
  info "npm 未安装（Hermes 容器内装 MCP 时会自己拉，宿主机可忽略）"
fi

# -----------------------------------------------------------------------------
# 2) hermes 用户 + 数据目录（10G 配额的前提）
# -----------------------------------------------------------------------------
info "== 2. 创建 hermes 用户与数据目录 =="

# 飞牛的「用户」是它自己的账号体系，配额在 UI 里设（文档 Part 2.5）。
# 这里只保证：存在一个 UID=1001 的系统用户/组，且数据目录归属正确。
# 如果 UID 不是 1001，用 `id hermes` 查，并把上面的 HERMES_UID 改掉。
if ! getent group "$HERMES_GID" >/dev/null 2>&1; then
  groupadd -g "$HERMES_GID" "$HERMES_USER" 2>/dev/null || true
fi
if ! id -u "$HERMES_USER" >/dev/null 2>&1; then
  useradd -u "$HERMES_UID" -g "$HERMES_GID" -M -s /usr/sbin/nologin "$HERMES_USER" 2>/dev/null \
    || useradd -u "$HERMES_UID" -g "$HERMES_GID" -M "$HERMES_USER" 2>/dev/null || true
  green "已创建系统用户 ${HERMES_USER} (UID/GID=${HERMES_UID})"
else
  green "用户 ${HERMES_USER} 已存在 ($(id -u "$HERMES_USER"))"
fi

# 数据目录：两件套的唯一真相源
mkdir -p "$DATA_DIR" "$HERMES_COMPOSE_DIR" "$DASH_DIR"
chown -R "$HERMES_UID:$HERMES_GID" "$DATA_DIR"
chmod 700 "$DATA_DIR"
green "数据目录就绪：$DATA_DIR （归属 ${HERMES_UID}:${HERMES_GID}）"

# -----------------------------------------------------------------------------
# 3) 把工作台「连」到 Hermes 上
# -----------------------------------------------------------------------------
info "== 3. 连接工作台与 Hermes =="
cat <<EOF
连接方式只有两条，已在本脚本和 dashboard 的 docker-compose.yml 里配好：

  (A) 共用同一份数据目录
      Hermes 容器:  /volume1/homes/hermes/data -> /opt/data
      工作台容器:   /volume1/homes/hermes/data -> /opt/data   (HERMES_DIR=/opt/data)
      => config.yaml / SOUL.md / memories / skills / cron / logs / sessions 完全同一份

  (B) 对话/探测时，工作台用 docker exec 去敲正在跑的 Hermes 容器
      HERMES_MODE=docker  HERMES_CONTAINER=hermes
      => 工作台容器以 1001 身份运行，并挂了宿主机 docker 组，能访问 docker.sock

  两者跑不跑同一个用户？不必，但强烈建议工作台也用 1001：
      - 文件归属一致，Hermes 容器（1001）读得到工作台写的文件
      - 10G 配额按 UID 计，工作台写入也会计进 hermes 的配额，不会偷偷撑爆
EOF

# 自检：docker 组 GID（给 dashboard 的 group_add 用）
DOCKER_GID=$(getent group docker | cut -d: -f3 || echo "未找到")
if [ "$DOCKER_GID" != "未找到" ]; then
  warn "宿主机 docker 组 GID = $DOCKER_GID"
  warn "把它填进 dashboard/docker-compose.yml 的 group_add（当前注释着）"
else
  warn "没找到 docker 组（FNOS 可能用别的名字）；网页对话/探测需要它，请手动确认"
fi

echo
green "准备完成。下一步："
echo "  1) 把 hermes-console/ 整个目录拷到 $DASH_DIR"
echo "  2) 把 hermes-taming/docker-compose.yml 拷到 $HERMES_COMPOSE_DIR（已配好 UID 对齐）"
echo "  3) cd $HERMES_COMPOSE_DIR && docker compose up -d        # 起 Hermes"
echo "  4) cd $DASH_DIR && docker compose up -d --build          # 起工作台"
echo "  5) 浏览器开 http://<NAS的IP>:8080"
