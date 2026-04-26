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
