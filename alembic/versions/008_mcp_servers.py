"""MCP Server 表。

Revision ID: 008_mcp_servers
Revises: 007_add_foreign_keys
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_mcp_servers"
down_revision: Union[str, None] = "007_add_foreign_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, comment="唯一标识名称"),
        sa.Column("description", sa.String(length=512), nullable=True, comment="描述"),
        sa.Column(
            "transport",
            sa.Enum("stdio", "sse", "http", name="mcptransport"),
            nullable=False,
            comment="传输协议",
        ),
        sa.Column("command", sa.String(length=256), nullable=True, comment="stdio 启动命令"),
        sa.Column("args", sa.JSON(), nullable=True, comment="stdio 参数数组"),
        sa.Column("url", sa.String(length=1024), nullable=True, comment="sse/http 地址"),
        sa.Column("env_cipher", sa.Text(), nullable=True, comment="环境变量 JSON（加密）"),
        sa.Column(
            "scope",
            sa.Enum("public", "private", name="mcpscope"),
            nullable=False,
            comment="作用域",
        ),
        sa.Column("user_id", sa.String(length=64), nullable=False, comment="所属用户ID"),
        sa.Column("status", sa.SmallInteger(), nullable=False, comment="1启用 0禁用"),
        sa.Column("tool_cache", sa.JSON(), nullable=True, comment="工具列表缓存"),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True, comment="最近同步时间"),
        sa.Column("last_error", sa.String(length=1024), nullable=True, comment="最近错误"),
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
        sa.UniqueConstraint("name"),
        comment="外部 MCP Server 配置表",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_mcp_servers_user_id", "mcp_servers", ["user_id"])
    op.create_index("ix_mcp_servers_scope", "mcp_servers", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_scope", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_user_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")
    sa.Enum(name="mcptransport").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="mcpscope").drop(op.get_bind(), checkfirst=True)
