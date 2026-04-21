import asyncio
from datetime import UTC, datetime

import pytest
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.normalized_pair import NormalizedPair
from src.ingestion.contracts.pair_quality_policy import PairQualityPolicy
from src.ingestion.contracts.provider_adapter import ProviderAdapter
from src.ingestion.strategies.base_live_source_strategy import BaseLiveSourceStrategy


class _InMemoryAdapter(ProviderAdapter):
    def __init__(
        self,
        address_pairs: dict[str, NormalizedPair] | None = None,
        symbol_pairs: dict[str, NormalizedPair] | None = None,
    ) -> None:
        self._address_pairs = address_pairs or {}
        self._symbol_pairs = symbol_pairs or {}

    async def fetch_pairs_by_addresses(
        self,
        symbol_to_address: dict[str, str],
        trace_id: str,
    ) -> dict[str, NormalizedPair]:
        _ = (symbol_to_address, trace_id)
        return dict(self._address_pairs)

    async def fetch_pair_by_symbol(self, symbol: str, trace_id: str) -> NormalizedPair | None:
        _ = trace_id
        return self._symbol_pairs.get(symbol)


class _AllowAllPolicy(PairQualityPolicy):
    def is_acceptable(self, pair: NormalizedPair, chain_id: str) -> bool:
        _ = (pair, chain_id)
        return True


class _DenyAllPolicy(PairQualityPolicy):
    def is_acceptable(self, pair: NormalizedPair, chain_id: str) -> bool:
        _ = (pair, chain_id)
        return False


class _TestLiveStrategy(BaseLiveSourceStrategy):
    pass


def _mk_pair(symbol: str, price: float, buys_5m: int, sells_5m: int) -> NormalizedPair:
    return NormalizedPair(
        chain_id="bsc",
        symbol=symbol,
        source="unit-test",
        price_usd=price,
        volume_5m=1000.0,
        liquidity_usd=5000.0,
        buys_5m=buys_5m,
        sells_5m=sells_5m,
        pair_created_at_ms=1_700_000_000_000,
    )


def test_base_live_source_strategy_builds_market_tick_rows(monkeypatch) -> None:
    strategy = _TestLiveStrategy(
        chain_id="bsc",
        adapter=_InMemoryAdapter(
            symbol_pairs={
                "BNB": _mk_pair("BNB", 600.0, 50, 25),
                "CAKE": _mk_pair("CAKE", 2.5, 30, 10),
            }
        ),
        quality_policy=_AllowAllPolicy(),
    )
    strategy.settings.bsc_token_addresses = ""
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB", "CAKE"], raising=True)
    ts = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)

    rows = asyncio.run(strategy.fetch_market_ticks(ts_minute=ts))

    assert [row.token_id for row in rows] == ["bsc_bnb", "bsc_cake"]
    assert rows[0].price_usd == 600.0
    assert rows[0].buys_1m == 10
    assert rows[0].sells_1m == 5
    assert rows[0].tx_count_1m == 15


def test_base_live_source_strategy_raises_when_all_pairs_filtered(monkeypatch) -> None:
    strategy = _TestLiveStrategy(
        chain_id="bsc",
        adapter=_InMemoryAdapter(symbol_pairs={"BNB": _mk_pair("BNB", 600.0, 50, 25)}),
        quality_policy=_DenyAllPolicy(),
    )
    strategy.settings.bsc_token_addresses = ""
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)
    ts = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)

    with pytest.raises(IngestionFetchError, match="no_valid_rows"):
        asyncio.run(strategy.fetch_market_ticks(ts_minute=ts))
