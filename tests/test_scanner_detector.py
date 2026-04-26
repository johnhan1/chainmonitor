from __future__ import annotations

from datetime import UTC, datetime

from src.scanner.detector import Detector
from src.scanner.models import AnomalyType, Snapshot, TrendingToken


def _token(
    address: str,
    symbol: str,
    rank: int,
    volume_1m: float | None = None,
    smart_degen: int | None = None,
) -> TrendingToken:
    return TrendingToken(
        address=address,
        symbol=symbol,
        name=symbol,
        price_usd=0.1,
        rank=rank,
        chain="sol",
        volume_1m=volume_1m,
        smart_degen_count=smart_degen,
    )


def _snapshot(tokens: list[TrendingToken]) -> Snapshot:
    return Snapshot(chain="sol", interval="1m", tokens=tokens, taken_at=datetime.now(UTC))


def test_detect_new_token() -> None:
    prev = _snapshot([_token("0xold", "OLD", 1)])
    curr = _snapshot([_token("0xold", "OLD", 1), _token("0xnew", "NEW", 2)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    assert len(events) == 1
    assert events[0].type == AnomalyType.NEW
    assert events[0].token.address == "0xnew"


def test_detect_surge() -> None:
    prev = _snapshot([_token("0xa", "A", 15), _token("0xb", "B", 1)])
    curr = _snapshot([_token("0xa", "A", 1), _token("0xb", "B", 15)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    assert len(events) == 1
    assert events[0].type == AnomalyType.SURGE
    assert events[0].token.address == "0xa"
    assert events[0].rank_change == 14


def test_detect_spike_volume() -> None:
    prev = _snapshot([_token("0xa", "A", 1, volume_1m=1000.0)])
    curr = _snapshot([_token("0xa", "A", 1, volume_1m=5000.0)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    assert len(events) == 1
    assert events[0].type == AnomalyType.SPIKE
    assert "volume" in events[0].reason.lower()


def test_detect_no_change() -> None:
    prev = _snapshot([_token("0xa", "A", 1)])
    curr = _snapshot([_token("0xa", "A", 1)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    assert events == []


def test_detect_first_snapshot_no_events() -> None:
    curr = _snapshot([_token("0xa", "A", 1)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(None, curr)
    assert events == []
