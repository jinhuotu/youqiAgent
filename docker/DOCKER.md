# Docker 部署（推荐）

本项目提供 Docker Compose 一键编排：**MySQL + Redis + API + 运维台(nginx)**。  
对外仅暴露 **8091**（nginx）；后端不映射宿主机端口。镜像仅本地构建（不推仓库）。

目录约定：后端 `youqiAgent` 与前端 `youqiAgent-web` 为**同级**目录。

## 1. 准备

- 已安装 Docker / Docker Compose 插件
- 国内网络：默认基础镜像前缀 `docker.1ms.run/library/...`；pip 用阿里云；npm 用 npmmirror
- 若构建报 `docker/dockerfile` **403**：确认 Dockerfile **没有** `# syntax=docker/dockerfile:1`
- 若 api 日志反复出现 **`exec /entrypoint.sh: no such file or directory`**：多为 Windows 把脚本存成 CRLF。仓库已在镜像构建时 `sed` 去 `\r`；本地也可确认 `docker/api/entrypoint.sh` 为 LF，然后 `docker compose --env-file .env.docker up -d --build api`。
  - API 的 Node 安装已改为：**多镜像源回退 + curl 重试 + SHA256 校验**（截断包不会解压，会换源重试）。
  - 基础镜像拉取过慢：在 `.env.docker` 换 `PYTHON_IMAGE` 前缀，例如
    `docker.m.daocloud.io/library/python:3.12.5-slim-bookworm`、
    `mirror.ccs.tencentyun.com/library/python:3.12.5-slim-bookworm`，
    或本机 Hub 可达时直接用 `python:3.12.5-slim-bookworm`。
  - 仍失败：`docker builder prune -af` 后再 `--build`。

```bash
cd youqiAgent
cp .env.docker.example .env.docker
# 编辑 .env.docker：修改 MYSQL_* 密码、INTERNAL_SERVICE_TOKENS、ENCRYPTION_KEY、CORS_ORIGINS
```

数据目录：

| 环境 | `DATA_ROOT` |
|------|-------------|
| Windows 本机 | `./data`（默认） |
| 阿里云 Ubuntu | `/opt/youqiAgent/data` |

Ubuntu 示例：

```bash
sudo mkdir -p /opt/youqiAgent/data
# .env.docker 中设置：
# DATA_ROOT=/opt/youqiAgent/data
```

## 2. 构建并启动

在 **youqiAgent** 目录执行（会引用 `../youqiAgent-web`）：

```bash
docker compose --env-file .env.docker up -d --build
```

查看状态：

```bash
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs -f api
```

验证：

- 健康检查：http://127.0.0.1:8091/health  
- 运维台：http://127.0.0.1:8091/  
- 连接设置：Base URL 可留空后刷新，或填 `http://127.0.0.1:8091`（同源反代）  
  Service Token / User Id 与 `.env.docker` 中配置一致  

公网访问时，把 `http://你的公网IP:8091` 追加进 `.env.docker` 的 `CORS_ORIGINS`，然后：

```bash
docker compose --env-file .env.docker up -d api
```

## 3. 常用命令

```bash
# 重建并启动
docker compose --env-file .env.docker up -d --build

# 停止
docker compose --env-file .env.docker down

# 看日志
docker compose --env-file .env.docker logs -f web api
```

## 4. MCP 说明

- API 镜像内含 **Node / npm / npx**，并已全局预装 **mssql-mcp-server**
- 运维台 MCP 配置示例：命令 `npx`，参数每行 `-y` 与 `mssql-mcp-server`
- 工作目录挂载在 `${DATA_ROOT}/mcp`

## 5. 安全组

阿里云安全组放行 **TCP 8091**（勿再单独放行 8000，后端未映射）。

## 6. 与传统 systemd 部署的关系

不使用 Docker 时，仍可按本文后续章节（Poetry + systemd、端口 8000）部署。  
Docker 与 systemd **不要同时**占用同一套业务端口/数据目录，避免冲突。
