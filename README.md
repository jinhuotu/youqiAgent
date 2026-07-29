# Agent AI Service

内部 AI 能力下沉服务：基于 FastAPI + LangChain，面向 Java 业务后端与运维台提供标准化 HTTP 接口。

- **不对外暴露**、无独立用户鉴权体系
- 调用方携带 `X-Service-Token` + `X-User-Id` 内网调用
- 按 `user_id` 行级数据隔离

> **能力边界（请勿误解）：** 当前已实现模型管理、多轮对话（SSE）、提示词、知识库上传/向量化/RAG、**外部 MCP 工具调用**。  
> 完整工作流编排 / 自建 MCP Server 仍为后续演进项。

## 技术栈

| 组件 | 版本要求 |
|------|----------|
| Python | ≥ 3.11 |
| FastAPI | 最新稳定版 |
| LangChain | ≥ 1.0（对话 / Embedding） |
| SQLAlchemy | ≥ 2.0 |
| MySQL + Redis + ChromaDB | ChromaDB ≥ 1.0 |
| Poetry | 依赖管理 |

## 快速开始

### 方式 A：Docker Compose（推荐）

需本机已安装 Docker，且 `youqiAgent` 与 `youqiAgent-web` 为同级目录。详情见 [`docker/DOCKER.md`](./docker/DOCKER.md)。

```bash
cd youqiAgent
cp .env.docker.example .env.docker
# 编辑密钥与 CORS 后：
docker compose --env-file .env.docker up -d --build
# 浏览器打开 http://127.0.0.1:8091
```

### 方式 B：本地 Poetry

1. 安装 Poetry：`pip install poetry`
2. 安装依赖：`cd youqiAgent && poetry install`
3. 配置环境变量：

```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

编辑 `.env`，至少配置：

- MySQL 连接信息，并预先创建数据库：`CREATE DATABASE agent_ai DEFAULT CHARSET utf8mb4;`
- Redis（知识库任务队列依赖；不可用时会降级为临时线程）
- `INTERNAL_SERVICE_TOKENS`：服务间密钥（可多个，逗号分隔）
- `ENCRYPTION_KEY`：Fernet 密钥，生成方式：

```bash
poetry run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4. 执行数据库迁移

```bash
poetry run alembic upgrade head
```

### 5. 启动服务

```bash
poetry run start
# 或
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- 存活检查：`GET http://127.0.0.1:8000/health`
- 就绪检查：`GET http://127.0.0.1:8000/ready`（探测 MySQL / Redis / Chroma）
- API 文档：`http://127.0.0.1:8000/docs`（非生产环境）
- 生产部署步骤见 [`DEPLOY.md`](./DEPLOY.md)

## 请求头规范

