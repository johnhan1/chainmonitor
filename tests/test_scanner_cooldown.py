from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.scanner.cooldown import CooldownManager


def test_is_cooling_returns_true_within_cooldown() -> None:
    now = datetime.now(UTC)
    cm = CooldownManager(cooldown_high_seconds=900, clock=lambda: now)
    cm.mark("0xabc", "HIGH")
    assert cm.is_cooling("0xabc") is True


def test_is_cooling_returns_false_after_expiry() -> None:
    now = datetime.now(UTC)
    cm = CooldownManager(cooldown_high_seconds=900, clock=lambda: now)
    cm.mark("0xabc", "HIGH")
    cm._clock = lambda: now + timedelta(seconds=901)
    assert cm.is_cooling("0xabc") is False


def test_mark_respects_level_duration() -> None:
    now = datetime.now(UTC)
    cm = CooldownManager(
        cooldown_high_seconds=900,
        cooldown_medium_seconds=300,
        cooldown_observe_seconds=60,
        clock=lambda: now,
    )
    cm.mark("0xhigh", "HIGH")
    cm.mark("0xmed", "MEDIUM")
    cm.mark("0xobs", "OBSERVE")
    cm._clock = lambda: now + timedelta(seconds=400)
    assert cm.is_cooling("0xhigh") is True
    assert cm.is_cooling("0xmed") is False
    assert cm.is_cooling("0xobs") is False


def test_pool_size() -> None:
    now = datetime.now(UTC)
    cm = CooldownManager(cooldown_high_seconds=900, clock=lambda: now)
    cm.mark("0xa", "HIGH")
    cm.mark("0xb", "HIGH")
    assert cm.pool_size == 2
    cm._clock = lambda: now + timedelta(seconds=901)
    assert cm.pool_size == 0


def test_decay_factor_first_hit() -> None:
    cm = CooldownManager()
    cm.mark("0xa", "HIGH")
    assert cm.decay_factor("0xa") == 1.0


def test_decay_factor_second_hit() -> None:
    cm = CooldownManager()
    cm.mark("0xa", "HIGH")
    cm._clock = lambda: datetime.now(UTC) + timedelta(hours=1)
    cm.mark("0xa", "HIGH")
    assert cm.decay_factor("0xa") == 0.6


def test_decay_factor_third_hit() -> None:
    cm = CooldownManager()
    cm.mark("0xa", "HIGH")
    cm._clock = lambda: datetime.now(UTC) + timedelta(hours=1)
    cm.mark("0xa", "HIGH")
    cm._clock = lambda: datetime.now(UTC) + timedelta(hours=2)
    cm.mark("0xa", "HIGH")
    assert cm.decay_factor("0xa") == 0.3
