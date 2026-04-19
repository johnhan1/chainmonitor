from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BacktestConfig(BaseModel):
    chain_id: str
    strategy_version: str
    period_start: datetime
    period_end: datetime
    conviction_threshold: float = 70.0
    hold_minutes: int = 5
    stop_loss_pct: float = 0.06
    take_profit_pct: float = 0.12
    trade_size_usd: float = 1_000.0
    fee_bps: float = 20.0
    slippage_bps: float = 30.0
    gas_usd_per_trade: float = 1.5
    latency_bps: float = 5.0
    fail_probability: float = 0.01


class CostBreakdown(BaseModel):
    total_fee_usd: float = 0.0
    total_slippage_usd: float = 0.0
    total_latency_usd: float = 0.0
    total_gas_usd: float = 0.0
    total_cost_usd: float = 0.0


class BacktestTradeResult(BaseModel):
    chain_id: str
    token_id: str
    ts_minute: datetime
    conviction: float
    expected_return_pct: float
    gross_pnl_usd: float
    cost_usd: float
    net_pnl_usd: float
    failed: bool = False


class BacktestMetrics(BaseModel):
    trade_count: int
    win_count: int
    lose_count: int
    win_rate: float
    net_pnl_usd: float
    gross_profit_usd: float
    gross_loss_usd: float
    pf: float
    expectancy: float
    max_dd_pct: float
    cost_breakdown: CostBreakdown


class WalkForwardReport(BaseModel):
    window_count: int
    pf_values: list[float] = Field(default_factory=list)
    expectancy_values: list[float] = Field(default_factory=list)
    parameter_stability_score: float
    passed: bool


class Gate2CheckResult(BaseModel):
    reproducibility_passed: bool
    cost_consistency_passed: bool
    anti_overfitting_passed: bool
    strategy_threshold_passed: bool
    reproducibility_diff: float
    walk_forward: WalkForwardReport
    metrics: BacktestMetrics
    passed: bool


class BacktestRunReport(BaseModel):
    run_id: str
    chain_id: str
    strategy_version: str
    period_start: datetime
    period_end: datetime
    status: str
    metrics: BacktestMetrics
    gate2: Gate2CheckResult | None = None


class SearchCandidate(BaseModel):
    conviction_threshold: float
    stop_loss_pct: float
    take_profit_pct: float
    hold_minutes: int
    pf: float
    expectancy: float
    net_pnl_usd: float
    passed: bool


class ParameterSearchReport(BaseModel):
    chain_id: str
    strategy_version: str
    tested_count: int
    best: SearchCandidate
    leaderboard: list[SearchCandidate] = Field(default_factory=list)


class AttributionBucket(BaseModel):
    key: str
    trade_count: int
    net_pnl_usd: float
    win_rate: float


class AttributionReport(BaseModel):
    by_token: list[AttributionBucket] = Field(default_factory=list)
    by_hour: list[AttributionBucket] = Field(default_factory=list)
    by_regime: list[AttributionBucket] = Field(default_factory=list)


class BatchBacktestItem(BaseModel):
    item_id: str
    chain_id: str
    status: str
    result: BacktestRunReport | None = None
    error: str | None = None


class BatchBacktestJobReport(BaseModel):
    job_id: str
    chain_id: str
    status: str
    total: int
    succeeded: int
    failed: int
    items: list[BatchBacktestItem] = Field(default_factory=list)
