import asyncio
from datetime import UTC, datetime, timedelta

from src.backtest.engine import BacktestEngine
from src.backtest.validator import Gate2Validator
from src.shared.config.chain import get_chain_settings
from src.shared.schemas.backtest import BacktestConfig


def _phase2_config() -> BacktestConfig:
    chain_settings = get_chain_settings()
    end = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
    start = end - timedelta(minutes=90)
    return BacktestConfig(
        chain_id=chain_settings.bsc_chain_id,
        strategy_version=chain_settings.get_strategy_version(chain_id=chain_settings.bsc_chain_id),
        period_start=start,
        period_end=end,
        conviction_threshold=60.0,
        trade_size_usd=1_000.0,
        fee_bps=20.0,
        slippage_bps=30.0,
        latency_bps=5.0,
        gas_usd_per_trade=1.5,
        fail_probability=0.01,
    )


def test_phase2_gate2_reproducibility_and_cost_consistency() -> None:
    config = _phase2_config()
    validator = Gate2Validator(engine=BacktestEngine(chain_id=config.chain_id))

    result = asyncio.run(validator.check(config))

    assert result.reproducibility_passed
    assert result.cost_consistency_passed
    assert result.reproducibility_diff == 0.0
    assert result.metrics.cost_breakdown.total_cost_usd > 0


def test_phase2_gate2_walk_forward_and_threshold() -> None:
    config = _phase2_config()
    validator = Gate2Validator(engine=BacktestEngine(chain_id=config.chain_id))

    result = asyncio.run(validator.check(config))

    assert result.anti_overfitting_passed
    assert result.walk_forward.window_count >= 2
    assert result.walk_forward.parameter_stability_score >= 0.6
    assert result.strategy_threshold_passed
    assert result.metrics.pf > 1.2
    assert result.metrics.expectancy > 0
    assert result.passed
