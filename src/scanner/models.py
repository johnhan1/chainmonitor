from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class TrendingToken(BaseModel):
    address: str
    symbol: str
    name: str
    price_usd: float
    volume_1m: float | None = None
    volume_1h: float | None = None
    market_cap: float | None = None
    liquidity: float | None = None
    smart_degen_count: int | None = None
    rank: int
    chain: str
    also_in_1h: bool = False


class Snapshot(BaseModel):
    chain: str
    interval: str
    tokens: list[TrendingToken]
    taken_at: datetime


class AnomalyType(str, Enum):
    NEW = "new"
    SURGE = "surge"
    SPIKE = "spike"


class AnomalyEvent(BaseModel):
    type: AnomalyType
    token: TrendingToken
    chain: str
    previous_rank: int | None = None
    rank_change: int | None = None
    reason: str


class TokenRisk(BaseModel):
    rug_risk: float = 0.0
    is_honeypot: bool = False
    bundler_ratio: float = 0.0
    rat_ratio: float = 0.0
    sniper_count: int = 0
    top10_holder_pct: float = 0.0


class FilterResult(BaseModel):
    passed: bool = True
    reason: str = ""


class ScoredToken(BaseModel):
    token: TrendingToken
    score: int = 0
    breakdown: dict[str, int] = {}
    risk: TokenRisk | None = None
    passed_filters: bool = True
    filter_reason: str = ""


class AlphaSignal(BaseModel):
    token: ScoredToken
    level: str
    chain: str
    interval: str
    detected_at: datetime
