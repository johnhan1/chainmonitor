from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class InfraSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_",
        extra="ignore",
    )

    # Redis 连接 URL
    redis_url: str = "redis://localhost:6379/0"
    # ClickHouse HTTP 接口地址（尚未接入）
    clickhouse_http_url: str = "http://localhost:8123"
    # MinIO S3 兼容存储端点（尚未接入）
    minio_endpoint: str = "http://localhost:9002"


@lru_cache
def get_infra_settings() -> InfraSettings:
    return InfraSettings()
