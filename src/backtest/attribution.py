from __future__ import annotations

from collections import defaultdict
from datetime import UTC

from src.shared.schemas.backtest import AttributionBucket, AttributionReport, BacktestTradeResult


class BacktestAttribution:
    def build(self, trades: list[BacktestTradeResult]) -> AttributionReport:
        return AttributionReport(
            by_token=self._aggregate(
                keys=[trade.token_id for trade in trades],
                trades=trades,
            ),
            by_hour=self._aggregate(
                keys=[trade.ts_minute.astimezone(UTC).strftime("%H:00") for trade in trades],
                trades=trades,
            ),
            by_regime=self._aggregate(
                keys=[self._regime_key(trade.conviction) for trade in trades],
                trades=trades,
            ),
        )

    @staticmethod
    def _aggregate(keys: list[str], trades: list[BacktestTradeResult]) -> list[AttributionBucket]:
        groups: dict[str, list[BacktestTradeResult]] = defaultdict(list)
        for key, trade in zip(keys, trades, strict=False):
            groups[key].append(trade)

        rows: list[AttributionBucket] = []
        for key, items in groups.items():
            net_pnl = sum(item.net_pnl_usd for item in items)
            wins = sum(1 for item in items if item.net_pnl_usd > 0)
            rows.append(
                AttributionBucket(
                    key=key,
                    trade_count=len(items),
                    net_pnl_usd=round(net_pnl, 8),
                    win_rate=round(wins / len(items), 8) if items else 0.0,
                )
            )
        rows.sort(key=lambda row: row.net_pnl_usd, reverse=True)
        return rows

    @staticmethod
    def _regime_key(conviction: float) -> str:
        if conviction >= 85:
            return "risk_on"
        if conviction >= 70:
            return "neutral"
        return "risk_off"
