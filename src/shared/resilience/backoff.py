from __future__ import annotations

from threading import Lock


class BackoffGuard:
    def __init__(self) -> None:
        self._lock = Lock()
        self._failure_streak = 0
        self._opened_until = 0.0

    def allow_request(self, now: float) -> bool:
        with self._lock:
            return now >= self._opened_until

    def remaining_blocked_seconds(self, now: float) -> float:
        with self._lock:
            return max(0.0, self._opened_until - now)

    def record_failure(
        self,
        now: float,
        base_seconds: float,
        max_seconds: float,
    ) -> None:
        with self._lock:
            self._failure_streak += 1
            multiplier = min(8, max(1, self._failure_streak))
            cooldown = min(max_seconds, max(0.1, base_seconds) * multiplier)
            self._opened_until = max(self._opened_until, now + cooldown)

    def record_success(self) -> None:
        with self._lock:
            self._failure_streak = 0
            self._opened_until = 0.0


class BackoffRegistry:
    _lock = Lock()
    _guards: dict[str, BackoffGuard] = {}

    @classmethod
    def get_guard(cls, name: str) -> BackoffGuard:
        key = name.strip().lower()
        with cls._lock:
            guard = cls._guards.get(key)
            if guard is None:
                guard = BackoffGuard()
                cls._guards[key] = guard
            return guard
