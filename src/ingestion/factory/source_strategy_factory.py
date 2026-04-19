from __future__ import annotations

from src.ingestion.contracts.source_strategy import SourceStrategy
from src.ingestion.fallback.fallback_source_chain import FallbackSourceChain
from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy
from src.ingestion.strategies.mock_source_strategy import MockSourceStrategy
from src.shared.config import Settings, get_settings


class SourceStrategyFactory:
    _registry = {
        "dexscreener": DexScreenerSourceStrategy,
        "mock": MockSourceStrategy,
    }

    @staticmethod
    def create(chain_id: str, data_mode: str | None = None) -> SourceStrategy:
        settings = get_settings()
        SourceStrategyFactory.validate_settings(settings)
        primary_name = settings.ingestion_primary_strategy.strip().lower()
        secondary_name = settings.ingestion_secondary_strategy.strip().lower()
        SourceStrategyFactory.validate_runtime_safety(
            settings=settings,
            data_mode=data_mode,
            primary_name=primary_name,
            secondary_name=secondary_name,
        )
        try:
            primary_cls = SourceStrategyFactory._registry[primary_name]
            secondary_cls = SourceStrategyFactory._registry[secondary_name]
        except KeyError as exc:
            supported = ",".join(sorted(SourceStrategyFactory._registry))
            raise ValueError(
                f"unsupported ingestion strategy '{exc.args[0]}', supported={supported}"
            ) from exc

        primary = primary_cls(chain_id=chain_id, data_mode=data_mode)
        secondary = secondary_cls(chain_id=chain_id, data_mode=data_mode)
        return FallbackSourceChain(
            chain_id=chain_id,
            primary=primary,
            secondary=secondary,
            data_mode=data_mode,
        )

    @staticmethod
    def validate_settings(settings: Settings) -> None:
        primary_name = settings.ingestion_primary_strategy.strip().lower()
        secondary_name = settings.ingestion_secondary_strategy.strip().lower()
        supported = set(SourceStrategyFactory._registry.keys())
        if primary_name not in supported:
            raise ValueError(f"unsupported ingestion primary strategy '{primary_name}'")
        if secondary_name not in supported:
            raise ValueError(f"unsupported ingestion secondary strategy '{secondary_name}'")
        if not 0.0 <= settings.market_data_min_success_ratio <= 1.0:
            raise ValueError("market_data_min_success_ratio must be in [0,1]")
        for chain_id in settings.supported_chains:
            settings.get_market_data_retry_attempts(chain_id=chain_id)
            settings.get_market_data_max_concurrency(chain_id=chain_id)
            settings.get_market_data_rate_limit_per_second(chain_id=chain_id)
            settings.get_market_data_circuit_failure_threshold(chain_id=chain_id)
            settings.get_market_data_circuit_recovery_seconds(chain_id=chain_id)
            settings.get_market_data_min_success_ratio(chain_id=chain_id)
            settings.get_market_data_min_pair_age_seconds(chain_id=chain_id)
            settings.get_market_data_max_volume_liquidity_ratio(chain_id=chain_id)

    @staticmethod
    def validate_runtime_safety(
        settings: Settings,
        data_mode: str | None,
        primary_name: str,
        secondary_name: str,
    ) -> None:
        mode = (data_mode or settings.market_data_mode).strip().lower()
        if mode not in {"live", "mock", "hybrid"}:
            raise ValueError(f"unsupported market_data_mode: {mode}")
        if not settings.is_production or settings.ingestion_allow_mock_in_production:
            return
        if mode == "mock":
            raise ValueError("mock market_data_mode is forbidden in production")
        if mode == "hybrid" and (primary_name == "mock" or secondary_name == "mock"):
            raise ValueError("mock strategy is forbidden in production hybrid mode")
