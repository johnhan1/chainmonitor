from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_APP_", extra="ignore")

    name: str = "chainmonitor"
    env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    api_key: str = ""
    require_api_key: bool = False
    rate_limit_per_minute: int = 600
    rate_limit_burst: int = 120
    rate_limit_bucket_max_keys: int = 100_000
    rate_limit_bucket_key_ttl_seconds: int = 600

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in {"prod", "production"}


@lru_cache
def get_app_settings() -> AppSettings:
    return AppSettings()
