"""SQLAlchemy engine / session factory.

Connection spec is shared with stock-platform (feasibility §8.0):
URL.create("mysql+pymysql", ..., charset=utf8mb4) so special chars in the
password are URL-encoded automatically; pool_pre_ping survives idle RDS
disconnects; pool_size=3 because this app is a short-lived CLI process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def build_database_url(settings: Optional[Settings] = None) -> URL:
    settings = settings or get_settings()
    return URL.create(
        drivername="mysql+pymysql",
        username=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        query={"charset": "utf8mb4"},
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        build_database_url(),
        pool_pre_ping=True,
        pool_size=3,
        pool_recycle=1800,
        echo=False,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


def reset_engine_cache() -> None:
    """Test hook: drop cached engine after switching DB_NAME."""
    eng = get_engine.cache_info()  # noqa: F841 - ensure caches exist check
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    _ = eng
