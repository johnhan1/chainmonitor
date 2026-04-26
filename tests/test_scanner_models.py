from __future__ import annotations

from datetime import datetime, timezone

from src.scanner.models import AnomalyEvent, AnomalyType, Snapshot, TrendingToken


def test_trending_token_defaults() -> None:
    t = TrendingToken(
        address="0xabc",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        rank=1,
        chain="sol",
    )
    assert t.volume_1m is None
    assert t.smart_degen_count is None
    assert t.market_cap is None


def test_snapshot_roundtrip() -> None:
    t = TrendingToken(
        address="0xabc",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        volume_1m=1000.0,
        rank=1,
        chain="sol",
    )
    snap = Snapshot(
        chain="sol",
        interval="1m",
        tokens=[t],
        taken_at=datetime.now(timezone.utc),  # noqa: UP017
    )
    assert snap.tokens[0].symbol == "TEST"
    assert snap.tokens[0].volume_1m == 1000.0


def test_anomaly_event_defaults() -> None:
    t = TrendingToken(
        address="0xabc",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        rank=1,
        chain="sol",
    )
    e = AnomalyEvent(
        type=AnomalyType.NEW,
        token=t,
        chain="sol",
        previous_rank=None,
        rank_change=None,
        reason="New token appeared",
    )
    assert e.type == AnomalyType.NEW
    assert e.reason == "New token appeared"
