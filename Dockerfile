FROM python:3.11-slim

WORKDIR /app

# 可选：容器内安装 docker CLI（docker 模式、网页对话需要）+ git（页面内自更新需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
        docker-cli git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 默认走清华 PyPI 源（国内机器拉包快很多）；
# 需要默认 PyPI 时：--build-arg PIP_INDEX=https://pypi.org/simple
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -i ${PIP_INDEX} \
        -r requirements.txt

COPY app.py hermes_ctl.py cost.py notify.py auth.py ./
COPY templates/ templates/
COPY static/ static/
COPY health-check.sh /app/health-check.sh
COPY security-check.sh /app/security-check.sh
COPY VERSION /app/VERSION
RUN chmod +x /app/health-check.sh /app/security-check.sh

# 让工作台以「和 Hermes 同一个 UID」运行（飞牛上 hermes 用户 = 1001）。
# 这样它写出的文件归属一致，且自动计入那个用户的 10G 配额。
RUN groupadd -g 1001 dash && useradd -u 1001 -g 1001 -M dash 2>/dev/null || true
USER dash

ENV PORT=8080 \
    HERMES_DIR=/opt/data \
    QUOTA_MB=10240 \
    SCRIPT_DIR=/app \
    BUDGET_DAILY=0 \
    BUDGET_MONTHLY=0 \
    ALERT_INTERVAL=600

EXPOSE 8080

CMD ["python", "app.py"]
