import asyncio
from datetime import UTC, datetime

from src.app.services.chain_pipeline_service import ChainPipelineService
from src.ingestion.services.chain_ingestion_service import ChainIngestionService
from src.shared.config import get_settings
from src.shared.schemas.pipeline import MarketTickInput


def test_market_ingestion_source_mock_supports_all_phase1_chains() -> None:
    settings = get_settings()
    ts = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
    for chain_id in settings.supported_chains:
        source = ChainIngestionService(chain_id=chain_id, data_mode="mock")
        rows = asyncio.run(source.fetch_market_ticks(ts_minute=ts))
        assert len(rows) > 0
        assert all(row.chain_id == chain_id for row in rows)


def test_gate_filter_removes_non_tradeable_ticks() -> None:
    service = ChainPipelineService(chain_id="bsc")
    ts = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
    kept = MarketTickInput(
        chain_id="bsc",
        token_id="bsc_kept",
        ts_minute=ts,
        price_usd=1.0,
        volume_1m=5_000.0,
        volume_5m=30_000.0,
        liquidity_usd=300_000.0,
        buys_1m=20,
        sells_1m=8,
        tx_count_1m=40,
    )
    dropped = MarketTickInput(
        chain_id="bsc",
        token_id="bsc_dropped",
        ts_minute=ts,
        price_usd=1.0,
        volume_1m=200.0,
        volume_5m=500.0,
        liquidity_usd=2_000.0,
        buys_1m=1,
        sells_1m=1,
        tx_count_1m=2,
    )

    filtered = service._apply_gate([kept, dropped])
    assert [row.token_id for row in filtered] == ["bsc_kept"]
