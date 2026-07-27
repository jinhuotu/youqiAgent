"""知识库与文档 ORM。"""

import enum
from typing import Optional

from sqlalchemy import Enum, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql.models.base import Base, TimestampMixin, UserScopedMixin
from app.db.mysql.models.model_config import _enum_values


class KnowledgeScope(str, enum.Enum):
    """知识库作用域。"""

    PUBLIC = "public"
    PRIVATE = "private"


class DocumentSourceType(str, enum.Enum):
    """文档来源。"""

    TEXT = "text"
    FILE = "file"


class DocumentParseStatus(str, enum.Enum):
    """文档解析/入库状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class KnowledgeBase(Base, TimestampMixin, UserScopedMixin):
    """知识库主表。"""

    __tablename__ = "knowledge_bases"
    __table_args__ = {"comment": "知识库主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="知识库名称")
    description: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="描述",
    )
    scope: Mapped[KnowledgeScope] = mapped_column(
        Enum(KnowledgeScope, values_callable=_enum_values),
        nullable=False,
        default=KnowledgeScope.PRIVATE,
        index=True,
        comment="作用域 public/private",
    )
    embedding_model_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Embedding 模型配置ID，空则使用 Chroma 默认向量",
    )
    status: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        comment="1启用 0禁用",
    )


class KnowledgeDocument(Base, TimestampMixin, UserScopedMixin):
    """知识库文档表（原文 + 元数据；向量分块存 Chroma）。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = {"comment": "知识库文档表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="所属知识库ID",
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="文档标题")
    # MySQL TEXT 仅 ~64KB，整本 PDF 原文会超限；用 MEDIUMTEXT（16MB）
    content: Mapped[str] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql"),
        nullable=False,
        comment="文档原文",
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="切分块数量",
    )
    source_type: Mapped[DocumentSourceType] = mapped_column(
        Enum(DocumentSourceType, values_callable=_enum_values),
        nullable=False,
        default=DocumentSourceType.TEXT,
        comment="来源 text/file",
    )
    file_name: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True,
        comment="原始文件名",
    )
    file_path: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="相对 UPLOAD_ROOT 的存储路径",
    )
    file_ext: Mapped[Optional[str]] = mapped_column(
        String(16),
        nullable=True,
        comment="文件扩展名",
    )
    file_size: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="文件字节数",
    )
    parse_status: Mapped[DocumentParseStatus] = mapped_column(
        Enum(DocumentParseStatus, values_callable=_enum_values),
        nullable=False,
        default=DocumentParseStatus.READY,
        comment="解析状态",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="失败原因",
    )
    status: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        comment="1正常 0删除标记",
    )
