"""初始化全部业务表结构。

Revision ID: 001_initial
Revises:
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 models / conversations / messages / prompt_templates / system_config。"""

    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, comment="模型展示名称"),
        sa.Column(
            "type",
            sa.Enum("text", "image", "audio", "video", "multimodal", name="modeltype"),
            nullable=False,
            comment="模态类型",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            comment="提供商标识",
        ),
        sa.Column("base_url", sa.String(length=512), nullable=False, comment="接口请求地址"),
        sa.Column("api_key", sa.Text(), nullable=False, comment="API密钥（加密存储）"),
        sa.Column("model_id", sa.String(length=128), nullable=False, comment="模型标识符"),
        sa.Column("max_context", sa.Integer(), nullable=False, comment="最大上下文长度"),
        sa.Column(
            "scope",
            sa.Enum("public", "private", name="modelscope"),
            nullable=False,
            comment="作用域",
        ),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="所属用户ID"),
        sa.Column("status", sa.SmallInteger(), nullable=False, comment="1启用 0禁用"),
        sa.Column(
            "create_time",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="大模型配置表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_models_user_id", "models", ["user_id"])
    op.create_index("ix_models_scope", "models", ["scope"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False, comment="会话标题"),
        sa.Column("model_id", sa.Integer(), nullable=False, comment="绑定模型ID"),
        sa.Column("round_count", sa.Integer(), nullable=False, comment="消息轮数"),
        sa.Column("summary", sa.Text(), nullable=True, comment="历史总结"),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="所属用户ID"),
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
        comment="会话主表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_model_id", "conversations", ["model_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False, comment="所属会话ID"),
        sa.Column(
            "role",
            sa.Enum("system", "user", "assistant", name="messagerole"),
            nullable=False,
            comment="消息角色",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="消息内容"),
        sa.Column("token_count", sa.Integer(), nullable=False, comment="估算token数"),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="所属用户ID"),
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
        comment="对话消息明细表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_messages_user_id", "messages", ["user_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, comment="模板名称"),
        sa.Column("content", sa.Text(), nullable=False, comment="模板内容"),
        sa.Column(
            "model_type",
            sa.Enum(
                "text",
                "image",
                "audio",
                "video",
                "multimodal",
                name="modeltype",
                create_type=False,
            ),
            nullable=True,
            comment="适用模型类型",
        ),
        sa.Column(
            "scope",
            sa.Enum("public", "private", name="templatescope"),
            nullable=False,
            comment="作用域",
        ),
        sa.Column("description", sa.String(length=512), nullable=True, comment="描述"),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="所属用户ID"),
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
        comment="提示词模板表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_prompt_templates_user_id", "prompt_templates", ["user_id"])
    op.create_index("ix_prompt_templates_scope", "prompt_templates", ["scope"])

    op.create_table(
        "system_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="系统级固定为0"),
        sa.Column("config_key", sa.String(length=128), nullable=False, comment="配置键"),
        sa.Column("config_value", sa.Text(), nullable=False, comment="配置值"),
        sa.Column("description", sa.String(length=256), nullable=False, comment="说明"),
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
        sa.UniqueConstraint("config_key"),
        comment="全局系统配置表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_system_config_user_id", "system_config", ["user_id"])


def downgrade() -> None:
    """回滚全部表。"""
    op.drop_table("system_config")
    op.drop_table("prompt_templates")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("models")
    # 清理枚举类型（MySQL 上 Enum 随表删除，此处兼容）
    sa.Enum(name="messagerole").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="templatescope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="modelscope").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="modeltype").drop(op.get_bind(), checkfirst=True)
