from __future__ import annotations

from datetime import datetime

from src.ingestion.factory.source_strategy_factory import SourceStrategyFactory
from src.shared.schemas.pipeline import MarketTickInput


class ChainIngestionService:
    def __init__(self, chain_id: str, data_mode: str | None = None) -> None:
        self.strategy = SourceStrategyFactory.create(chain_id=chain_id, data_mode=data_mode)

    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        return await self.strategy.fetch_market_ticks(ts_minute=ts_minute)

    async def aclose(self) -> None:
        await self.strategy.aclose()
