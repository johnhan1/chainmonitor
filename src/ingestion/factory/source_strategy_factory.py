from __future__ import annotations

from src.ingestion.contracts.source_strategy import SourceStrategy
from src.ingestion.fallback.fallback_source_chain import FallbackSourceChain
from src.ingestion.strategies.birdeye_source_strategy import BirdeyeSourceStrategy
from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy
from src.ingestion.strategies.geckoterminal_source_strategy import GeckoTerminalSourceStrategy
from src.shared.config import Settings, get_settings


class SourceStrategyFactory:
    _registry = {
        "birdeye": BirdeyeSourceStrategy,
        "dexscreener": DexScreenerSourceStrategy,
        "geckoterminal": GeckoTerminalSourceStrategy,
    }

    @staticmethod
    def create(chain_id: str) -> SourceStrategy:
        settings = get_settings()
        SourceStrategyFactory.validate_settings(settings)
        strategy_names = settings.enabled_ingestion_strategies
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
    def validate_settings(settings: Settings) -> None:
        strategy_names = settings.enabled_ingestion_strategies
        if not strategy_names:
            raise ValueError("ingestion_strategy_order must configure at least one strategy")
        supported = set(SourceStrategyFactory._registry.keys())
        for strategy_name in strategy_names:
            if strategy_name not in supported:
                raise ValueError(f"unsupported ingestion strategy '{strategy_name}'")
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
