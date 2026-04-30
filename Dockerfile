FROM python:3.11 AS builder

WORKDIR /src

# 先复制依赖文件，利用缓存
COPY requirements.txt pyproject.toml ./

RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# 再复制源码并安装
COPY . .
RUN . /opt/venv/bin/activate \
    && pip install --no-cache-dir --no-deps .

FROM python:3.11-slim
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src/scripts/docker-entrypoint.sh /entrypoint.sh

ENV TZ="Asia/Shanghai"
ENV EK_IN_DOCKER="1"

WORKDIR /app
RUN chmod +x /entrypoint.sh \
    && touch config.toml
ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["/entrypoint.sh"]
