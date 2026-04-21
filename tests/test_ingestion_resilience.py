import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.source_strategy import SourceStrategy
from src.ingestion.fallback.fallback_source_chain import FallbackSourceChain
from src.ingestion.resilience.resilient_http_client import ResilientHttpClient
from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy
from src.shared.config import get_settings
from src.shared.schemas.pipeline import MarketTickInput


class _FailingPrimary(SourceStrategy):
    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        raise IngestionFetchError(
            reason="upstream_unavailable",
            detail="simulated",
            chain_id="bsc",
            trace_id="trace123",
        )


class _StaticSecondary(SourceStrategy):
    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        ts = ts_minute or datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
        symbols = ["BNB", "CAKE", "XVS", "BUSD", "USDT"]
        return [
            MarketTickInput(
                chain_id="bsc",
                token_id=f"bsc_{symbol.lower()}",
                ts_minute=ts,
                price_usd=1.0,
                volume_1m=10_000.0,
                volume_5m=50_000.0,
                liquidity_usd=300_000.0,
                buys_1m=30,
                sells_1m=10,
                tx_count_1m=45,
            )
            for symbol in symbols
        ]


def test_fallback_chain_uses_secondary_when_primary_raises() -> None:
    chain = FallbackSourceChain(
        chain_id="bsc",
        sources=[_FailingPrimary(), _StaticSecondary()],
    )
    rows = asyncio.run(chain.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert len(rows) == 5
    assert all(row.chain_id == "bsc" for row in rows)


def test_resilient_http_client_retries_on_429(monkeypatch) -> None:
    settings = get_settings()
    client = ResilientHttpClient(chain_id="bsc", settings=settings)
    client._cache_ttl_seconds = 0  # noqa: SLF001
    calls = {"count": 0}

    async def fake_get(self, url, *args, **kwargs):  # noqa: ANN001
        calls["count"] += 1
        request = httpx.Request("GET", url)
        if calls["count"] == 1:
            return httpx.Response(status_code=429, request=request, json={"pairs": []})
        return httpx.Response(status_code=200, request=request, json={"pairs": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get, raising=True)

    payload = asyncio.run(
        client.get_json(
            url="https://api.dexscreener.com/latest/dex/search?q=BNB",
            endpoint="search",
            trace_id="trace-test",
            trace="symbol:BNB",
        )
    )
    assert payload is not None
    assert calls["count"] >= 2
    asyncio.run(client.aclose())


def test_resilient_http_client_retry_after_http_date_is_used() -> None:
    settings = get_settings()
    client = ResilientHttpClient(chain_id="bsc", settings=settings)
    retry_at = datetime.now(tz=UTC) + timedelta(seconds=2)
    response = httpx.Response(
        status_code=429,
        request=httpx.Request("GET", "https://api.dexscreener.com/latest/dex/search?q=BNB"),
        headers={"Retry-After": retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")},
    )
    value = client._retry_after_seconds(response=response)  # noqa: SLF001
    assert value is not None
    assert 0.0 < value <= 3.0


def test_insufficient_coverage_raises(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc")
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB", "CAKE"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

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

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "insufficient_coverage"


def test_required_symbol_invalid_when_row_filtered(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc")
    strategy.settings.market_data_min_success_ratio = 1.0
    strategy.settings.market_data_required_address_symbols_by_chain = "bsc=BNB"
    strategy.settings.bsc_token_addresses = "BNB=0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        from src.ingestion.contracts.normalized_pair import NormalizedPair

        return {
            "BNB": NormalizedPair(
                chain_id="bsc",
                symbol="BNB",
                source="dexscreener",
                price_usd=0.0,
                volume_5m=100000.0,
                liquidity_usd=1500000.0,
                buys_5m=200,
                sells_5m=100,
                pair_created_at_ms=1700000000000,
                dex_id="pancakeswap",
                pair_address="0xpair1",
                url="https://dexscreener.com/bsc/pair1",
                base_token_address="0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
            )
        }

    monkeypatch.setattr(
        strategy._adapter,
        "fetch_pairs_by_addresses",
        fake_fetch_by_addresses,
        raising=True,  # noqa: SLF001
    )

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "required_symbol_invalid"
    assert "BNB" in exc.value.detail
