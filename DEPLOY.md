# 阿里云 ECS 部署指南（youqiAgent）

本文记录将本服务部署到阿里云 Ubuntu 服务器，并与本地运维台 `youqiAgent-web` 联调的完整步骤。  
适用环境示例：Ubuntu 22.04 LTS、2 核 4G、40GB 盘、公网 IP。

> **推荐优先使用 Docker Compose**（MySQL + Redis + API + 运维台，对外 **8091**）。见 [docker/DOCKER.md](./docker/DOCKER.md)。  
> 下文为不使用 Docker 时的 Poetry + systemd 传统方式（默认端口 **8000**）。

> 本服务为 **内部 API**，正式环境建议仅内网供 Java 调用；本地联调可临时开放公网端口。

---

## 一、服务器与规格建议

| 场景 | 建议规格 |
|------|----------|
| 内测 / 联调 | 2 核 4G（可同机 MySQL + Redis） |
| 正式小流量 | 4 核 8G；MySQL / Redis 建议用云产品拆分 |
| 本机跑 Ollama | 需另加大内存 / GPU，勿与 4G 机混跑 |

推荐镜像：**Ubuntu 22.04 LTS**。与 Java 同地域、同 VPC 时延迟更低。

---

## 二、登录服务器

使用 FinalShell / SSH 以 `root`（或具备 sudo 的用户）登录。

```bash
cat /etc/os-release
uname -m
free -h
df -h
python3 --version
```

Ubuntu 22.04 默认多为 **Python 3.10**，本项目要求 **≥ 3.11**，需单独安装。

---

## 三、系统准备

### 3.1 添加 Swap（4G 内存强烈建议）

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h
```

### 3.2 安装基础包与 Python 3.11

```bash
apt update
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt update
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip \
  git curl wget vim build-essential pkg-config default-libmysqlclient-dev
python3.11 --version
```

### 3.3 安装 Poetry

```bash
curl -sSL https://install.python-poetry.org | python3.11 -
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
poetry --version
poetry config virtualenvs.in-project true
```

### 3.4 安装 MySQL 与 Redis

```bash
apt install -y mysql-server redis-server
systemctl enable --now mysql redis-server
```

**重要：** Ubuntu 上 MySQL 的 `root` 默认使用 socket 认证，应用用密码连接会报：

```text
(1698, "Access denied for user 'root'@'localhost'")
```

请创建专用用户（密码请自行替换）：

```bash
sudo mysql
```

```sql
CREATE DATABASE IF NOT EXISTS agent_ai DEFAULT CHARSET utf8mb4;
CREATE USER IF NOT EXISTS 'agent'@'localhost' IDENTIFIED BY '你的强密码';
GRANT ALL PRIVILEGES ON agent_ai.* TO 'agent'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

验证：

```bash
mysql -u agent -p -e "SHOW DATABASES;"
redis-cli ping
```

---

## 四、拉取代码

```bash
rm -rf /opt/youqiAgent
git clone https://github.com/jinhuotu/youqiAgent.git /opt/youqiAgent
cd /opt/youqiAgent
ls -la
```

私有仓库需使用 GitHub Personal Access Token 作为密码。

> 若仓库中缺少 `README.md`，而 `pyproject.toml` 声明了 `readme = "README.md"`，  
> `poetry install` 可能报 `Readme path ... does not exist`。可临时执行：  
> `echo '# youqiAgent' > README.md`

---

## 五、国内 PyPI 镜像（避免下载超时）

服务器直连 `files.pythonhosted.org` 常出现 `Read timed out` / `Cannot install chromadb`。

```bash
poetry source add --priority=primary aliyun https://mirrors.aliyun.com/pypi/simple/

mkdir -p ~/.pip
cat > ~/.pip/pip.conf <<'EOF'
[global]
index-url = https://mirrors.aliyun.com/pypi/simple/
trusted-host = mirrors.aliyun.com
timeout = 300
EOF
```

备选清华源：

```text
https://pypi.tuna.tsinghua.edu.cn/simple/
```

---

## 六、配置环境变量

```bash
cd /opt/youqiAgent
cp .env.example .env
vim .env
```

生产联调关键项示例：

