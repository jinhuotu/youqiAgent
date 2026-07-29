"""知识库相关响应 Schema。"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.mysql.models.knowledge import (
    DocumentParseStatus,
    DocumentSourceType,
    KnowledgeScope,
)


class KnowledgeBaseResponse(BaseModel):
    """知识库响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    scope: KnowledgeScope
    embedding_model_id: Optional[int] = None
    user_id: str
    status: int
    document_count: int = Field(default=0, description="文档数量")
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


class KnowledgeDocumentResponse(BaseModel):
    """知识库文档响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    title: str
    content: str
    chunk_count: int
    source_type: DocumentSourceType = DocumentSourceType.TEXT
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_ext: Optional[str] = None
    file_size: Optional[int] = None
    parse_status: DocumentParseStatus = DocumentParseStatus.READY
    error_message: Optional[str] = None
    user_id: str
    status: int
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


class KnowledgeSearchHit(BaseModel):
    """检索命中片段。"""

    id: str
    content: str
    distance: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    """检索结果。"""

    query: str
    top_k: int
    max_distance: Optional[float] = Field(
        default=None,
        description="当前生效的距离上限；<=0 表示未启用",
    )
    neighbor_window: int = Field(default=0, description="邻块扩展窗口")
    hits: list[KnowledgeSearchHit]


class KnowledgeEvalCaseResult(BaseModel):
    """单条评测结果。"""

    query: str
    hit: bool
    hit_at: Optional[int] = None
    reason: str = ""
    top_ids: list[str] = Field(default_factory=list)
    top_distances: list[Optional[float]] = Field(default_factory=list)


class KnowledgeEvalResponse(BaseModel):
    """评测汇总。"""

    total: int
    hit_count: int
    hit_rate: float
    mrr: float
    top_k: int
    max_distance: float
    neighbor_window: int
    cases: list[KnowledgeEvalCaseResult]
