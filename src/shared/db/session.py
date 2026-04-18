from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from src.shared.config import get_settings


def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.postgres_dsn, future=True, pool_pre_ping=True)
