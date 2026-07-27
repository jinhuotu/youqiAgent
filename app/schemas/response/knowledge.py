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
    hits: list[KnowledgeSearchHit]
