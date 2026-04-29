from __future__ import annotations

from src.ingestion.contracts.source_strategy import SourceStrategy
from src.ingestion.fallback.fallback_source_chain import FallbackSourceChain
from src.ingestion.strategies.birdeye_source_strategy import BirdeyeSourceStrategy
from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy
from src.ingestion.strategies.geckoterminal_source_strategy import GeckoTerminalSourceStrategy
from src.shared.config.chain import ChainSettings, get_chain_settings
from src.shared.config.ingestion import IngestionSettings, get_ingestion_settings


class SourceStrategyFactory:
    _registry = {
        "birdeye": BirdeyeSourceStrategy,
        "dexscreener": DexScreenerSourceStrategy,
        "geckoterminal": GeckoTerminalSourceStrategy,
    }

    @staticmethod
    def create(chain_id: str) -> SourceStrategy:
        chain_settings = get_chain_settings()
        ingestion_settings = get_ingestion_settings()
        SourceStrategyFactory.validate_settings(chain_settings, ingestion_settings)
        strategy_names = chain_settings.enabled_ingestion_strategies
        if not strategy_names:
            raise ValueError("ingestion_strategy_order must configure at least one strategy")
        try:
            strategy_classes = [SourceStrategyFactory._registry[name] for name in strategy_names]
        except KeyError as exc:
            supported = ",".join(sorted(SourceStrategyFactory._registry))
            raise ValueError(
                f"unsupported ingestion strategy '{exc.args[0]}', supported={supported}"
            ) from exc
        sources = [strategy_cls(chain_id=chain_id) for strategy_cls in strategy_classes]
        return FallbackSourceChain(chain_id=chain_id, sources=sources)

    @staticmethod
    def validate_settings(
        chain_settings: ChainSettings, ingestion_settings: IngestionSettings
    ) -> None:
        strategy_names = chain_settings.enabled_ingestion_strategies
        if not strategy_names:
            raise ValueError("ingestion_strategy_order must configure at least one strategy")
        supported = set(SourceStrategyFactory._registry.keys())
        for strategy_name in strategy_names:
            if strategy_name not in supported:
                raise ValueError(f"unsupported ingestion strategy '{strategy_name}'")
        if not 0.0 <= ingestion_settings.min_success_ratio <= 1.0:
            raise ValueError("market_data_min_success_ratio must be in [0,1]")
        for chain_id in chain_settings.supported_chains:
            ingestion_settings.get_retry_attempts(chain_id=chain_id)
            ingestion_settings.get_max_concurrency(chain_id=chain_id)
            ingestion_settings.get_rate_limit_per_second(chain_id=chain_id)
            ingestion_settings.get_circuit_failure_threshold(chain_id=chain_id)
            ingestion_settings.get_circuit_recovery_seconds(chain_id=chain_id)
            ingestion_settings.get_min_success_ratio(chain_id=chain_id)
            ingestion_settings.get_min_pair_age_seconds(chain_id=chain_id)
            ingestion_settings.get_max_volume_liquidity_ratio(chain_id=chain_id)
