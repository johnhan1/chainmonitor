from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from src.shared.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.postgres_dsn,
        future=True,
        pool_pre_ping=True,
        pool_size=max(1, settings.postgres_pool_size),
        max_overflow=max(0, settings.postgres_max_overflow),
        pool_timeout=max(1, settings.postgres_pool_timeout_seconds),
        pool_recycle=max(60, settings.postgres_pool_recycle_seconds),
    )


def close_engine() -> None:
    if get_engine.cache_info().currsize == 0:
        return
    engine = get_engine()
    engine.dispose()
    get_engine.cache_clear()
