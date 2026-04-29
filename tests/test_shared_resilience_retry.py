from __future__ import annotations

from src.shared.resilience.retry import retry_sleep_seconds


def test_retry_sleep_increases_with_attempt() -> None:
    t1 = retry_sleep_seconds(attempt=1, base_seconds=1.0, max_seconds=60.0)
    t2 = retry_sleep_seconds(attempt=2, base_seconds=1.0, max_seconds=60.0)
    assert t2 > t1


def test_retry_sleep_capped_by_max() -> None:
    t = retry_sleep_seconds(attempt=10, base_seconds=10.0, max_seconds=15.0)
    assert t <= 15.0


def test_retry_sleep_includes_jitter() -> None:
    values = {retry_sleep_seconds(attempt=1, base_seconds=5.0, max_seconds=60.0) for _ in range(20)}
    assert len(values) > 1  # jitter produces variation
