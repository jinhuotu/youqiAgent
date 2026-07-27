"""knowledge_documents.content 扩为 MEDIUMTEXT，支持整本 PDF 原文。

Revision ID: 005_kb_content_mediumtext
Revises: 004_kb_file_upload
Create Date: 2026-07-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "005_kb_content_mediumtext"
down_revision: Union[str, None] = "004_kb_file_upload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "knowledge_documents",
        "content",
        existing_type=sa.Text(),
        type_=mysql.MEDIUMTEXT(),
        existing_nullable=False,
        comment="文档原文",
    )


def downgrade() -> None:
    op.alter_column(
        "knowledge_documents",
        "content",
        existing_type=mysql.MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=False,
        comment="文档原文",
    )
