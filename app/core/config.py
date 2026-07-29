"""应用配置加载模块。

通过 pydantic-settings 从环境变量 / .env 文件读取配置，
禁止在业务代码中硬编码任何敏感信息或环境相关参数。
"""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局应用配置，所有字段均可通过 .env 注入。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 服务配置 ----------
    server_host: str = Field(default="0.0.0.0", description="服务监听地址")
    server_port: int = Field(default=8000, description="服务监听端口")
    log_level: str = Field(default="INFO", description="日志级别")
    env: str = Field(default="development", description="运行环境")
    app_version: str = Field(default="1.0.0", description="系统版本号")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="CORS 允许来源，多个用英文逗号分隔",
    )

    # ---------- MySQL ----------
    mysql_host: str = Field(default="127.0.0.1")
    mysql_port: int = Field(default=3306)
    mysql_user: str = Field(default="root")
    mysql_password: str = Field(default="")
    mysql_database: str = Field(default="agent_ai")

    # ---------- Redis ----------
    redis_host: str = Field(default="127.0.0.1")
    redis_port: int = Field(default=6379)
    redis_password: str = Field(default="")
    redis_db: int = Field(default=0)

    # ---------- Chroma ----------
    chroma_persist_path: str = Field(default="./data/chroma")

    # ---------- 服务间鉴权 ----------
    internal_service_tokens: str = Field(
        default="",
        description="服务密钥，多个用英文逗号分隔",
    )
    enable_admin_role: bool = Field(default=True, description="是否启用管理员角色")

    # ---------- 加密 ----------
    encryption_key: str = Field(
        default="",
        description="Fernet 加密密钥，用于 API Key 等敏感字段",
    )

    # ---------- 会话业务参数 ----------
    round_warn_threshold: int = Field(default=30, description="轮数提醒阈值")
    summary_trigger_rounds: int = Field(default=25, description="自动总结触发轮数")
    summary_keep_rounds: int = Field(default=5, description="总结后保留最近轮数")
    summary_token_ratio: float = Field(default=0.8, description="Token 占用触发总结比例")

    # ---------- 知识库 ----------
    kb_chunk_size: int = Field(default=800, description="知识库文本切分长度")
    kb_chunk_overlap: int = Field(default=100, description="知识库切分重叠长度")
    kb_chunk_progress_every: int = Field(
        default=10,
        description="切分进度写库间隔（每 N 块提交一次，降低大文件 DB 压力）",
    )
    kb_default_top_k: int = Field(default=5, description="RAG 默认召回条数")
    kb_source_preview_chars: int = Field(
        default=240,
        description="对话引用展示时单条片段预览字数",
    )
    # Chroma distance 越小越相似；<=0 表示不过滤。默认 1.5 适合常见 L2 向量，可按试检索调参
    kb_rag_max_distance: float = Field(
        default=1.5,
        description="RAG 最大允许 distance；<=0 关闭距离门槛",
    )
    kb_neighbor_window: int = Field(
        default=1,
        ge=0,
        le=3,
        description="命中块左右扩展邻块数；0 表示不扩展",
    )
    kb_retrieve_candidate_multiplier: int = Field(
        default=3,
        ge=1,
        le=5,
        description="距离过滤前多召回倍数，保证过滤后仍接近 top_k",
    )
    # 阿里云 text-embedding-v3/v4 兼容接口单批上限 10；OpenAI 可更大
    kb_embed_batch_size: int = Field(default=10, description="Embedding 单批条数")
    kb_job_workers: int = Field(default=1, description="知识库文档处理 worker 数")
    kb_job_stuck_minutes: int = Field(
        default=30,
        description="processing 超时分钟数，启动时重新入队",
    )
    upload_root: str = Field(default="./data/uploads", description="知识库上传文件根目录")
    upload_max_file_size_mb: int = Field(default=100, description="单文件最大 MB")
    upload_max_files_per_request: int = Field(default=10, description="单次最多上传文件数")

    # ---------- MCP ----------
    mcp_workdir: str = Field(
        default="./data/mcp",
        description="stdio MCP 子进程默认工作目录",
    )
    mcp_command_allowlist: str = Field(
        default="npx,uvx,node,python,python3",
        description="stdio 允许的命令名（basename），逗号分隔",
    )
    mcp_tool_timeout_seconds: int = Field(default=60, description="单次 MCP 工具调用超时秒")
    mcp_tool_max_rounds: int = Field(default=8, description="对话中最多工具调用轮次")
    mcp_tool_result_max_chars: int = Field(
        default=8000,
        description="工具结果写入模型上下文的最大字符数",
    )

    @property
    def mcp_command_allowlist_set(self) -> set[str]:
        """解析 stdio 命令白名单。"""
        return {
            x.strip().lower()
            for x in self.mcp_command_allowlist.split(",")
            if x.strip()
        }

    @property
    def service_token_list(self) -> List[str]:
        """解析多密钥配置为列表。"""
        if not self.internal_service_tokens:
            return []
        return [t.strip() for t in self.internal_service_tokens.split(",") if t.strip()]

    @property
    def cors_origin_list(self) -> List[str]:
        """解析 CORS 允许来源为列表。"""
        if not self.cors_origins:
            return []
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def mysql_dsn(self) -> str:
        """构建 SQLAlchemy MySQL 连接串（PyMySQL 驱动）。"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        """构建 Redis 连接 URL。"""
        if self.redis_password:
            return (
                f"redis://:{self.redis_password}@{self.redis_host}"
                f":{self.redis_port}/{self.redis_db}"
            )
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_production(self) -> bool:
        """判断是否为生产环境。"""
        return self.env.lower() in ("production", "prod")

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, v: str) -> str:
        """统一日志级别为大写。"""
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（进程内缓存）。"""
    return Settings()
