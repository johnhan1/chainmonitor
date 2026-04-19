import asyncio
from datetime import UTC, datetime

from src.ingestion.services.chain_ingestion_service import ChainIngestionService


def test_bsc_ingestion_source_is_deterministic_for_same_minute() -> None:
    source = ChainIngestionService(chain_id="bsc", data_mode="mock")
    ts = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)

    rows1 = asyncio.run(source.fetch_market_ticks(ts_minute=ts))
    rows2 = asyncio.run(source.fetch_market_ticks(ts_minute=ts))

    assert len(rows1) == len(rows2)
    assert [r.model_dump() for r in rows1] == [r.model_dump() for r in rows2]
