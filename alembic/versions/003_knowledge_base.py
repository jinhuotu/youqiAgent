"""知识库字符集 utf8mb4 + 业务表。

Revision ID: 003_knowledge_base
Revises: 002_utf8mb4
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_knowledge_base"
down_revision: Union[str, None] = "002_utf8mb4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, comment="知识库名称"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="描述"),
        sa.Column(
            "scope",
            sa.Enum("public", "private", name="knowledgescope"),
            nullable=False,
            comment="作用域",
        ),
        sa.Column(
            "embedding_model_id",
            sa.Integer(),
            nullable=True,
            comment="Embedding模型配置ID",
        ),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="所属用户ID"),
        sa.Column("status", sa.SmallInteger(), nullable=False, comment="1启用 0禁用"),
        sa.Column(
            "create_time",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="知识库主表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_knowledge_bases_user_id", "knowledge_bases", ["user_id"])
    op.create_index("ix_knowledge_bases_scope", "knowledge_bases", ["scope"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "knowledge_base_id",
            sa.Integer(),
            nullable=False,
            comment="所属知识库ID",
        ),
        sa.Column("title", sa.String(length=256), nullable=False, comment="文档标题"),
        sa.Column("content", sa.Text(), nullable=False, comment="文档原文"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, comment="切分块数量"),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="所属用户ID"),
        sa.Column("status", sa.SmallInteger(), nullable=False, comment="1正常 0删除"),
        sa.Column(
            "create_time",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="知识库文档表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_knowledge_documents_user_id",
        "knowledge_documents",
        ["user_id"],
    )
    op.create_index(
        "ix_knowledge_documents_knowledge_base_id",
        "knowledge_documents",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_bases")
    sa.Enum(name="knowledgescope").drop(op.get_bind(), checkfirst=True)
