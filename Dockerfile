# API 镜像：仅依赖 Python 基础镜像；Node 用可校验、可重试的二进制安装
ARG PYTHON_IMAGE=docker.1ms.run/library/python:3.12.5-slim-bookworm
ARG NODE_VERSION=20.18.1
# node-v20.18.1-linux-x64.tar.xz 官方 SHA256（换版本时请同步更新）
ARG NODE_SHA256=c6fa75c841cbffac851678a472f2a5bd612fff8308ef39236190e1f8dbb0e567

FROM ${PYTHON_IMAGE}

ARG NODE_VERSION=20.18.1
ARG NODE_SHA256=c6fa75c841cbffac851678a472f2a5bd612fff8308ef39236190e1f8dbb0e567

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    POETRY_VERSION=1.8.5 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    PATH="/usr/local/bin:${PATH}"

# apt 国内源 + 编译/运行依赖（与 Node 下载拆层，便于缓存）
RUN set -eux; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        default-libmysqlclient-dev \
        pkg-config \
        xz-utils \
    ; \
    rm -rf /var/lib/apt/lists/*

# Node / npm / npx（供 MCP stdio）
# - 多镜像源回退 + curl 重试，避免 npmmirror 单点截断
# - 下载后强制 SHA256，截断包会直接失败并换源重试，而不是 tar 半截解压
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64) node_arch=linux-x64 ;; \
      arm64) node_arch=linux-arm64 ;; \
      *) echo "unsupported arch: ${arch}"; exit 1 ;; \
    esac; \
    tgz="node-v${NODE_VERSION}-${node_arch}.tar.xz"; \
    dest="/tmp/${tgz}"; \
    ok=0; \
    for attempt in 1 2 3 4 5; do \
      for base in \
        "https://cdn.npmmirror.com/binaries/node" \
        "https://npmmirror.com/mirrors/node" \
        "https://mirrors.cloud.tencent.com/nodejs-release" \
        "https://mirrors.huaweicloud.com/nodejs-release" \
        "https://nodejs.org/dist"; do \
        url="${base}/v${NODE_VERSION}/${tgz}"; \
        echo "==> attempt ${attempt}: ${url}"; \
        rm -f "${dest}"; \
        if ! curl -fL \
            --retry 5 \
            --retry-delay 2 \
            --retry-all-errors \
            --connect-timeout 30 \
            --max-time 600 \
            -o "${dest}" \
            "${url}"; then \
          echo "curl failed: ${url}"; \
          continue; \
        fi; \
        if [ ! -s "${dest}" ]; then \
          echo "empty download: ${url}"; \
          continue; \
        fi; \
        if [ "${node_arch}" = "linux-x64" ] && [ -n "${NODE_SHA256}" ]; then \
          if echo "${NODE_SHA256}  ${dest}" | sha256sum -c -; then \
            ok=1; \
            break 2; \
          fi; \
          echo "sha256 mismatch for ${url}"; \
          continue; \
        fi; \
        sum_url="${base}/v${NODE_VERSION}/SHASUMS256.txt"; \
        if curl -fsSL --connect-timeout 20 --max-time 60 -o /tmp/SHASUMS256.txt "${sum_url}" \
          && grep -E "  ${tgz}\$" /tmp/SHASUMS256.txt \
            | awk -v f="${dest}" '{print $1 "  " f}' \
            | sha256sum -c -; then \
          ok=1; \
          break 2; \
        fi; \
        echo "checksum verify failed for ${url}"; \
      done; \
      sleep $((attempt * 2)); \
    done; \
    test "${ok}" = "1"; \
    tar -xJf "${dest}" -C /usr/local --strip-components=1; \
    rm -f "${dest}" /tmp/SHASUMS256.txt; \
    node -v && npm -v && npx -v

WORKDIR /app

RUN pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY tests ./tests

RUN poetry install --only main --no-ansi \
    && npm install -g mssql-mcp-server \
    && apt-get update \
    && apt-get purge -y --auto-remove build-essential pkg-config \
    && rm -rf /root/.cache /tmp/* /var/lib/apt/lists/*

COPY docker/api/entrypoint.sh /entrypoint.sh
# Windows 检出常为 CRLF，会导致 exec /entrypoint.sh: no such file or directory
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
