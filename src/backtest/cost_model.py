from __future__ import annotations

from dataclasses import dataclass

from src.shared.schemas.backtest import BacktestConfig, CostBreakdown


@dataclass
class TradeCost:
    fee_usd: float
    slippage_usd: float
    latency_usd: float
    gas_usd: float

    @property
    def total(self) -> float:
        return self.fee_usd + self.slippage_usd + self.latency_usd + self.gas_usd


class TradeCostModel:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def estimate(self, notional_usd: float) -> TradeCost:
        fee = notional_usd * (self.config.fee_bps / 10_000)
        slippage = notional_usd * (self.config.slippage_bps / 10_000)
        latency = notional_usd * (self.config.latency_bps / 10_000)
        return TradeCost(
            fee_usd=round(fee, 8),
            slippage_usd=round(slippage, 8),
            latency_usd=round(latency, 8),
            gas_usd=round(self.config.gas_usd_per_trade, 8),
        )

    @staticmethod
    def summarize(costs: list[TradeCost]) -> CostBreakdown:
        total_fee = sum(item.fee_usd for item in costs)
        total_slippage = sum(item.slippage_usd for item in costs)
        total_latency = sum(item.latency_usd for item in costs)
        total_gas = sum(item.gas_usd for item in costs)
        total_cost = total_fee + total_slippage + total_latency + total_gas
        return CostBreakdown(
            total_fee_usd=round(total_fee, 8),
            total_slippage_usd=round(total_slippage, 8),
            total_latency_usd=round(total_latency, 8),
            total_gas_usd=round(total_gas, 8),
            total_cost_usd=round(total_cost, 8),
        )
