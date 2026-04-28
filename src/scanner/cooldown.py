from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime


class CooldownManager:
    def __init__(
        self,
        cooldown_high_seconds: int = 900,
        cooldown_medium_seconds: int = 1800,
        cooldown_observe_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._cooldown: dict[str, float] = {}
        self._hit_counts: dict[str, int] = {}
        self._cooldown_high_seconds = cooldown_high_seconds
        self._cooldown_medium_seconds = cooldown_medium_seconds
        self._cooldown_observe_seconds = cooldown_observe_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def is_cooling(self, address: str) -> bool:
        expires = self._cooldown.get(address, 0.0)
        return expires > self._clock().timestamp()

    def decay_factor(self, address: str) -> float:
        hits = self._hit_counts.get(address, 0)
        if hits >= 3:
            return 0.3
        if hits == 2:
            return 0.6
        return 1.0

    def mark(self, address: str, level: str) -> None:
        if level == "HIGH":
            seconds = self._cooldown_high_seconds
        elif level == "OBSERVE":
            seconds = self._cooldown_observe_seconds
        else:
            seconds = self._cooldown_medium_seconds
        self._cooldown[address] = self._clock().timestamp() + seconds
        self._hit_counts[address] = self._hit_counts.get(address, 0) + 1

    @property
    def pool_size(self) -> int:
        now = self._clock().timestamp()
        return sum(1 for exp in self._cooldown.values() if exp > now)
