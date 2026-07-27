"""Alembic 迁移环境配置。

从应用 Settings 读取 MySQL DSN，自动导入全部 ORM 模型以支持 autogenerate。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db.mysql.models import Base  # noqa: F401  导入以注册 metadata
from app.db.mysql.models import (  # noqa: F401
    Conversation,
    Message,
    ModelConfig,
    PromptTemplate,
    SystemConfig,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 用应用配置覆盖 sqlalchemy.url
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.mysql_dsn)


def run_migrations_offline() -> None:
    """离线模式迁移（仅生成 SQL，不连库）。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式迁移（连接数据库执行）。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
