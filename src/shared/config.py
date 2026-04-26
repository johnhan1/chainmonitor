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
    app_api_key: str = ""
    app_require_api_key: bool = False
    app_rate_limit_per_minute: int = 600
    app_rate_limit_burst: int = 120
    app_rate_limit_bucket_max_keys: int = 100_000
    app_rate_limit_bucket_key_ttl_seconds: int = 600
    postgres_dsn: str = "postgresql+psycopg://cm:cm@localhost:5432/chainmonitor"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20
    postgres_pool_timeout_seconds: int = 30
    postgres_pool_recycle_seconds: int = 1800
    postgres_statement_timeout_ms: int = 15_000
    postgres_write_batch_size: int = 500
    redis_url: str = "redis://localhost:6379/0"
    clickhouse_http_url: str = "http://localhost:8123"
    minio_endpoint: str = "http://localhost:9002"
    bsc_chain_id: str = "bsc"
    bsc_default_symbols: str = "BNB,CAKE,XVS,BUSD,USDT"
    base_chain_id: str = "base"
    base_default_symbols: str = "WETH,USDC,DEGEN,AERO,BRETT"
    eth_chain_id: str = "eth"
    eth_default_symbols: str = "ETH,USDC,WBTC,PEPE,UNI"
    sol_chain_id: str = "sol"
    sol_default_symbols: str = "SOL,USDC,JUP,WIF,BONK"
    candidate_tier_a_threshold: float = 85.0
    candidate_tier_b_threshold: float = 70.0
    candidate_tier_c_threshold: float = 55.0
    bsc_strategy_version: str = "bsc-mvp-v1"
    base_strategy_version: str = "base-mvp-v1"
    eth_strategy_version: str = "eth-mvp-v1"
    sol_strategy_version: str = "sol-mvp-v1"
    market_data_timeout_seconds: float = 3.0
    market_data_retry_attempts: int = 3
    market_data_retry_base_seconds: float = 0.3
    market_data_retry_max_sleep_seconds: float = 15.0
    market_data_max_concurrency: int = 8
    market_data_rate_limit_per_second: float = 10.0
    market_data_rate_limit_capacity: int = 20
    market_data_rate_limit_capacity_by_chain: str = ""
    market_data_rate_limit_per_second_by_provider: str = ""
    market_data_rate_limit_capacity_by_provider: str = ""
    market_data_rate_limit_per_second_by_provider_chain: str = ""
    market_data_rate_limit_capacity_by_provider_chain: str = ""
    market_data_circuit_failure_threshold: int = 5
    market_data_circuit_recovery_seconds: float = 30.0
    market_data_circuit_half_open_max_calls: int = 2
    market_data_min_success_ratio: float = 0.6
    market_data_min_pair_age_seconds: int = 300
    market_data_max_volume_liquidity_ratio: float = 20.0
    market_data_cache_ttl_seconds: float = 3.0
    market_data_cache_max_entries: int = 2000
    market_data_http_max_connections: int = 100
    market_data_http_max_keepalive_connections: int = 20
    market_data_http_keepalive_expiry_seconds: float = 30.0
    market_data_retry_attempts_by_chain: str = ""
    market_data_max_concurrency_by_chain: str = ""
    market_data_rate_limit_per_second_by_chain: str = ""
    market_data_circuit_failure_threshold_by_chain: str = ""
    market_data_circuit_recovery_seconds_by_chain: str = ""
    market_data_min_success_ratio_by_chain: str = ""
    market_data_min_pair_age_seconds_by_chain: str = ""
    market_data_max_volume_liquidity_ratio_by_chain: str = ""
    market_data_required_address_symbols_by_chain: str = ""
    market_data_require_address_mapping_in_production: bool = True
    market_data_dex_blacklist_ids: str = ""
    market_data_route_blacklist_keywords: str = ""
    market_data_geckoterminal_api_base: str = "https://api.geckoterminal.com/api/v2"
    market_data_geckoterminal_network_by_chain: str = ""
    market_data_birdeye_api_base: str = "https://public-api.birdeye.so/defi"
    market_data_birdeye_api_key: str = ""
    market_data_birdeye_chain_by_chain: str = ""
    ingestion_strategy_order: str = "dexscreener,geckoterminal,birdeye"
    bsc_token_addresses: str = ""
    base_token_addresses: str = ""
    eth_token_addresses: str = ""
    sol_token_addresses: str = ""
    gate_min_liquidity_usd: float = 150_000.0
    gate_min_volume_5m_usd: float = 12_000.0
    gate_min_tx_1m: int = 15
    pipeline_run_timeout_seconds: float = 30.0
    pipeline_fetch_timeout_seconds: float = 20.0
    pipeline_feature_timeout_seconds: float = 10.0
    pipeline_score_timeout_seconds: float = 10.0
    pipeline_persist_timeout_seconds: float = 20.0
    pipeline_candidate_query_cache_ttl_seconds: float = 3.0
    pipeline_replay_require_api_key: bool = True
    pipeline_replay_rate_limit_per_minute: int = 6
    pipeline_replay_rate_limit_burst: int = 2
    pipeline_replay_max_in_flight_per_chain: int = 1
    pipeline_replay_max_lookback_minutes: int = 1_440
    pipeline_replay_max_future_skew_seconds: int = 60
    pipeline_replay_chain_allowlist: str = ""
    pipeline_scheduler_enabled: bool = False
    pipeline_scheduler_interval_seconds: int = 60
    pipeline_scheduler_initial_delay_seconds: int = 5
    pipeline_scheduler_chains: str = "bsc,base,eth,sol"
    pipeline_scheduler_startup_jitter_seconds: int = 7
    pipeline_scheduler_catchup_windows: int = 3

    # GMGN
    cm_gmgn_api_key: str = ""
    cm_gmgn_cli_path: str = "gmgn-cli"
    # Telegram
    cm_telegram_bot_token: str = ""
    cm_telegram_chat_id: str = ""
    # Scanner
    cm_scanner_enabled: bool = False
    cm_scanner_chains: list[str] = ["sol", "bsc", "base", "eth"]
    cm_scanner_surge_threshold: int = 10
    cm_scanner_spike_ratio: float = 2.0
    cm_scanner_interval_1m_seconds: int = 60
    cm_scanner_interval_1h_seconds: int = 300
    cm_scanner_trending_limit: int = 50

    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_",
        extra="ignore",
    )

    @property
    def supported_chains(self) -> tuple[str, ...]:
        return (
            self.bsc_chain_id,
            self.base_chain_id,
            self.eth_chain_id,
            self.sol_chain_id,
        )

    def get_chain_symbols(self, chain_id: str) -> str:
        mapping = {
            self.bsc_chain_id: self.bsc_default_symbols,
            self.base_chain_id: self.base_default_symbols,
            self.eth_chain_id: self.eth_default_symbols,
            self.sol_chain_id: self.sol_default_symbols,
        }
        return mapping[chain_id]

    def get_strategy_version(self, chain_id: str) -> str:
        mapping = {
            self.bsc_chain_id: self.bsc_strategy_version,
            self.base_chain_id: self.base_strategy_version,
            self.eth_chain_id: self.eth_strategy_version,
            self.sol_chain_id: self.sol_strategy_version,
        }
        return mapping[chain_id]

    def get_dexscreener_chain_id(self, chain_id: str) -> str:
        mapping = {
            self.bsc_chain_id: "bsc",
            self.base_chain_id: "base",
            self.eth_chain_id: "ethereum",
            self.sol_chain_id: "solana",
        }
        return mapping[chain_id]

    def get_chain_token_addresses(self, chain_id: str) -> dict[str, str]:
        mapping = {
            self.bsc_chain_id: self.bsc_token_addresses,
            self.base_chain_id: self.base_token_addresses,
            self.eth_chain_id: self.eth_token_addresses,
            self.sol_chain_id: self.sol_token_addresses,
        }
        raw = mapping[chain_id].strip()
        if not raw:
            return {}
        pairs = [item.strip() for item in raw.split(",") if item.strip()]
        parsed: dict[str, str] = {}
        for pair in pairs:
            if "=" not in pair:
                continue
            symbol, address = pair.split("=", 1)
            symbol = symbol.strip().upper()
            address = address.strip()
            if symbol and address:
                parsed[symbol] = address
        return parsed

    def get_geckoterminal_network(self, chain_id: str) -> str:
        parsed = self._parse_chain_override(
            overrides=self.market_data_geckoterminal_network_by_chain
        )
        override = parsed.get(chain_id)
        if override:
            return override
        mapping = {
            self.bsc_chain_id: "bsc",
            self.base_chain_id: "base",
            self.eth_chain_id: "eth",
            self.sol_chain_id: "solana",
        }
        return mapping[chain_id]

    def get_birdeye_chain(self, chain_id: str) -> str:
        parsed = self._parse_chain_override(overrides=self.market_data_birdeye_chain_by_chain)
        override = parsed.get(chain_id)
        if override:
            return override
        mapping = {
            self.bsc_chain_id: "bsc",
            self.base_chain_id: "base",
            self.eth_chain_id: "ethereum",
            self.sol_chain_id: "solana",
        }
        return mapping[chain_id]

    @property
    def enabled_ingestion_strategies(self) -> tuple[str, ...]:
        raw = self.ingestion_strategy_order.strip().lower()
        if not raw:
            return ()
        requested = [item.strip() for item in raw.split(",") if item.strip()]
        deduped = dict.fromkeys(requested)
        return tuple(deduped.keys())

    def get_market_data_retry_attempts(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.market_data_retry_attempts_by_chain,
            default=self.market_data_retry_attempts,
            minimum=1,
        )

    def get_market_data_max_concurrency(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.market_data_max_concurrency_by_chain,
            default=self.market_data_max_concurrency,
            minimum=1,
        )

    def get_market_data_rate_limit_per_second(
        self,
        chain_id: str,
        provider: str | None = None,
    ) -> float:
        provider_value = self._provider_float_override(
            chain_id=chain_id,
            provider=provider,
            provider_chain_overrides=self.market_data_rate_limit_per_second_by_provider_chain,
            provider_overrides=self.market_data_rate_limit_per_second_by_provider,
            minimum=0.01,
        )
        if provider_value is not None:
            return provider_value
        return self._chain_float_override(
            chain_id=chain_id,
            overrides=self.market_data_rate_limit_per_second_by_chain,
            default=self.market_data_rate_limit_per_second,
            minimum=0.01,
        )

    def get_market_data_rate_limit_capacity(
        self,
        chain_id: str,
        provider: str | None = None,
    ) -> int:
        provider_value = self._provider_int_override(
            chain_id=chain_id,
            provider=provider,
            provider_chain_overrides=self.market_data_rate_limit_capacity_by_provider_chain,
            provider_overrides=self.market_data_rate_limit_capacity_by_provider,
            minimum=1,
        )
        if provider_value is not None:
            return provider_value
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.market_data_rate_limit_capacity_by_chain,
            default=self.market_data_rate_limit_capacity,
            minimum=1,
        )

    def get_market_data_circuit_failure_threshold(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.market_data_circuit_failure_threshold_by_chain,
            default=self.market_data_circuit_failure_threshold,
            minimum=1,
        )

    def get_market_data_circuit_recovery_seconds(self, chain_id: str) -> float:
        return self._chain_float_override(
            chain_id=chain_id,
            overrides=self.market_data_circuit_recovery_seconds_by_chain,
            default=self.market_data_circuit_recovery_seconds,
            minimum=0.5,
        )

    def get_market_data_min_success_ratio(self, chain_id: str) -> float:
        value = self._chain_float_override(
            chain_id=chain_id,
            overrides=self.market_data_min_success_ratio_by_chain,
            default=self.market_data_min_success_ratio,
            minimum=0.0,
        )
        return min(1.0, value)

    def get_market_data_min_pair_age_seconds(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.market_data_min_pair_age_seconds_by_chain,
            default=self.market_data_min_pair_age_seconds,
            minimum=0,
        )

    def get_market_data_max_volume_liquidity_ratio(self, chain_id: str) -> float:
        return self._chain_float_override(
            chain_id=chain_id,
            overrides=self.market_data_max_volume_liquidity_ratio_by_chain,
            default=self.market_data_max_volume_liquidity_ratio,
            minimum=0.1,
        )

    def get_market_data_required_address_symbols(self, chain_id: str) -> set[str]:
        parsed = self._parse_chain_override(
            overrides=self.market_data_required_address_symbols_by_chain
        )
        raw = parsed.get(chain_id, "").strip().upper()
        if not raw:
            return set()
        if raw == "*":
            return {
                symbol.strip().upper()
                for symbol in self.get_chain_symbols(chain_id).split(",")
                if symbol.strip()
            }
        return {item.strip().upper() for item in raw.split("|") if item.strip()}

    @property
    def dex_blacklist_ids(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.market_data_dex_blacklist_ids.split(",")
            if item.strip()
        }

    @property
    def route_blacklist_keywords(self) -> tuple[str, ...]:
        return tuple(
            item.strip().lower()
            for item in self.market_data_route_blacklist_keywords.split(",")
            if item.strip()
        )

    @property
    def enabled_scheduler_chains(self) -> tuple[str, ...]:
        requested = [
            item.strip() for item in self.pipeline_scheduler_chains.split(",") if item.strip()
        ]
        if not requested:
            return ()
        supported = set(self.supported_chains)
        deduped = dict.fromkeys(requested)
        return tuple(chain_id for chain_id in deduped if chain_id in supported)

    @property
    def replay_allowed_chains(self) -> tuple[str, ...]:
        raw = self.pipeline_replay_chain_allowlist.strip()
        if not raw:
            return self.supported_chains
        requested = [item.strip() for item in raw.split(",") if item.strip()]
        supported = set(self.supported_chains)
        deduped = dict.fromkeys(requested)
        return tuple(chain_id for chain_id in deduped if chain_id in supported)

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"prod", "production"}

    def _chain_int_override(
        self,
        chain_id: str,
        overrides: str,
        default: int,
        minimum: int,
    ) -> int:
        parsed = self._parse_chain_override(overrides=overrides)
        raw = parsed.get(chain_id)
        if raw is None:
            return max(minimum, int(default))
        try:
            return max(minimum, int(raw))
        except ValueError:
            return max(minimum, int(default))

    def _chain_float_override(
        self,
        chain_id: str,
        overrides: str,
        default: float,
        minimum: float,
    ) -> float:
        parsed = self._parse_chain_override(overrides=overrides)
        raw = parsed.get(chain_id)
        if raw is None:
            return max(minimum, float(default))
        try:
            return max(minimum, float(raw))
        except ValueError:
            return max(minimum, float(default))

    def _provider_int_override(
        self,
        chain_id: str,
        provider: str | None,
        provider_chain_overrides: str,
        provider_overrides: str,
        minimum: int,
    ) -> int | None:
        provider_key = (provider or "").strip().lower()
        if not provider_key:
            return None
        provider_chain_parsed = self._parse_provider_chain_override(
            overrides=provider_chain_overrides
        )
        raw = provider_chain_parsed.get((provider_key, chain_id))
        if raw is not None:
            try:
                return max(minimum, int(raw))
            except ValueError:
                return None
        provider_parsed = self._parse_provider_override(overrides=provider_overrides)
        raw = provider_parsed.get(provider_key)
        if raw is not None:
            try:
                return max(minimum, int(raw))
            except ValueError:
                return None
        return None

    def _provider_float_override(
        self,
        chain_id: str,
        provider: str | None,
        provider_chain_overrides: str,
        provider_overrides: str,
        minimum: float,
    ) -> float | None:
        provider_key = (provider or "").strip().lower()
        if not provider_key:
            return None
        provider_chain_parsed = self._parse_provider_chain_override(
            overrides=provider_chain_overrides
        )
        raw = provider_chain_parsed.get((provider_key, chain_id))
        if raw is not None:
            try:
                return max(minimum, float(raw))
            except ValueError:
                return None
        provider_parsed = self._parse_provider_override(overrides=provider_overrides)
        raw = provider_parsed.get(provider_key)
        if raw is not None:
            try:
                return max(minimum, float(raw))
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_chain_override(overrides: str) -> dict[str, str]:
        items = [item.strip() for item in overrides.split(",") if item.strip()]
        parsed: dict[str, str] = {}
        for item in items:
            if "=" not in item:
                continue
            chain_id, value = item.split("=", 1)
            chain_key = chain_id.strip().lower()
            value = value.strip()
            if chain_key and value:
                parsed[chain_key] = value
        return parsed

    @staticmethod
    def _parse_provider_override(overrides: str) -> dict[str, str]:
        items = [item.strip() for item in overrides.split(",") if item.strip()]
        parsed: dict[str, str] = {}
        for item in items:
            if "=" not in item:
                continue
            provider, value = item.split("=", 1)
            provider_key = provider.strip().lower()
            value = value.strip()
            if provider_key and value:
                parsed[provider_key] = value
        return parsed

    @staticmethod
    def _parse_provider_chain_override(overrides: str) -> dict[tuple[str, str], str]:
        items = [item.strip() for item in overrides.split(",") if item.strip()]
        parsed: dict[tuple[str, str], str] = {}
        for item in items:
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if ":" not in key:
                continue
            provider, chain_id = key.split(":", 1)
            provider = provider.strip().lower()
            chain_id = chain_id.strip().lower()
            if provider and chain_id and value:
                parsed[(provider, chain_id)] = value
        return parsed


@lru_cache
def get_settings() -> Settings:
    return Settings()
