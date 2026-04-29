from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class InfraSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    clickhouse_http_url: str = "http://localhost:8123"
    minio_endpoint: str = "http://localhost:9002"


@lru_cache
def get_infra_settings() -> InfraSettings:
    return InfraSettings()