```env
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO
ENV=production
APP_VERSION=1.0.0

# 本地运维台跨域（按实际前端地址增删）
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=agent
MYSQL_PASSWORD=你的强密码
MYSQL_DATABASE=agent_ai

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

CHROMA_PERSIST_PATH=./data/chroma
UPLOAD_ROOT=./data/uploads

# 服务间鉴权：随机串，前端 / Java 请求头 X-Service-Token 携带
INTERNAL_SERVICE_TOKENS=

# 数据库敏感字段加密，勿与上面 Token 混用
ENCRYPTION_KEY=
```

生成密钥：

```bash
# INTERNAL_SERVICE_TOKENS
openssl rand -hex 32

# ENCRYPTION_KEY（需已安装 cryptography，可在 poetry install 之后生成）
poetry run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 七、安装依赖与数据库迁移

```bash
cd /opt/youqiAgent
mkdir -p data/chroma data/uploads logs

poetry env use python3.11

# 若提示 lock 与 pyproject 不一致
# poetry lock

poetry install --only main
# 若仅缺 README 导致装项目失败：补 README 后重跑，或临时
# poetry install --only main --no-root
```

迁移：

```bash
poetry run alembic upgrade head
mysql -u agent -p agent_ai -e "SHOW TABLES;"
```

---

## 八、启动服务（systemd）

### 8.1 前台试跑（可选）

```bash
cd /opt/youqiAgent
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
# 另开终端
curl http://127.0.0.1:8000/health
# 应返回 {"status":"ok","version":"1.0.0"}
# Ctrl+C 停掉后再配 systemd
```

### 8.2 写入 systemd（4G 机器建议 workers=1）

```bash
cat >/etc/systemd/system/youqi-agent.service <<'EOF'
[Unit]
Description=youqiAgent AI Service
After=network.target mysql.service redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/youqiAgent
EnvironmentFile=/opt/youqiAgent/.env
ExecStart=/opt/youqiAgent/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now youqi-agent
systemctl status youqi-agent --no-pager
curl http://127.0.0.1:8000/health
```

常用命令：

```bash
systemctl restart youqi-agent
systemctl stop youqi-agent
journalctl -u youqi-agent -n 80 --no-pager
```

### 8.3 端口占用（Address already in use）

若日志出现 `[Errno 98] Address already in use`，说明 **8000 已被占用**（常见于前台 uvicorn 未关，又与 systemd 同时启动）。

```bash
systemctl stop youqi-agent
ss -lntp | grep 8000
pkill -f 'uvicorn app.main:app' || true
ss -lntp | grep 8000   # 无输出即空闲
systemctl start youqi-agent
systemctl status youqi-agent --no-pager
```

**只保留一种启动方式：要么 systemd，要么前台手动，不要同时开两份。**

成功标志：

- `Active: active (running)`（不是 `activating (auto-restart)`）
- `curl http://127.0.0.1:8000/health` 返回 ok

---

## 九、阿里云安全组（公网访问）

控制台路径任选其一：

1. **ECS → 左侧「网络与安全」→「安全组」→ 配置规则 → 入方向 → 手动添加**
2. **实例详情 → 安全组 → 进入规则 → 入方向 → 手动添加**

添加规则：

| 项 | 值 |
|----|-----|
| 授权策略 | 允许 |
| 优先级 | 1 |
| 协议 | 自定义 TCP |
| 端口 | 8000/8000 |
| 授权对象 | 联调可用 `0.0.0.0/0`；正式建议本机公网 IP `/32` |

浏览器验证（把 IP 换成你的公网 IP）：

```text
http://你的公网IP:8000/health
```

示例：`http://115.29.201.166:8000/health` → `{"status":"ok","version":"1.0.0"}`

业务接口需带鉴权头，例如：

```bash
curl -X GET http://你的公网IP:8000/api/v1/internal/system/info \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: 你的INTERNAL_SERVICE_TOKENS" \
  -H "X-User-Id: 10001"
```

---

## 十、本地前端 youqiAgent-web 连接远程后端

前端项目路径示例：`D:\code\python\youqiAgent-web`。

### 10.1 页面「连接设置」（推荐）

1. `npm run dev`，打开 http://127.0.0.1:5173  
2. 进入 **系统总览 / 连接设置**  
3. 填写：

| 项 | 说明 |
|----|------|
| API Base URL | `http://你的公网IP:8000`（不要带 `/health`） |
| Service Token | 与服务器 `INTERNAL_SERVICE_TOKENS` **完全一致**（对应请求头 `X-Service-Token`） |
| User Id | 任意业务用户 ID，如 `001` |
| Role | 管理公共资源选 `admin` |

