from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_APP_",
        extra="ignore",
    )

    # 服务名称（用于日志/监控标识）
    name: str = "chainmonitor"
    # 运行环境：dev / staging / prod
    env: str = "dev"
    # 监听地址
    host: str = "0.0.0.0"
    # 监听端口
    port: int = 8000
    # 日志级别
    log_level: str = "INFO"
    # API Key（为空则不校验）
    api_key: str = ""
    # 是否要求所有请求携带 API Key
    require_api_key: bool = False
    # 全局限流：每分钟允许请求数
    rate_limit_per_minute: int = 600
    # 令牌桶突发容量
    rate_limit_burst: int = 120
    # 令牌桶最大追踪 Key 数
    rate_limit_bucket_max_keys: int = 100_000
    # Key 在桶中的存活时间（秒）
    rate_limit_bucket_key_ttl_seconds: int = 600

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in {"prod", "production"}


@lru_cache
def get_app_settings() -> AppSettings:
    return AppSettings()
