"""MySQL 数据库会话管理。

提供引擎创建、Session 工厂与 FastAPI 依赖注入用的 get_db。
"""

from collections.abc import Generator
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logger import get_logger

log = get_logger("db.mysql")

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """获取全局 SQLAlchemy Engine（懒加载单例）。"""
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.mysql_dsn,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=10,
            max_overflow=20,
            echo=False,
            connect_args={"charset": "utf8mb4"},
        )
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
        log.info(f"MySQL 引擎已创建: {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}")
    return _engine


def get_session_factory() -> sessionmaker:
    """获取 Session 工厂。"""
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：获取数据库会话，请求结束自动关闭。

    Yields:
        SQLAlchemy Session
    """
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_mysql_connection() -> bool:
    """探测 MySQL 连接是否正常。

    Returns:
        True 表示连接成功，False 表示失败
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        log.warning(f"MySQL 连接检测失败: {e}")
        return False
