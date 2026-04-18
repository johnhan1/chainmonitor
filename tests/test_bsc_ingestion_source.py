from datetime import UTC, datetime

from src.ingestion.bsc_source import BscIngestionSource


def test_bsc_ingestion_source_is_deterministic_for_same_minute() -> None:
    source = BscIngestionSource()
    ts = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)

    rows1 = source.fetch_market_ticks(ts_minute=ts)
    rows2 = source.fetch_market_ticks(ts_minute=ts)

    assert len(rows1) == len(rows2)
    assert [r.model_dump() for r in rows1] == [r.model_dump() for r in rows2]
