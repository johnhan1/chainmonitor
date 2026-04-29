from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrendingFetched:
    chain: str
    interval: str
    token_count: int
    duration_ms: float
    success: bool


@dataclass
class TokenSecurityChecked:
    chain: str
    address: str
    symbol: str
    duration_ms: float
    success: bool


@dataclass
class TokenProcessed:
    chain: str
    interval: str
    scanned_at: datetime
    address: str
    symbol: str
    filter_passed: bool
    filter_reason: str
    score_total: int | None
    score_breakdown: dict[str, int] | None
    signal_emitted: bool
    signal_level: str | None
    cooldown_skipped: bool


@dataclass
class ChainScanCompleted:
    chain: str
    interval: str
    total_duration_ms: float
    token_count: int
    signal_count: int


EventHandler = Callable[[Any], None]

SYSTEM_EVENT_TYPES: list[type] = [
    TrendingFetched,
    TokenSecurityChecked,
    ChainScanCompleted,
]

STRATEGY_EVENT_TYPES: list[type] = [
    TokenProcessed,
]

ALL_EVENT_TYPES: list[type] = SYSTEM_EVENT_TYPES + STRATEGY_EVENT_TYPES


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = {}

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), []):
            try:
                handler(event)
            except Exception:
                logger.exception("EventBus handler failed for %s", type(event).__name__)
