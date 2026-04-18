from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    market_tick = "MarketTick"
    feature_ready = "FeatureReady"
    score_updated = "ScoreUpdated"
    signal_created = "SignalCreated"
    order_placed = "OrderPlaced"
    order_filled = "OrderFilled"
    position_closed = "PositionClosed"
    risk_alert = "RiskAlert"


class EventEnvelope(BaseModel):
    event_id: str
    event_type: EventType
    event_time: datetime
    chain_id: str
    token_id: str
    strategy_version: str
    payload: dict[str, Any] = Field(default_factory=dict)
