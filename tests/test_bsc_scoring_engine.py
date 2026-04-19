from datetime import UTC, datetime

from src.scoring.scoring_engine import ScoringEngine
from src.shared.schemas.pipeline import FeatureRowInput, MarketTickInput


def test_bsc_scoring_engine_returns_expected_tier_range() -> None:
    ts = datetime.now(tz=UTC).replace(second=0, microsecond=0)
    tick = MarketTickInput(
        chain_id="bsc",
        token_id="bsc_test",
        ts_minute=ts,
        price_usd=10.0,
        volume_1m=20000.0,
        volume_5m=100000.0,
        liquidity_usd=800000.0,
        buys_1m=120,
        sells_1m=30,
        tx_count_1m=180,
    )
    feature = FeatureRowInput(
        chain_id="bsc",
        token_id="bsc_test",
        ts_minute=ts,
        netflow_usd_5m=5000.0,
        netflow_usd_30m=30000.0,
        large_buy_count_30m=50,
        new_holder_30m=20,
        holder_churn_24h=0.2,
        contract_risk_score=0.1,
        lp_concentration=0.2,
        holder_concentration_top10=0.3,
        wash_trade_score=0.1,
        honeypot_flag=False,
    )

    score = ScoringEngine(strategy_version="bsc-mvp-v1").score([tick], [feature])[0]
    assert 0 <= score.conviction <= 100
    assert score.tier in {"A", "B", "C"}
    assert "liquidity_ok" in score.reason_codes
