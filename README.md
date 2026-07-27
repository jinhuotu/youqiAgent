# Agent AI Service

内部 AI 能力下沉服务：基于 FastAPI + LangChain 1.0+ + LangGraph，面向 Java 业务后端提供标准化 HTTP 接口。

- **不对外暴露**、无独立用户鉴权体系
- Java 后端携带 `X-Service-Token` + `X-User-Id` 内网调用
- 按 `user_id` 行级数据隔离

## 技术栈

| 组件 | 版本要求 |
|------|----------|
| Python | ≥ 3.11 |
| FastAPI | 最新稳定版 |
| LangChain / LangGraph | ≥ 1.0 |
| SQLAlchemy | ≥ 2.0 |
| MySQL + Redis + ChromaDB | ChromaDB ≥ 1.0（Windows 预编译 wheel，无需本地编译） |
| Poetry | 依赖管理 |

## 快速开始

### 1. 安装 Poetry

```bash
pip install poetry
```

### 2. 安装依赖

```bash
cd youqiAgent
poetry install
```

### 3. 配置环境变量

```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

编辑 `.env`，至少配置：

- MySQL 连接信息，并预先创建数据库：`CREATE DATABASE agent_ai DEFAULT CHARSET utf8mb4;`
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

- 健康检查：`GET http://127.0.0.1:8000/health`
- API 文档：`http://127.0.0.1:8000/docs`（非生产环境）

## 请求头规范

所有 `/api/v1/internal/**` 接口必须携带：

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-User-Id` | 是 | Java 侧已鉴权用户 ID |
| `X-Service-Token` | 是 | 服务间密钥 |
| `X-Role` | 否 | `user` / `admin`，默认 `user` |
| `Content-Type` | 是 | `application/json` |

## 接口一览

### 模型管理

- `GET /api/v1/internal/models` — 可用模型列表
- `GET /api/v1/internal/models/{id}` — 模型详情
- `POST /api/v1/internal/models` — 新增模型
- `PUT /api/v1/internal/models/{id}` — 修改模型
- `DELETE /api/v1/internal/models/{id}` — 删除模型

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

### 知识库（最小闭环）

- `GET/POST /api/v1/internal/knowledge-bases`
- `GET/PUT/DELETE /api/v1/internal/knowledge-bases/{id}`
- `GET/POST /api/v1/internal/knowledge-bases/{id}/documents`
- `POST /api/v1/internal/knowledge-bases/{id}/documents/upload` — 多文件上传（`multipart/form-data`，字段名 `files`）
- `DELETE /api/v1/internal/knowledge-bases/{id}/documents/{doc_id}`
- `POST /api/v1/internal/knowledge-bases/{id}/search`
- 对话请求可传 `knowledge_base_id` / `rag_top_k` 开启 RAG

**上传说明：**

- 格式：`.pdf` / `.docx` / `.xlsx`（不含扫描件 OCR、不含 `.doc`）
- 限制：单次最多 10 个文件，单文件默认 ≤ 100MB（见 `UPLOAD_MAX_FILE_SIZE_MB`）
- 流程：落盘 `UPLOAD_ROOT` → 解析文本 → 切分 → Embedding → Chroma → 可 RAG
- 建议知识库配置独立 Embedding 模型，便于后续切换向量库

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
├── core/                # 配置、日志、异常、上下文、安全
├── schemas/             # Pydantic 请求/响应
├── services/            # 业务层 + LLM 抽象
├── db/                  # MySQL / Redis / Vector
├── middleware/          # 内部鉴权
├── agent/               # LangGraph / MCP 扩展预留
└── main.py
alembic/                 # 数据库迁移
```

## 扩展预留

- `app/agent/`：LangGraph 智能体与工作流
- `app/agent/mcp_placeholder.py`：MCP 工具挂载点
- `app/db/vector/`：向量库抽象，当前 Chroma，可替换实现
- `app/services/vector_service.py`：知识库 RAG 业务入口

## 注意事项

1. 生产环境请将 `ENV=production`，此时关闭 Swagger 且不返回异常堆栈
2. API Key 在数据库中加密存储，日志自动脱敏
3. 公共模型/模板仅 `X-Role: admin` 可管理
4. 会话超过 30 轮返回 `is_warn_round=true`；达到 25 轮或 Token 占用 80% 自动总结