所有 `/api/v1/internal/**` 接口必须携带：

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-User-Id` | 是 | Java 侧已鉴权用户 ID |
| `X-Service-Token` | 是 | 服务间密钥 |
| `X-Role` | 否 | `user` / `admin`，默认 `user` |
| `Content-Type` | 是 | `application/json`（上传接口除外） |

## 接口一览

### 模型管理

- `GET /api/v1/internal/models` — 可用模型列表
- `GET /api/v1/internal/models/{id}` — 模型详情
- `POST /api/v1/internal/models` — 新增模型
- `PUT /api/v1/internal/models/{id}` — 修改模型
- `DELETE /api/v1/internal/models/{id}` — 删除模型（仍被会话/知识库引用时拒绝）

### 会话与聊天

- `POST /api/v1/internal/chat/invoke` — 非流式问答
- `POST /api/v1/internal/chat/stream` — 流式问答（SSE）
- `GET /api/v1/internal/conversations` — 会话列表
- `GET /api/v1/internal/conversations/{id}` — 会话详情
- `POST /api/v1/internal/conversations` — 新建会话
- `PUT /api/v1/internal/conversations/{id}` — 修改标题
- `DELETE /api/v1/internal/conversations/{id}` — 删除会话
- `POST /api/v1/internal/conversations/{id}/summary` — 主动总结

### 提示词模板

- `GET/POST /api/v1/internal/prompts`
- `GET/PUT/DELETE /api/v1/internal/prompts/{id}`

### 知识库

- `GET/POST /api/v1/internal/knowledge-bases`
- `GET/PUT/DELETE /api/v1/internal/knowledge-bases/{id}`
- `GET/POST /api/v1/internal/knowledge-bases/{id}/documents`
- `POST /api/v1/internal/knowledge-bases/{id}/documents/upload` — 多文件上传（`multipart/form-data`，字段名 `files`）
- `DELETE /api/v1/internal/knowledge-bases/{id}/documents/{doc_id}`
- `POST /api/v1/internal/knowledge-bases/{id}/search` — 试检索（含距离门槛与邻块扩展）
- `POST /api/v1/internal/knowledge-bases/{id}/eval` — 黄金集语义检索评测（命中率 / MRR）
- 对话请求可传 `knowledge_base_id` / `rag_top_k` 开启 RAG
- 文件入库走 **Redis 任务队列**（`KB_JOB_WORKERS`），启动时回收卡住任务
- RAG 精度相关配置：`KB_RAG_MAX_DISTANCE`（`<=0` 关闭门槛）、`KB_NEIGHBOR_WINDOW`、`KB_RETRIEVE_CANDIDATE_MULTIPLIER`
- 黄金集示例：`data/kb_eval_examples.json`；运维台知识库页提供「评测」入口

### MCP（外部工具）

- `GET/POST /api/v1/internal/mcp-servers`
- `GET/PUT/DELETE /api/v1/internal/mcp-servers/{id}`
- `POST /api/v1/internal/mcp-servers/{id}/test` — 测试连接
- `POST /api/v1/internal/mcp-servers/{id}/sync` — 同步工具列表到缓存
- 支持传输：`stdio` / `sse` / `http`；**仅管理员可维护**
- 启用且已同步的工具会 **全局** 注入对话（SSE 事件：`tool_call` / `tool_result`）
- 可选请求字段：`mcp_server_ids` / `tool_names` 过滤（供后续工作流）

**上传说明：**

- 格式：`.pdf` / `.docx` / `.xlsx`（不含扫描件 OCR、不含 `.doc`）
- 限制：单次最多 10 个文件，单文件默认 ≤ 100MB（见 `UPLOAD_MAX_FILE_SIZE_MB`）
- 流程：落盘 `UPLOAD_ROOT` → 解析文本 → 切分 → Embedding → Chroma → 可 RAG
- 建议知识库配置独立 Embedding 模型（`type=embedding`）；更换 Embedding 会清空旧向量并重建

### 系统信息

- `GET /api/v1/internal/system/info`

## 调用示例

### 新增模型（OpenAI 兼容，如 DeepSeek）

```bash
curl -X POST http://127.0.0.1:8000/api/v1/internal/models \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: your_service_secret_key1" \
  -H "X-User-Id: 10001" \
  -d "{
    \"name\": \"DeepSeek Chat\",
    \"type\": \"text\",
    \"provider\": \"openai_compatible\",
    \"base_url\": \"https://api.deepseek.com/v1\",
    \"api_key\": \"sk-xxx\",
    \"model_id\": \"deepseek-chat\",
    \"max_context\": 32768,
    \"scope\": \"private\"
  }"
```

### 非流式对话

```bash
curl -X POST http://127.0.0.1:8000/api/v1/internal/chat/invoke \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: your_service_secret_key1" \
  -H "X-User-Id: 10001" \
  -d "{
    \"model_id\": 1,
    \"message\": \"你好，请介绍一下自己\"
  }"
```

### 流式对话（SSE）

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/internal/chat/stream \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: your_service_secret_key1" \
  -H "X-User-Id: 10001" \
  -d "{
    \"model_id\": 1,
    \"conversation_id\": 1,
    \"message\": \"继续上一个话题\"
  }"
```

### Ollama 本地模型

创建模型时设置：

```json
{
  "name": "本地 Llama",
  "type": "text",
  "provider": "ollama",
  "base_url": "http://127.0.0.1:11434",
  "api_key": "",
  "model_id": "llama3.2",
  "max_context": 8192,
  "scope": "private"
}
```

## 目录结构

```
app/
├── api/v1/internal/     # 内部 HTTP 接口
├── core/                # 配置、日志、异常、上下文、安全、启动校验
├── schemas/             # Pydantic 请求/响应
├── services/            # 业务层 + LLM / 知识库队列
├── db/                  # MySQL / Redis / Vector
├── middleware/          # 内部鉴权
├── agent/               # LangGraph / MCP 扩展预留（未实现）
└── main.py
alembic/                 # 数据库迁移
tests/                   # 最小自动化测试
DEPLOY.md                # 服务器部署说明
```

## 扩展预留（部分已落地）

- **MCP Client**：已实现外部 MCP Server 接入与对话工具调用（见上文「MCP」）
- `app/agent/`：AgentRegistry + MCP 会话挂载
- 工作流编排 / 自建 MCP Server：后续演进
- `app/db/vector/`：向量库抽象（已实现 Chroma；可替换实现）

已落地的知识库入口在 `app/services/knowledge_service.py` / `vector_service.py`。

## 注意事项

1. 生产环境请将 `ENV=production`，此时关闭 Swagger、拒绝不安全占位密钥，且不返回异常堆栈
2. API Key 在数据库中加密存储，日志自动脱敏
3. 公共模型/模板仅 `X-Role: admin` 可管理
4. 会话超过轮数阈值返回 `is_warn_round=true`；达阈值或 Token 占用过高会自动总结
5. 运维台为独立前端仓库 `youqiAgent-web`，通过本地连接配置对接本服务
