from __future__ import annotations

from datetime import timedelta

from src.backtest.engine import BacktestEngine
from src.shared.schemas.backtest import (
    BacktestConfig,
    Gate2CheckResult,
    WalkForwardReport,
)


class Gate2Validator:
    def __init__(self, engine: BacktestEngine) -> None:
        self.engine = engine

    async def check(self, config: BacktestConfig) -> Gate2CheckResult:
        _, metrics_a = await self.engine.run(config)
        _, metrics_b = await self.engine.run(config)
        reproducibility_diff = abs(metrics_a.net_pnl_usd - metrics_b.net_pnl_usd)
        reproducibility_passed = reproducibility_diff <= 1e-9

        cost = metrics_a.cost_breakdown
        total_cost = (
            cost.total_fee_usd
            + cost.total_slippage_usd
            + cost.total_latency_usd
            + cost.total_gas_usd
        )
        cost_consistency_passed = (
            metrics_a.trade_count == 0
            or abs(total_cost - cost.total_cost_usd) <= 1e-8
            and cost.total_cost_usd > 0
        )

        walk_forward = await self._walk_forward_check(config)
        anti_overfitting_passed = walk_forward.passed

        strategy_threshold_passed = metrics_a.pf > 1.2 and metrics_a.expectancy > 0
        passed = (
            reproducibility_passed
            and cost_consistency_passed
            and anti_overfitting_passed
            and strategy_threshold_passed
        )
        return Gate2CheckResult(
            reproducibility_passed=reproducibility_passed,
            cost_consistency_passed=cost_consistency_passed,
            anti_overfitting_passed=anti_overfitting_passed,
            strategy_threshold_passed=strategy_threshold_passed,
            reproducibility_diff=round(reproducibility_diff, 10),
            walk_forward=walk_forward,
            metrics=metrics_a,
            passed=passed,
        )

    async def _walk_forward_check(self, config: BacktestConfig) -> WalkForwardReport:
        total_span = config.period_end - config.period_start
        if total_span <= timedelta(minutes=2):
            return WalkForwardReport(
                window_count=0,
                pf_values=[],
                expectancy_values=[],
                parameter_stability_score=0.0,
                passed=False,
            )

        split_point = config.period_start + (total_span / 2)
        windows = [
            (config.period_start, split_point),
            (split_point + timedelta(minutes=1), config.period_end),
        ]
        pf_values: list[float] = []
        expectancy_values: list[float] = []
        active_pf_values: list[float] = []
        threshold_variants = [
            config.conviction_threshold,
            min(95.0, config.conviction_threshold + 2.0),
        ]
        for start, end in windows:
            variant_pfs: list[float] = []
            variant_expectancies: list[float] = []
            active_variant_pfs: list[float] = []
            for threshold in threshold_variants:
                cfg = config.model_copy(
                    update={
                        "period_start": start,
                        "period_end": end,
                        "conviction_threshold": threshold,
                    }
                )
                _, metrics = await self.engine.run(cfg)
                variant_pfs.append(metrics.pf)
                variant_expectancies.append(metrics.expectancy)
                if metrics.trade_count > 0:
                    active_variant_pfs.append(metrics.pf)
            pf_values.append(sum(variant_pfs) / len(variant_pfs))
            expectancy_values.append(sum(variant_expectancies) / len(variant_expectancies))
            if active_variant_pfs:
                active_pf_values.append(sum(active_variant_pfs) / len(active_variant_pfs))

        if not active_pf_values:
            stability = 0.0
            passed = False
        else:
            pf_min = min(active_pf_values)
            pf_max = max(active_pf_values)
            if pf_max <= 0:
                stability = 0.0
            else:
                stability = max(0.0, 1.0 - ((pf_max - pf_min) / pf_max))
            passed = all(value > 1.0 for value in active_pf_values) and stability >= 0.4

        if not active_pf_values:
            stability = 0.0
        return WalkForwardReport(
            window_count=len(windows),
            pf_values=[round(v, 8) for v in pf_values],
            expectancy_values=[round(v, 8) for v in expectancy_values],
            parameter_stability_score=round(stability, 8),
            passed=passed,
        )
