"""知识库文档增加文件上传相关字段。

Revision ID: 004_kb_file_upload
Revises: 003_knowledge_base
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_kb_file_upload"
down_revision: Union[str, None] = "003_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "source_type",
            sa.Enum("text", "file", name="documentsourcetype"),
            nullable=False,
            server_default="text",
            comment="来源 text/file",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("file_name", sa.String(length=256), nullable=True, comment="原始文件名"),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "file_path",
            sa.String(length=512),
            nullable=True,
            comment="相对 UPLOAD_ROOT 的存储路径",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("file_ext", sa.String(length=16), nullable=True, comment="文件扩展名"),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("file_size", sa.Integer(), nullable=True, comment="文件字节数"),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "parse_status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="documentparsestatus",
            ),
            nullable=False,
            server_default="ready",
            comment="解析状态",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "error_message",
            sa.String(length=512),
            nullable=True,
            comment="失败原因",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "error_message")
    op.drop_column("knowledge_documents", "parse_status")
    op.drop_column("knowledge_documents", "file_size")
    op.drop_column("knowledge_documents", "file_ext")
    op.drop_column("knowledge_documents", "file_path")
    op.drop_column("knowledge_documents", "file_name")
    op.drop_column("knowledge_documents", "source_type")
    sa.Enum(name="documentparsestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="documentsourcetype").drop(op.get_bind(), checkfirst=True)
