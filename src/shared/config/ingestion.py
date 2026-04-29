from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CM_MARKET_DATA_", extra="ignore")

    timeout_seconds: float = 3.0
    retry_attempts: int = 3
    retry_base_seconds: float = 0.3
    retry_max_sleep_seconds: float = 15.0
    max_concurrency: int = 8
    rate_limit_per_second: float = 10.0
    rate_limit_capacity: int = 20
    rate_limit_capacity_by_chain: str = ""
    rate_limit_per_second_by_provider: str = ""
    rate_limit_capacity_by_provider: str = ""
    rate_limit_per_second_by_provider_chain: str = ""
    rate_limit_capacity_by_provider_chain: str = ""
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    circuit_half_open_max_calls: int = 2
    min_success_ratio: float = 0.6
    min_pair_age_seconds: int = 300
    max_volume_liquidity_ratio: float = 20.0
    cache_ttl_seconds: float = 3.0
    cache_max_entries: int = 2000
    http_max_connections: int = 100
    http_max_keepalive_connections: int = 20
    http_keepalive_expiry_seconds: float = 30.0
    retry_attempts_by_chain: str = ""
    max_concurrency_by_chain: str = ""
    rate_limit_per_second_by_chain: str = ""
    circuit_failure_threshold_by_chain: str = ""
    circuit_recovery_seconds_by_chain: str = ""
    min_success_ratio_by_chain: str = ""
    min_pair_age_seconds_by_chain: str = ""
    max_volume_liquidity_ratio_by_chain: str = ""
    required_address_symbols_by_chain: str = ""
    require_address_mapping_in_production: bool = True
    dex_blacklist_ids: str = ""
    route_blacklist_keywords: str = ""
    geckoterminal_api_base: str = "https://api.geckoterminal.com/api/v2"
    geckoterminal_network_by_chain: str = ""
    birdeye_api_base: str = "https://public-api.birdeye.so/defi"
    birdeye_api_key: str = ""
    birdeye_chain_by_chain: str = ""

    @property
    def dex_blacklist_ids_set(self) -> set[str]:
        return {item.strip().lower() for item in self.dex_blacklist_ids.split(",") if item.strip()}

    @property
    def route_blacklist_keywords_tuple(self) -> tuple[str, ...]:
        return tuple(
            item.strip().lower()
            for item in self.route_blacklist_keywords.split(",")
            if item.strip()
        )

    def get_retry_attempts(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.retry_attempts_by_chain,
            default=self.retry_attempts,
            minimum=1,
        )

    def get_max_concurrency(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.max_concurrency_by_chain,
            default=self.max_concurrency,
            minimum=1,
        )

    def get_rate_limit_per_second(self, chain_id: str, provider: str | None = None) -> float:
        provider_value = self._provider_float_override(
            chain_id=chain_id,
            provider=provider,
            provider_chain_overrides=self.rate_limit_per_second_by_provider_chain,
            provider_overrides=self.rate_limit_per_second_by_provider,
            minimum=0.01,
        )
        if provider_value is not None:
            return provider_value
        return self._chain_float_override(
            chain_id=chain_id,
            overrides=self.rate_limit_per_second_by_chain,
            default=self.rate_limit_per_second,
            minimum=0.01,
        )

    def get_rate_limit_capacity(self, chain_id: str, provider: str | None = None) -> int:
        provider_value = self._provider_int_override(
            chain_id=chain_id,
            provider=provider,
            provider_chain_overrides=self.rate_limit_capacity_by_provider_chain,
            provider_overrides=self.rate_limit_capacity_by_provider,
            minimum=1,
        )
        if provider_value is not None:
            return provider_value
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.rate_limit_capacity_by_chain,
            default=self.rate_limit_capacity,
            minimum=1,
        )

    def get_circuit_failure_threshold(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.circuit_failure_threshold_by_chain,
            default=self.circuit_failure_threshold,
            minimum=1,
        )

    def get_circuit_recovery_seconds(self, chain_id: str) -> float:
        return self._chain_float_override(
            chain_id=chain_id,
            overrides=self.circuit_recovery_seconds_by_chain,
            default=self.circuit_recovery_seconds,
            minimum=0.5,
        )

    def get_min_success_ratio(self, chain_id: str) -> float:
        value = self._chain_float_override(
            chain_id=chain_id,
            overrides=self.min_success_ratio_by_chain,
            default=self.min_success_ratio,
            minimum=0.0,
        )
        return min(1.0, value)

    def get_min_pair_age_seconds(self, chain_id: str) -> int:
        return self._chain_int_override(
            chain_id=chain_id,
            overrides=self.min_pair_age_seconds_by_chain,
            default=self.min_pair_age_seconds,
            minimum=0,
        )

    def get_max_volume_liquidity_ratio(self, chain_id: str) -> float:
        return self._chain_float_override(
            chain_id=chain_id,
            overrides=self.max_volume_liquidity_ratio_by_chain,
            default=self.max_volume_liquidity_ratio,
            minimum=0.1,
        )

    def get_required_address_symbols(self, chain_id: str) -> set[str]:
        from src.shared.config.chain import get_chain_settings

        chain_settings = get_chain_settings()
        parsed = self._parse_chain_override(overrides=self.required_address_symbols_by_chain)
        raw = parsed.get(chain_id, "").strip().upper()
        if not raw:
            return set()
        if raw == "*":
            return {
                symbol.strip().upper()
                for symbol in chain_settings.get_chain_symbols(chain_id).split(",")
                if symbol.strip()
            }
        return {item.strip().upper() for item in raw.split("|") if item.strip()}

    def _chain_int_override(self, chain_id: str, overrides: str, default: int, minimum: int) -> int:
        parsed = self._parse_chain_override(overrides=overrides)
        raw = parsed.get(chain_id)
        if raw is None:
            return max(minimum, int(default))
        try:
            return max(minimum, int(raw))
        except ValueError:
            return max(minimum, int(default))

    def _chain_float_override(
        self, chain_id: str, overrides: str, default: float, minimum: float
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
def get_ingestion_settings() -> IngestionSettings:
    return IngestionSettings()
