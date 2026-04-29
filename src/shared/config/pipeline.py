from __future__ import annotations

import os
from functools import lru_cache

from pydantic.fields import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_PIPELINE_",
        extra="ignore",
    )

    # 单次 Pipeline 运行总超时（秒）
    run_timeout_seconds: float = 30.0
    # 数据获取阶段超时（秒）
    fetch_timeout_seconds: float = 20.0
    # 特征计算阶段超时（秒）
    feature_timeout_seconds: float = 10.0
    # 评分阶段超时（秒）
    score_timeout_seconds: float = 10.0
    # 持久化阶段超时（秒）
    persist_timeout_seconds: float = 20.0
    # 候选池查询结果缓存 TTL（秒）
    candidate_query_cache_ttl_seconds: float = 3.0
    # Replay API 是否需要 API Key 认证
    replay_require_api_key: bool = True
    # Replay API 每分钟速率限制
    replay_rate_limit_per_minute: int = 6
    # Replay API 令牌桶突发容量
    replay_rate_limit_burst: int = 2
    # 每条链最大并行 Replay 数
    replay_max_in_flight_per_chain: int = 1
    # Replay 最大回看窗口（分钟）
    replay_max_lookback_minutes: int = 1_440
    # Replay 最大未来偏差（秒），允许轻微时钟漂移
    replay_max_future_skew_seconds: int = 60
    # 允许 Replay 的链白名单，空=全部链
    replay_chain_allowlist: str = ""
    # 是否启用定时调度器
    scheduler_enabled: bool = False
    # 调度器轮询间隔（秒）
    scheduler_interval_seconds: int = 60
    # 调度器首次执行前的延迟（秒）
    scheduler_initial_delay_seconds: int = 5
    # 调度器监控的链列表，逗号分隔
    scheduler_chains: str = "bsc,base,eth,sol"
    # 调度器启动时的随机抖动（秒），避免多节点同时执行
    scheduler_startup_jitter_seconds: int = 7
    # 调度器追赶窗口数，允许补跑最近 N 个窗口
    scheduler_catchup_windows: int = 3
    # 候选交易对最低流动性（USD）
    min_liquidity_usd: float = Field(150_000.0, validation_alias="CM_GATE_MIN_LIQUIDITY_USD")
    # 候选交易对最低 5 分钟成交量（USD）
    min_volume_5m_usd: float = Field(12_000.0, validation_alias="CM_GATE_MIN_VOLUME_5M_USD")
    # 候选交易对最低 1 分钟交易笔数
    min_tx_1m: int = Field(15, validation_alias="CM_GATE_MIN_TX_1M")
    # Tier A 阈值（conviction >= 此值）
    tier_a_threshold: float = Field(85.0, validation_alias="CM_CANDIDATE_TIER_A_THRESHOLD")
    # Tier B 阈值
    tier_b_threshold: float = Field(70.0, validation_alias="CM_CANDIDATE_TIER_B_THRESHOLD")
    # Tier C 阈值
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
