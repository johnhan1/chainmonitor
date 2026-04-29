from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_POSTGRES_", extra="ignore")

    dsn: str = "postgresql+psycopg://cm:cm@localhost:5432/chainmonitor"
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout_seconds: int = 30
    pool_recycle_seconds: int = 1800
    statement_timeout_ms: int = 15_000
    write_batch_size: int = 500


@lru_cache
def get_postgres_settings() -> PostgresSettings:
    return PostgresSettings()
