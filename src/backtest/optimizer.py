from __future__ import annotations

from itertools import product

from src.backtest.engine import BacktestEngine
from src.shared.schemas.backtest import BacktestConfig, ParameterSearchReport, SearchCandidate


class BacktestParameterOptimizer:
    def __init__(self, engine: BacktestEngine) -> None:
        self.engine = engine

    async def grid_search(self, config: BacktestConfig) -> ParameterSearchReport:
        candidates: list[SearchCandidate] = []
        thresholds = [
            max(55.0, config.conviction_threshold - 5),
            config.conviction_threshold,
            min(90.0, config.conviction_threshold + 5),
        ]
        stop_losses = [max(0.02, config.stop_loss_pct - 0.02), config.stop_loss_pct]
        take_profits = [config.take_profit_pct, min(0.20, config.take_profit_pct + 0.03)]
        hold_minutes = [max(3, config.hold_minutes - 2), config.hold_minutes]

        for threshold, stop_loss, take_profit, hold in product(
            thresholds,
            stop_losses,
            take_profits,
            hold_minutes,
        ):
            trial_config = config.model_copy(
                update={
                    "conviction_threshold": float(threshold),
                    "stop_loss_pct": float(stop_loss),
                    "take_profit_pct": float(take_profit),
                    "hold_minutes": int(hold),
                }
            )
            _, metrics = await self.engine.run(trial_config)
            candidates.append(
                SearchCandidate(
                    conviction_threshold=float(threshold),
                    stop_loss_pct=float(stop_loss),
                    take_profit_pct=float(take_profit),
                    hold_minutes=int(hold),
                    pf=metrics.pf,
                    expectancy=metrics.expectancy,
                    net_pnl_usd=metrics.net_pnl_usd,
                    passed=metrics.pf > 1.2 and metrics.expectancy > 0,
                )
            )

        candidates.sort(
            key=lambda row: (row.passed, row.pf, row.expectancy, row.net_pnl_usd),
            reverse=True,
        )
        return ParameterSearchReport(
            chain_id=config.chain_id,
            strategy_version=config.strategy_version,
            tested_count=len(candidates),
            best=candidates[0],
            leaderboard=candidates[:10],
        )
