from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_POSTGRES_",
        extra="ignore",
    )

    # PostgreSQL 连接 DSN
    dsn: str = "postgresql+psycopg://cm:cm@localhost:5432/chainmonitor"
    # 连接池大小
    pool_size: int = 10
    # 连接池最大溢出连接数
    max_overflow: int = 20
    # 获取连接的超时时间（秒）
    pool_timeout_seconds: int = 30
    # 连接回收时间（秒），超过此时间未使用的连接将被回收
    pool_recycle_seconds: int = 1800
    # SQL 语句执行超时（毫秒）
    statement_timeout_ms: int = 15_000
    # 批量写入每批大小
    write_batch_size: int = 500


@lru_cache
def get_postgres_settings() -> PostgresSettings:
    return PostgresSettings()
