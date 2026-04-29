from __future__ import annotations

from time import monotonic

from src.shared.resilience.backoff import BackoffGuard, BackoffRegistry


class TestBackoffGuard:
    def test_allows_initial_request(self) -> None:
        guard = BackoffGuard()
        assert guard.allow_request(monotonic()) is True

    def test_blocks_after_failure(self) -> None:
        guard = BackoffGuard()
        now = monotonic()
        guard.record_failure(now=now, base_seconds=60.0, max_seconds=300.0)
        assert guard.allow_request(now + 1.0) is False

    def test_recovers_after_timeout(self) -> None:
        guard = BackoffGuard()
        now = monotonic()
        guard.record_failure(now=now, base_seconds=0.01, max_seconds=0.02)
        assert guard.allow_request(now + 0.03) is True

    def test_resets_on_success(self) -> None:
        guard = BackoffGuard()
        now = monotonic()
        guard.record_failure(now=now, base_seconds=60.0, max_seconds=300.0)
        guard.record_success()
        assert guard.allow_request(now + 1.0) is True

    def test_increases_backoff_on_consecutive_failures(self) -> None:
        guard = BackoffGuard()
        now = monotonic()
        guard.record_failure(now=now, base_seconds=1.0, max_seconds=100.0)
        t1 = guard.remaining_blocked_seconds(now)
        guard.record_failure(now=now, base_seconds=1.0, max_seconds=100.0)
        t2 = guard.remaining_blocked_seconds(now)
        assert t2 > t1

    def test_remaining_blocked_seconds_zero_when_not_blocked(self) -> None:
        guard = BackoffGuard()
        assert guard.remaining_blocked_seconds(monotonic()) == 0.0


class TestBackoffRegistry:
    def test_singleton(self) -> None:
        g1 = BackoffRegistry.get_guard(name="test")
        g2 = BackoffRegistry.get_guard(name="test")
        assert g1 is g2

    def test_different_names(self) -> None:
        g1 = BackoffRegistry.get_guard(name="alpha")
        g2 = BackoffRegistry.get_guard(name="beta")
        assert g1 is not g2

    def test_case_insensitive(self) -> None:
        g1 = BackoffRegistry.get_guard(name="TestName")
        g2 = BackoffRegistry.get_guard(name="testname")
        assert g1 is g2
