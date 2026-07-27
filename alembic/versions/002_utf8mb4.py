"""将库表字符集升级为 utf8mb4，以支持 emoji 等 4 字节字符。

Revision ID: 002_utf8mb4
Revises: 001_initial
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002_utf8mb4"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "models",
    "conversations",
    "messages",
    "prompt_templates",
    "system_config",
)


def upgrade() -> None:
    """库 / 表统一改为 utf8mb4，避免消息 content 写入 emoji 失败。"""
    bind = op.get_bind()
    db_name = bind.exec_driver_sql("SELECT DATABASE()").scalar()
    if db_name:
        op.execute(
            f"ALTER DATABASE `{db_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    for table in TABLES:
        op.execute(
            f"ALTER TABLE `{table}` "
            "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )


def downgrade() -> None:
    """回退为 utf8（不推荐；emoji 将再次写入失败）。"""
    for table in TABLES:
        op.execute(
            f"ALTER TABLE `{table}` "
            "CONVERT TO CHARACTER SET utf8 COLLATE utf8_general_ci"
        )
