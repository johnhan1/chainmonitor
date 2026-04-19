import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.source_strategy import SourceStrategy
from src.ingestion.fallback.fallback_source_chain import FallbackSourceChain
from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy
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
        primary=_FailingPrimary(),
        secondary=_StaticSecondary(),
        data_mode="hybrid",
    )
    rows = asyncio.run(chain.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert len(rows) == 5
    assert all(row.chain_id == "bsc" for row in rows)


def test_retry_on_retryable_status(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    calls = {"count": 0}

    async def fake_get(self, url, *args, **kwargs):  # noqa: ANN001
        calls["count"] += 1
        request = httpx.Request("GET", url)
        if calls["count"] == 1:
            return httpx.Response(status_code=429, request=request, json={"pairs": []})
        return httpx.Response(status_code=200, request=request, json={"pairs": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get, raising=True)

    async def _run() -> dict | None:
        async with httpx.AsyncClient() as client:
            return await strategy._request_json(
                client=client,
                url="https://api.dexscreener.com/latest/dex/search?q=BNB",
                endpoint="search",
                trace_id="trace-test",
                trace="symbol:BNB",
            )

    payload = asyncio.run(_run())
    assert payload is not None
    assert calls["count"] >= 2


def test_non_retryable_404_fail_fast(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy._cache_ttl_seconds = 0
    calls = {"count": 0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def fake_get(self, url, *args, **kwargs):  # noqa: ANN001
        calls["count"] += 1
        request = httpx.Request("GET", url)
        return httpx.Response(status_code=404, request=request, json={"detail": "not found"})

    monkeypatch.setattr(asyncio, "sleep", fake_sleep, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get, raising=True)

    async def _run() -> dict | None:
        client = await strategy._get_http_client()
        return await strategy._request_json(
            client=client,
            url="https://api.dexscreener.com/latest/dex/search?q=BNB",
            endpoint="search",
            trace_id="trace-test",
            trace="symbol:BNB",
        )

    payload = asyncio.run(_run())
    assert payload is None
    assert calls["count"] == 1
    assert sleeps == []


def test_insufficient_coverage_raises(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB", "CAKE"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        symbol = kwargs["symbol"]
        return symbol, None

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )
    monkeypatch.setattr(strategy, "_fetch_pair_by_symbol", fake_fetch_by_symbol, raising=True)

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "insufficient_coverage"


def test_chaos_malformed_pair_fields_raise_no_valid_rows(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        # malformed / suspicious pair: missing pairCreatedAt and invalid quality fields
        return "BNB", {
            "chainId": "bsc",
            "baseToken": {"symbol": "BNB"},
            "priceUsd": "1",
            "volume": {"m5": "0"},
            "liquidity": {"usd": "0"},
            "txns": {"m5": {"buys": 0, "sells": 0}},
        }

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )
    monkeypatch.setattr(strategy, "_fetch_pair_by_symbol", fake_fetch_by_symbol, raising=True)

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "no_valid_rows"


def test_invalid_pair_created_at_is_rejected(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        return "BNB", {
            "chainId": "bsc",
            "baseToken": {"symbol": "BNB"},
            "priceUsd": "1.1",
            "volume": {"m5": "1000"},
            "liquidity": {"usd": "500000"},
            "txns": {"m5": {"buys": 20, "sells": 10}},
            "pairCreatedAt": "not_a_timestamp",
            "dexId": "pancakeswap",
            "pairAddress": "0xpair",
            "url": "https://dexscreener.com/bsc/pair",
        }

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )
    monkeypatch.setattr(strategy, "_fetch_pair_by_symbol", fake_fetch_by_symbol, raising=True)

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "no_valid_rows"


def test_symbol_task_failure_isolated(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_min_success_ratio = 0.5
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB", "CAKE"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        symbol = kwargs["symbol"]
        if symbol == "BNB":
            raise RuntimeError("upstream decode failure")
        return "CAKE", {
            "chainId": "bsc",
            "baseToken": {"symbol": "CAKE"},
            "priceUsd": "2.1",
            "volume": {"m5": "80000"},
            "liquidity": {"usd": "700000"},
            "txns": {"m5": {"buys": 120, "sells": 60}},
            "pairCreatedAt": 1700000000000,
            "dexId": "pancakeswap",
            "pairAddress": "0xpair",
            "url": "https://dexscreener.com/bsc/pair",
        }

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )
    monkeypatch.setattr(strategy, "_fetch_pair_by_symbol", fake_fetch_by_symbol, raising=True)

    rows = asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert len(rows) == 1
    assert rows[0].token_id == "bsc_cake"


def test_retry_after_header_is_used(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy._cache_ttl_seconds = 0
    calls = {"count": 0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def fake_get(self, url, *args, **kwargs):  # noqa: ANN001
        calls["count"] += 1
        request = httpx.Request("GET", url)
        if calls["count"] == 1:
            return httpx.Response(
                status_code=429,
                request=request,
                headers={"Retry-After": "1.5"},
                json={"pairs": []},
            )
        return httpx.Response(status_code=200, request=request, json={"pairs": []})

    monkeypatch.setattr(asyncio, "sleep", fake_sleep, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get, raising=True)

    async def _run() -> dict | None:
        client = await strategy._get_http_client()
        return await strategy._request_json(
            client=client,
            url="https://api.dexscreener.com/latest/dex/search?q=BNB",
            endpoint="search",
            trace_id="trace-test",
            trace="symbol:BNB",
        )

    payload = asyncio.run(_run())
    assert payload is not None
    assert calls["count"] >= 2
    assert sleeps
    assert sleeps[0] == pytest.approx(1.5, rel=0.01)


def test_invalid_numeric_pair_skipped_without_batch_failure(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_min_success_ratio = 0.5
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB", "CAKE"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        symbol = kwargs["symbol"]
        if symbol == "BNB":
            return "BNB", {
                "chainId": "bsc",
                "baseToken": {"symbol": "BNB"},
                "priceUsd": "bad_price",
                "volume": {"m5": "125000"},
                "liquidity": {"usd": "2500000"},
                "txns": {"m5": {"buys": 200, "sells": 120}},
                "pairCreatedAt": 1700000000000,
                "dexId": "pancakeswap",
                "pairAddress": "0xpair1",
                "url": "https://dexscreener.com/bsc/pair1",
            }
        return "CAKE", {
            "chainId": "bsc",
            "baseToken": {"symbol": "CAKE"},
            "priceUsd": "2.1",
            "volume": {"m5": "80000"},
            "liquidity": {"usd": "700000"},
            "txns": {"m5": {"buys": 120, "sells": 60}},
            "pairCreatedAt": 1700000000000,
            "dexId": "pancakeswap",
            "pairAddress": "0xpair2",
            "url": "https://dexscreener.com/bsc/pair2",
        }

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )
    monkeypatch.setattr(strategy, "_fetch_pair_by_symbol", fake_fetch_by_symbol, raising=True)

    rows = asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert len(rows) == 1
    assert rows[0].token_id == "bsc_cake"


def test_production_requires_address_mapping(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.app_env = "prod"
    strategy.settings.market_data_require_address_mapping_in_production = True
    strategy.settings.market_data_required_address_symbols_by_chain = "bsc=BNB"
    strategy.settings.bsc_token_addresses = ""
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "required_mapping_missing"


def test_production_requires_all_symbols_when_toggle_enabled(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.app_env = "prod"
    strategy.settings.market_data_require_address_mapping_in_production = True
    strategy.settings.market_data_required_address_symbols_by_chain = ""
    strategy.settings.bsc_token_addresses = "BNB=0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB", "CAKE"], raising=True)

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "required_mapping_missing"
    assert "CAKE" in exc.value.detail


def test_invalid_price_filtered(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_require_address_mapping_in_production = False
    strategy.settings.market_data_min_success_ratio = 0.5
    strategy.settings.market_data_required_address_symbols_by_chain = ""
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB", "CAKE"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        symbol = kwargs["symbol"]
        if symbol == "BNB":
            return "BNB", {
                "chainId": "bsc",
                "baseToken": {"symbol": "BNB"},
                "priceUsd": "0",
                "volume": {"m5": "125000"},
                "liquidity": {"usd": "2500000"},
                "txns": {"m5": {"buys": 200, "sells": 120}},
                "pairCreatedAt": 1700000000000,
                "dexId": "pancakeswap",
                "pairAddress": "0xpair1",
                "url": "https://dexscreener.com/bsc/pair1",
            }
        return "CAKE", {
            "chainId": "bsc",
            "baseToken": {"symbol": "CAKE"},
            "priceUsd": "2.1",
            "volume": {"m5": "80000"},
            "liquidity": {"usd": "700000"},
            "txns": {"m5": {"buys": 120, "sells": 60}},
            "pairCreatedAt": 1700000000000,
            "dexId": "pancakeswap",
            "pairAddress": "0xpair2",
            "url": "https://dexscreener.com/bsc/pair2",
        }

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )
    monkeypatch.setattr(strategy, "_fetch_pair_by_symbol", fake_fetch_by_symbol, raising=True)

    rows = asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert len(rows) == 1
    assert rows[0].token_id == "bsc_cake"


def test_retry_after_http_date_is_used() -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    retry_at = datetime.now(tz=UTC) + timedelta(seconds=2)
    response = httpx.Response(
        status_code=429,
        request=httpx.Request("GET", "https://api.dexscreener.com/latest/dex/search?q=BNB"),
        headers={"Retry-After": retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")},
    )
    value = strategy._retry_after_seconds(response=response)
    assert value is not None
    assert 0.0 < value <= 3.0


def test_cache_respects_max_entries() -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy._cache_ttl_seconds = 60.0
    strategy._cache_max_entries = 1
    asyncio.run(strategy._cache_set(url="https://example.com/a", payload={"ok": 1}))
    asyncio.run(strategy._cache_set(url="https://example.com/b", payload={"ok": 2}))
    assert len(strategy._response_cache) == 1
    assert "https://example.com/a" not in strategy._response_cache
    assert "https://example.com/b" in strategy._response_cache


def test_endpoint_circuit_breaker_isolated() -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_circuit_failure_threshold = 1
    strategy.settings.market_data_circuit_recovery_seconds = 60.0
    search_breaker = asyncio.run(strategy._breaker_for_endpoint(endpoint="search"))
    tokens_breaker = asyncio.run(strategy._breaker_for_endpoint(endpoint="tokens"))
    assert search_breaker is not tokens_breaker

    asyncio.run(search_breaker.record_failure())
    assert asyncio.run(search_breaker.allow_request()) is False
    assert asyncio.run(tokens_breaker.allow_request()) is True


def test_retry_after_is_capped_by_max_sleep_seconds(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_retry_max_sleep_seconds = 2.0
    strategy._cache_ttl_seconds = 0
    calls = {"count": 0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def fake_get(self, url, *args, **kwargs):  # noqa: ANN001
        calls["count"] += 1
        request = httpx.Request("GET", url)
        if calls["count"] == 1:
            return httpx.Response(
                status_code=429,
                request=request,
                headers={"Retry-After": "600"},
                json={"pairs": []},
            )
        return httpx.Response(status_code=200, request=request, json={"pairs": []})

    monkeypatch.setattr(asyncio, "sleep", fake_sleep, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get, raising=True)

    async def _run() -> dict | None:
        client = await strategy._get_http_client()
        return await strategy._request_json(
            client=client,
            url="https://api.dexscreener.com/latest/dex/search?q=BNB",
            endpoint="search",
            trace_id="trace-test",
            trace="symbol:BNB",
        )

    payload = asyncio.run(_run())
    assert payload is not None
    assert sleeps
    assert sleeps[0] == pytest.approx(2.0, rel=0.01)


def test_required_symbol_invalid_when_row_filtered(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_min_success_ratio = 1.0
    strategy.settings.market_data_required_address_symbols_by_chain = "bsc=BNB"
    strategy.settings.bsc_token_addresses = "BNB=0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {
            "BNB": {
                "chainId": "bsc",
                "baseToken": {
                    "symbol": "BNB",
                    "address": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
                },
                "priceUsd": "0",
                "volume": {"m5": "100000"},
                "liquidity": {"usd": "1500000"},
                "txns": {"m5": {"buys": 200, "sells": 100}},
                "pairCreatedAt": 1700000000000,
                "dexId": "pancakeswap",
                "pairAddress": "0xpair1",
                "url": "https://dexscreener.com/bsc/pair1",
            }
        }

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )

    with pytest.raises(IngestionFetchError) as exc:
        asyncio.run(strategy.fetch_market_ticks(datetime(2026, 4, 18, 12, 30, tzinfo=UTC)))
    assert exc.value.reason == "required_symbol_invalid"
    assert "BNB" in exc.value.detail


def test_address_chunk_fetch_runs_concurrently(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_max_concurrency = 8
    address_map = {f"T{i}": f"0x{i:040x}" for i in range(45)}
    in_flight = {"current": 0, "max_seen": 0}

    async def fake_request_json(*args, **kwargs):  # noqa: ANN002, ANN003
        in_flight["current"] += 1
        in_flight["max_seen"] = max(in_flight["max_seen"], in_flight["current"])
        await asyncio.sleep(0.01)
        in_flight["current"] -= 1
        return {"pairs": []}

    monkeypatch.setattr(strategy, "_request_json", fake_request_json, raising=True)

    async def _run() -> dict[str, dict]:
        client = await strategy._get_http_client()
        return await strategy._fetch_pairs_by_addresses(
            client=client,
            ds_chain_id="bsc",
            symbol_to_address=address_map,
            trace_id="trace-test",
        )

    rows = asyncio.run(_run())
    assert rows == {}
    assert in_flight["max_seen"] > 1


def test_async_context_manager_closes_resources() -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")

    class _Closable:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    async def _run() -> tuple[bool, bool]:
        redis_client = _Closable()
        strategy._redis_client = redis_client
        async with strategy:
            client = await strategy._get_http_client()
            assert client is not None
        return strategy._http_client is None, redis_client.closed

    http_closed, redis_closed = asyncio.run(_run())
    assert http_closed is True
    assert redis_closed is True
