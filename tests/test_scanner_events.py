from __future__ import annotations

from datetime import UTC, datetime

from src.scanner.events import (
    ALL_EVENT_TYPES,
    ChainScanCompleted,
    EventBus,
    TokenProcessed,
    TokenSecurityChecked,
    TrendingFetched,
)


def test_event_bus_publish() -> None:
    bus = EventBus()
    received: list[object] = []

    def handler(event: object) -> None:
        received.append(event)

    bus.subscribe(TrendingFetched, handler)
    event = TrendingFetched(
        chain="sol",
        interval="1m",
        token_count=50,
        duration_ms=100.0,
        success=True,
    )
    bus.publish(event)
    assert received == [event]


def test_event_bus_unrelated_type_not_dispatched() -> None:
    bus = EventBus()
    received: list[object] = []

    def handler(event: object) -> None:
        received.append(event)

    bus.subscribe(TokenProcessed, handler)
    bus.publish(
        TrendingFetched(
            chain="sol",
            interval="1m",
            token_count=50,
            duration_ms=100.0,
            success=True,
        )
    )
    assert received == []


def test_event_bus_handler_exception_isolation() -> None:
    bus = EventBus()
    received: list[object] = []

    def failing_handler(event: object) -> None:
        raise ValueError("oops")

    def good_handler(event: object) -> None:
        received.append(event)

    bus.subscribe(TrendingFetched, failing_handler)
    bus.subscribe(TrendingFetched, good_handler)
    bus.publish(
        TrendingFetched(
            chain="sol",
            interval="1m",
            token_count=50,
            duration_ms=100.0,
            success=True,
        )
    )
    assert len(received) == 1


def test_event_types_are_dataclasses() -> None:
    now = datetime.now(UTC)
    TrendingFetched(
        chain="sol",
        interval="1m",
        token_count=50,
        duration_ms=100.0,
        success=True,
    )
    TokenSecurityChecked(
        chain="sol",
        address="0x1",
        symbol="A",
        duration_ms=50.0,
        success=True,
    )
    TokenProcessed(
        chain="sol",
        interval="1m",
        scanned_at=now,
        address="0x1",
        symbol="A",
        filter_passed=True,
        filter_reason="",
        score_total=80,
        score_breakdown={"smart_money": 30},
        signal_emitted=True,
        signal_level="HIGH",
        cooldown_skipped=False,
    )
    ChainScanCompleted(
        chain="sol",
        interval="1m",
        total_duration_ms=5000.0,
        token_count=50,
        signal_count=3,
    )
    assert ALL_EVENT_TYPES


def test_token_processed_defaults() -> None:
    now = datetime.now(UTC)
    tp = TokenProcessed(
        chain="sol",
        interval="1m",
        scanned_at=now,
        address="0x1",
        symbol="A",
        filter_passed=False,
        filter_reason="liquidity",
        score_total=None,
        score_breakdown=None,
        signal_emitted=False,
        signal_level=None,
        cooldown_skipped=False,
    )
    assert tp.filter_passed is False
    assert tp.score_total is None
    assert tp.signal_emitted is False
