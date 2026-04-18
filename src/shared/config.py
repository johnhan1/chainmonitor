import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class Settings(BaseSettings):
    app_name: str = "chainmonitor"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "INFO"
    postgres_dsn: str = "postgresql+psycopg://cm:cm@localhost:5432/chainmonitor"
    redis_url: str = "redis://localhost:6379/0"
    clickhouse_http_url: str = "http://localhost:8123"
    minio_endpoint: str = "http://localhost:9002"
    bsc_chain_id: str = "bsc"
    bsc_default_symbols: str = "BNB,CAKE,XVS,BUSD,USDT"
    candidate_tier_a_threshold: float = 85.0
    candidate_tier_b_threshold: float = 70.0
    candidate_tier_c_threshold: float = 55.0
    bsc_strategy_version: str = "bsc-mvp-v1"
    bsc_scheduler_enabled: bool = False
    bsc_scheduler_interval_seconds: int = 60
    bsc_scheduler_initial_delay_seconds: int = 5

    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

