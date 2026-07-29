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


class KnowledgeEvalCase(BaseModel):
    """黄金集单条用例。"""

    query: str = Field(..., min_length=1, description="测试问题")
    expect_contains: Optional[str] = Field(
        default=None,
        description="期望命中片段中包含的关键词/原文片段",
    )
    expect_doc_title: Optional[str] = Field(
        default=None,
        description="期望命中文档标题包含的关键字",
    )


class KnowledgeEvalRequest(BaseModel):
    """知识库语义检索评测。"""

    cases: list[KnowledgeEvalCase] = Field(..., min_length=1, max_length=100)
    top_k: int = Field(default=5, ge=1, le=20, description="每条用例召回条数")
