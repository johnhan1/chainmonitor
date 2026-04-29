from __future__ import annotations

from functools import lru_cache

from pydantic.fields import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScannerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_SCANNER_", extra="ignore")

    enabled: bool = False
    chains_raw: str = "sol,bsc,base,eth"
    surge_threshold: int = 10
    spike_ratio: float = 2.0
    interval_1m_seconds: int = 60
    interval_1h_seconds: int = 300
    trending_limit: int = 50
    min_liquidity: float = 50_000.0
    max_rug_risk: float = 0.8
    max_bundler_rat_ratio: float = 0.7
    score_high_threshold: int = 75
    score_medium_threshold: int = 65
    score_low_threshold: int = 55
    cooldown_high_seconds: int = 900
    cooldown_medium_seconds: int = 1800
    cooldown_observe_seconds: int = 300
    metrics_port: int = 9101
    rate_limit_per_second: float = 2.0
    rate_limit_capacity: int = 5
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    circuit_half_open_max_calls: int = 2
    retry_attempts: int = 3
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 30.0
    trending_timeout_seconds: float = 30.0
    security_timeout_seconds: float = 15.0
    security_max_concurrency: int = 5
    gmgn_api_key: str = Field("", validation_alias="CM_GMGN_API_KEY")
    gmgn_cli_path: str = Field("gmgn-cli", validation_alias="CM_GMGN_CLI_PATH")
    telegram_bot_token: str = Field("", validation_alias="CM_TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field("", validation_alias="CM_TELEGRAM_CHAT_ID")

    @property
    def chains(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.chains_raw.split(",") if item.strip())


@lru_cache
def get_scanner_settings() -> ScannerSettings:
    return ScannerSettings()
