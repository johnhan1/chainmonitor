from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_app_env = os.getenv("CM_APP_ENV", "dev")


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_app_env}"),
        env_file_encoding="utf-8",
        env_prefix="CM_MARKET_DATA_",
        extra="ignore",
    )

    # HTTP 请求超时秒数
    timeout_seconds: float = 3.0
    # 请求重试次数
    retry_attempts: int = 3
    # 退避策略初始秒数
    retry_base_seconds: float = 0.3
    # 退避策略最大秒数
    retry_max_sleep_seconds: float = 15.0
    # 默认最大并发数（可被按链覆盖）
    max_concurrency: int = 8
    # 令牌桶速率（每秒许可数，可被按链/按 Provider 覆盖）
    rate_limit_per_second: float = 10.0
    # 令牌桶容量（可被按链/按 Provider 覆盖）
    rate_limit_capacity: int = 20
    # 按链覆盖令牌桶容量，格式: chain_id=capacity,chain_id=capacity
    rate_limit_capacity_by_chain: str = ""
    # 按 Provider 覆盖速率，格式: provider=rate,provider=rate
    rate_limit_per_second_by_provider: str = ""
    # 按 Provider 覆盖容量，格式: provider=capacity,provider=capacity
    rate_limit_capacity_by_provider: str = ""
    # 按 Provider+链 覆盖速率，格式: provider:chain=rate,provider:chain=rate
    rate_limit_per_second_by_provider_chain: str = ""
    # 按 Provider+链 覆盖容量，格式: provider:chain=capacity
    rate_limit_capacity_by_provider_chain: str = ""
    # 断路器：连续失败次数阈值
    circuit_failure_threshold: int = 5
    # 断路器：半开后等待恢复秒数
    circuit_recovery_seconds: float = 30.0
    # 断路器：半开状态下最大试探请求数
    circuit_half_open_max_calls: int = 2
    # 一次采集所需的最低成功比例（成功symbol/总symbol）
    min_success_ratio: float = 0.6
    # 新交易对最低存活时间（秒），低于此值认为不可靠
    min_pair_age_seconds: int = 300
    # 成交量/流动性的最大允许比率，超过则过滤
    max_volume_liquidity_ratio: float = 20.0
    # 响应缓存 TTL（秒）
    cache_ttl_seconds: float = 3.0
    # 响应缓存最大条目数
    cache_max_entries: int = 2000
    # HTTP 连接池最大连接数
    http_max_connections: int = 100
    # HTTP 连接池最大 Keepalive 连接数
    http_max_keepalive_connections: int = 20
    # HTTP Keepalive 过期秒数
    http_keepalive_expiry_seconds: float = 30.0
    # 按链覆盖重试次数，格式: chain_id=N
    retry_attempts_by_chain: str = ""
    # 按链覆盖最大并发数，格式: chain_id=N
    max_concurrency_by_chain: str = ""
    # 按链覆盖令牌桶速率，格式: chain_id=rate
    rate_limit_per_second_by_chain: str = ""
    # 按链覆盖断路器阈值，格式: chain_id=N
    circuit_failure_threshold_by_chain: str = ""
    # 按链覆盖断路器恢复秒数，格式: chain_id=seconds
    circuit_recovery_seconds_by_chain: str = ""
    # 按链覆盖最低成功比例，格式: chain_id=ratio
    min_success_ratio_by_chain: str = ""
    # 按链覆盖最低交易对年龄，格式: chain_id=seconds
    min_pair_age_seconds_by_chain: str = ""
    # 按链覆盖成交量/流动性比率上限，格式: chain_id=ratio
    max_volume_liquidity_ratio_by_chain: str = ""
    # 按链要求必须提供地址映射的 Symbol 列表（* 表示全部）
    required_address_symbols_by_chain: str = ""
    # 生产环境是否强制要求地址映射
    require_address_mapping_in_production: bool = True
    # DEX 黑名单 ID 列表，逗号分隔
    dex_blacklist_ids: str = ""
    # 路由关键词黑名单，匹配 pair_address/url 时过滤
    route_blacklist_keywords: str = ""
    # GeckoTerminal API 基础 URL
    geckoterminal_api_base: str = "https://api.geckoterminal.com/api/v2"
    # 按链覆盖 GeckoTerminal 网络名，格式: chain_id=network
    geckoterminal_network_by_chain: str = ""
    # Birdeye API 基础 URL
    birdeye_api_base: str = "https://public-api.birdeye.so/defi"
    # Birdeye API 密钥
    birdeye_api_key: str = ""
    # 按链覆盖 Birdeye 链名，格式: chain_id=chain_name
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
