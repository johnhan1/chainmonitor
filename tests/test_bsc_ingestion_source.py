from datetime import UTC, datetime

from src.ingestion.contracts.source_strategy import SourceStrategy
from src.ingestion.services.chain_ingestion_service import ChainIngestionService
from src.shared.schemas.pipeline import MarketTickInput


class _FakeStrategy(SourceStrategy):
    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        target = ts_minute or datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
        return [
            MarketTickInput(
                chain_id="bsc",
                token_id="bsc_bnb",
                ts_minute=target,
                price_usd=600.0,
                volume_1m=10_000.0,
                volume_5m=50_000.0,
                liquidity_usd=500_000.0,
                buys_1m=10,
                sells_1m=8,
                tx_count_1m=18,
            )
        ]


def test_bsc_ingestion_service_forwards_strategy_result() -> None:
    source = ChainIngestionService(chain_id="bsc")
    source.strategy = _FakeStrategy()
    ts = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)

    import asyncio

    rows = asyncio.run(source.fetch_market_ticks(ts_minute=ts))

    assert len(rows) == 1
    assert rows[0].token_id == "bsc_bnb"
