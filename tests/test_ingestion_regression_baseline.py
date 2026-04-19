import asyncio
from datetime import UTC, datetime

from src.ingestion.strategies.dexscreener_source_strategy import DexScreenerSourceStrategy


def test_dexscreener_tick_mapping_regression_baseline(monkeypatch) -> None:
    strategy = DexScreenerSourceStrategy(chain_id="bsc", data_mode="live")
    strategy.settings.market_data_require_address_mapping_in_production = False
    strategy.settings.market_data_required_address_symbols_by_chain = ""
    ts = datetime(2026, 4, 18, 12, 30, 33, 456789, tzinfo=UTC)
    monkeypatch.setattr(strategy, "_symbols", lambda: ["BNB"], raising=True)

    pair = {
        "chainId": "bsc",
        "baseToken": {"symbol": "BNB", "address": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"},
        "priceUsd": "602.123",
        "volume": {"m5": "125000"},
        "liquidity": {"usd": "2500000"},
        "txns": {"m5": {"buys": 200, "sells": 120}},
        "pairCreatedAt": 1700000000000,
        "dexId": "pancakeswap",
        "pairAddress": "0xpair",
        "url": "https://dexscreener.com/bsc/pair",
    }

    async def fake_fetch_by_addresses(*args, **kwargs):  # noqa: ANN002, ANN003
        return {}

    async def fake_fetch_by_symbol(*args, **kwargs):  # noqa: ANN002, ANN003
        return "BNB", pair

    monkeypatch.setattr(
        strategy, "_fetch_pairs_by_addresses", fake_fetch_by_addresses, raising=True
    )
    monkeypatch.setattr(strategy, "_fetch_pair_by_symbol", fake_fetch_by_symbol, raising=True)

    rows = asyncio.run(strategy.fetch_market_ticks(ts_minute=ts))
    assert len(rows) == 1
    baseline = rows[0].model_dump()
    assert baseline["chain_id"] == "bsc"
    assert baseline["token_id"] == "bsc_bnb"
    assert baseline["price_usd"] == 602.123
    assert baseline["volume_1m"] == 25000.0
    assert baseline["volume_5m"] == 125000.0
    assert baseline["liquidity_usd"] == 2500000.0
    assert baseline["buys_1m"] == 40
    assert baseline["sells_1m"] == 24
    assert baseline["tx_count_1m"] == 64
    assert baseline["ts_minute"] == datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