4. **测试连接** → **保存配置**（写入浏览器 `localStorage`，键名 `youqi_ops_connection`）

### 10.2 默认环境变量（仅影响首次默认值）

文件：`youqiAgent-web/.env.development`

```env
VITE_API_BASE_URL=http://你的公网IP:8000
```

**注意：** 若浏览器已保存过连接配置，会 **覆盖** `.env` 默认值。改 `.env` 后仍显示本地地址时：

1. 在连接设置里改 URL 并保存，或  
2. 控制台执行：`localStorage.removeItem('youqi_ops_connection'); location.reload()`

### 10.3 Network 面板如何核对

Vite 加载的 `http://localhost:5173/src/.../*.vue` 是 **前端源码**，不是后端。  
请筛选 XHR/Fetch，查看例如：

```text
http://你的公网IP:8000/api/v1/internal/models
```

### 10.4 CORS

服务器 `.env` 中 `CORS_ORIGINS` 必须包含前端来源（如 `http://localhost:5173`），修改后：

```bash
systemctl restart youqi-agent
```

---

## 十一、代码更新

```bash
cd /opt/youqiAgent
git pull
poetry install --only main
poetry run alembic upgrade head
systemctl restart youqi-agent
```

---

## 十二、常见问题速查

| 现象 | 处理 |
|------|------|
| Python 3.10 | 安装并使用 `python3.11` + `poetry env use python3.11` |
| PyPI / chromadb 超时 | 配置阿里云或清华 Poetry/pip 镜像 |
| `root@localhost` 1698 | 改用 `agent` 用户 + 密码，勿用 Ubuntu 默认 root 密码登录 |
| `README.md does not exist` | 补 README 或 `poetry install --no-root` |
| `Address already in use` | 停掉多余 uvicorn，只保留 systemd |
| systemd `activating` 循环 | `journalctl -u youqi-agent -n 80` 查原因 |
| 外网打不开 8000 | 查安全组是否放行 TCP 8000 |
| 前端仍访问 127.0.0.1 | 改「连接设置」并保存，或清 `youqi_ops_connection` |
| 401 鉴权失败 | Service Token 与服务器 `INTERNAL_SERVICE_TOKENS` 不一致 |
| MCP stdio 启动失败 | 确认已安装 Node/`npx`，白名单含该命令，工作目录 `MCP_WORKDIR` 可写 |

---

## 十二点五、MCP（外部工具）

1. 执行迁移：`poetry run alembic upgrade head`（含 `008_mcp_servers`）。  
2. 若使用 `npx` 拉起 MCP Server，服务器需安装 Node.js，并可访问 npm（或预装包）。  
3. `.env` 配置 `MCP_WORKDIR`、`MCP_COMMAND_ALLOWLIST` 等；stdio **仅管理员**可在运维台维护。  
4. 运维台「MCP 管理」→ 添加 Server → **同步**工具 → 启用后对话自动全局可用。  
5. filesystem 类工具请将参数中的目录限制在 `MCP_WORKDIR` 内，勿挂载整盘。

---

## 十三、安全建议

1. 正式环境将 `ENV=production`，关闭 Swagger。  
2. 安全组 `8000` 不要长期对 `0.0.0.0/0` 开放；优先 Java 内网调用。  
3. 勿将 `.env`、Token、数据库密码提交到 Git 或发到公开聊天。  
4. 定期备份 `data/chroma`、`data/uploads`、`data/mcp` 与 MySQL。  
5. `ENCRYPTION_KEY` 与 `INTERNAL_SERVICE_TOKENS` 用途不同，不要混用。  
6. MCP stdio 可执行本机命令，务必限制管理员权限与命令白名单。

---

## 十四、部署检查清单

- [ ] Python 3.11 + Poetry + 国内镜像  
- [ ] MySQL `agent` 用户 + 库 `agent_ai`；Redis 正常  
- [ ] 代码在 `/opt/youqiAgent`，`.env` 已配置  
- [ ] `poetry install --only main` 成功（含 `mcp` 依赖）  
- [ ] `alembic upgrade head` 成功  
- [ ] `youqi-agent` 为 `active (running)`  
- [ ] 本机 `curl 127.0.0.1:8000/health` 成功  
- [ ] 安全组放行 8000；公网 `/health` 成功  
- [ ] 前端连接设置指向公网 API + 正确 Service Token  
- [ ]（可选）MCP：Node/`npx` 可用，`MCP_WORKDIR` 已创建  