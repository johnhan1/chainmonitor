from __future__ import annotations

from functools import lru_cache

from pydantic.fields import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_PIPELINE_", extra="ignore")

    run_timeout_seconds: float = 30.0
    fetch_timeout_seconds: float = 20.0
    feature_timeout_seconds: float = 10.0
    score_timeout_seconds: float = 10.0
    persist_timeout_seconds: float = 20.0
    candidate_query_cache_ttl_seconds: float = 3.0
    replay_require_api_key: bool = True
    replay_rate_limit_per_minute: int = 6
    replay_rate_limit_burst: int = 2
    replay_max_in_flight_per_chain: int = 1
    replay_max_lookback_minutes: int = 1_440
    replay_max_future_skew_seconds: int = 60
    replay_chain_allowlist: str = ""
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 60
    scheduler_initial_delay_seconds: int = 5
    scheduler_chains: str = "bsc,base,eth,sol"
    scheduler_startup_jitter_seconds: int = 7
    scheduler_catchup_windows: int = 3
    min_liquidity_usd: float = Field(150_000.0, validation_alias="CM_GATE_MIN_LIQUIDITY_USD")
    min_volume_5m_usd: float = Field(12_000.0, validation_alias="CM_GATE_MIN_VOLUME_5M_USD")
    min_tx_1m: int = Field(15, validation_alias="CM_GATE_MIN_TX_1M")
    tier_a_threshold: float = Field(85.0, validation_alias="CM_CANDIDATE_TIER_A_THRESHOLD")
    tier_b_threshold: float = Field(70.0, validation_alias="CM_CANDIDATE_TIER_B_THRESHOLD")
    tier_c_threshold: float = Field(55.0, validation_alias="CM_CANDIDATE_TIER_C_THRESHOLD")

    @property
    def replay_allowed_chains(self):
        from src.shared.config.chain import get_chain_settings

        chain_settings = get_chain_settings()
        raw = self.replay_chain_allowlist.strip()
        if not raw:
            return chain_settings.supported_chains
        requested = [item.strip() for item in raw.split(",") if item.strip()]
        supported = set(chain_settings.supported_chains)
        deduped = dict.fromkeys(requested)
        return tuple(chain_id for chain_id in deduped if chain_id in supported)

    @property
    def enabled_scheduler_chains(self):
        from src.shared.config.chain import get_chain_settings

        chain_settings = get_chain_settings()
        requested = [item.strip() for item in self.scheduler_chains.split(",") if item.strip()]
        if not requested:
            return ()
        supported = set(chain_settings.supported_chains)
        deduped = dict.fromkeys(requested)
        return tuple(chain_id for chain_id in deduped if chain_id in supported)


@lru_cache
def get_pipeline_settings() -> PipelineSettings:
    return PipelineSettings()
