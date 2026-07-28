"""补齐核心表外键，提升引用完整性。

Revision ID: 007_add_foreign_keys
Revises: 006_model_type_embedding
Create Date: 2026-07-28

说明：
- 迁移前先清理孤儿数据，避免 ADD CONSTRAINT 失败
- conversations.model_id -> models.id（RESTRICT）
- messages.conversation_id -> conversations.id（CASCADE）
- knowledge_documents.knowledge_base_id -> knowledge_bases.id（CASCADE）
- knowledge_bases.embedding_model_id -> models.id（SET NULL）
"""

from typing import Sequence, Union

from alembic import op

revision: str = "007_add_foreign_keys"
down_revision: Union[str, None] = "006_model_type_embedding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 清理孤儿消息 / 文档
    op.execute(
        """
        DELETE m FROM messages m
        LEFT JOIN conversations c ON m.conversation_id = c.id
        WHERE c.id IS NULL
        """
    )
    op.execute(
        """
        DELETE d FROM knowledge_documents d
        LEFT JOIN knowledge_bases k ON d.knowledge_base_id = k.id
        WHERE k.id IS NULL
        """
    )
    # 无效 Embedding 引用置空
    op.execute(
        """
        UPDATE knowledge_bases kb
        LEFT JOIN models m ON kb.embedding_model_id = m.id
        SET kb.embedding_model_id = NULL
        WHERE kb.embedding_model_id IS NOT NULL AND m.id IS NULL
        """
    )
    # 绑定了不存在模型的会话：先删消息再删会话（历史脏数据）
    op.execute(
        """
        DELETE m FROM messages m
        INNER JOIN conversations c ON m.conversation_id = c.id
        LEFT JOIN models mo ON c.model_id = mo.id
        WHERE mo.id IS NULL
        """
    )
    op.execute(
        """
        DELETE c FROM conversations c
        LEFT JOIN models m ON c.model_id = m.id
        WHERE m.id IS NULL
        """
    )

    op.create_foreign_key(
        "fk_conversations_model_id",
        "conversations",
        "models",
        ["model_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_messages_conversation_id",
        "messages",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_documents_kb_id",
        "knowledge_documents",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_bases_embedding_model_id",
        "knowledge_bases",
        "models",
        ["embedding_model_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_knowledge_bases_embedding_model_id",
        "knowledge_bases",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_documents_kb_id",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_messages_conversation_id",
        "messages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_conversations_model_id",
        "conversations",
        type_="foreignkey",
    )
