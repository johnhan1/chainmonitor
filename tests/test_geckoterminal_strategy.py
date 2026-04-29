import asyncio
from datetime import UTC, datetime

import pytest
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.normalized_pair import NormalizedPair
from src.ingestion.strategies.geckoterminal_source_strategy import GeckoTerminalSourceStrategy


def test_geckoterminal_strategy_builds_market_tick(monkeypatch) -> None:
    strategy = GeckoTerminalSourceStrategy(chain_id="bsc")
    strategy._ingestion_settings.require_address_mapping_in_production = False
    strategy._ingestion_settings.required_address_symbols_by_chain = ""
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        return NormalizedPair(
            chain_id="bsc",
            symbol="BNB",
            source="geckoterminal",
            price_usd=600.0,
            volume_5m=100000.0,
            liquidity_usd=2000000.0,
            buys_5m=180,
            sells_5m=120,
            pair_created_at_ms=1700000000000,
            dex_id="pancakeswap_v3",
            pair_address="0xpool",
            url="https://www.geckoterminal.com/bsc/pools/0xpool",
            base_token_address="0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
        )

    monkeypatch.setattr(
        strategy._adapter,
        "fetch_pairs_by_addresses",
        fake_fetch_by_addresses,
        raising=True,  # noqa: SLF001
    )
    monkeypatch.setattr(
        strategy._adapter,
        "fetch_pair_by_symbol",
        fake_fetch_by_symbol,
        raising=True,  # noqa: SLF001
    )

    rows = asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert len(rows) == 1
    row = rows[0]
    assert row.token_id == "bsc_bnb"
    assert row.price_usd == 600.0
    assert row.volume_1m == 20000.0
    assert row.tx_count_1m == 60


def test_geckoterminal_strategy_raises_when_required_mapping_missing(monkeypatch) -> None:
    strategy = GeckoTerminalSourceStrategy(chain_id="bsc")
    strategy._ingestion_settings.required_address_symbols_by_chain = "bsc=BNB"
    strategy.settings.bsc_token_addresses = ""
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "required_mapping_missing"
