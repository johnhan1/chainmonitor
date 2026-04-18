from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MarketTickInput(BaseModel):
    chain_id: str
    token_id: str
    ts_minute: datetime
    price_usd: float
    volume_1m: float
    volume_5m: float
    liquidity_usd: float
    buys_1m: int
    sells_1m: int
    tx_count_1m: int


class FeatureRowInput(BaseModel):
    chain_id: str
    token_id: str
    ts_minute: datetime
    netflow_usd_5m: float
    netflow_usd_30m: float
    large_buy_count_30m: int
    new_holder_30m: int
    holder_churn_24h: float
    contract_risk_score: float
    lp_concentration: float
    holder_concentration_top10: float
    wash_trade_score: float
    honeypot_flag: bool


class ScoreRowInput(BaseModel):
    strategy_version: str
    chain_id: str
    token_id: str
    ts_minute: datetime
    alpha_score: float
    momentum_score: float
    smart_money_score: float
    narrative_score: float
    risk_penalty: float
    final_score: float
    conviction: float
    confidence: float
    tier: str
    reason_codes: list[str] = Field(default_factory=list)


class PipelineRunSummary(BaseModel):
    chain_id: str
    strategy_version: str
    ts_minute: datetime
    tick_count: int
    candidate_count: int
    status: str = "success"
    trigger: str = "manual"
    skipped: bool = False
    error_message: str | None = None
