"""知识库相关请求 Schema。"""

from typing import Optional

from pydantic import BaseModel, Field

from app.db.mysql.models.knowledge import KnowledgeScope


class KnowledgeBaseCreateRequest(BaseModel):
    """创建知识库。"""

    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    scope: KnowledgeScope = Field(default=KnowledgeScope.PRIVATE)
    embedding_model_id: Optional[int] = Field(
        default=None,
        description="Embedding 模型配置ID，空则用 Chroma 默认向量",
    )
    status: int = Field(default=1, ge=0, le=1)


class KnowledgeBaseUpdateRequest(BaseModel):
    """更新知识库。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    scope: Optional[KnowledgeScope] = None
    embedding_model_id: Optional[int] = None
    status: Optional[int] = Field(default=None, ge=0, le=1)


class KnowledgeDocumentCreateRequest(BaseModel):
    """录入文本文档。"""

    title: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1, description="文档原文，后端自动切分入库")


class KnowledgeSearchRequest(BaseModel):
    """知识库试检索。"""

    query: str = Field(..., min_length=1, description="检索问题")
    top_k: int = Field(default=5, ge=1, le=20, description="召回条数")
