"""models.type 增加 embedding，用于区分对话模型与向量模型。

Revision ID: 006_model_type_embedding
Revises: 005_kb_content_mediumtext
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006_model_type_embedding"
down_revision: Union[str, None] = "005_kb_content_mediumtext"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE models MODIFY COLUMN type "
        "ENUM('text','image','audio','video','multimodal','embedding') "
        "NOT NULL COMMENT '模态类型'"
    )
    # 已有向量模型配置按名称/标识自动归类，便于对话下拉立即排除
    op.execute(
        "UPDATE models SET type='embedding' "
        "WHERE LOWER(model_id) LIKE '%embedding%' "
        "OR LOWER(name) LIKE '%embedding%' "
        "OR LOWER(model_id) LIKE '%bge-%' "
        "OR LOWER(model_id) LIKE '%nomic-embed%'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE models SET type='text' WHERE type='embedding'"
    )
    op.execute(
        "ALTER TABLE models MODIFY COLUMN type "
        "ENUM('text','image','audio','video','multimodal') "
        "NOT NULL COMMENT '模态类型'"
    )
