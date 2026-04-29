from __future__ import annotations

from threading import Lock
from time import monotonic


class AsyncCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(0.5, float(recovery_seconds))
        self.half_open_max_calls = max(1, int(half_open_max_calls))
        self._state = "closed"
        self._failure_count = 0
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._lock = Lock()

    async def allow_request(self) -> bool:
        with self._lock:
            now = monotonic()
            if self._state == "open":
                if now - self._opened_at >= self.recovery_seconds:
                    self._state = "half_open"
                    self._half_open_calls = 0
                else:
                    return False
            if self._state == "half_open":
                if self._half_open_calls >= self.half_open_max_calls:
                    return False
                self._half_open_calls += 1
                return True
            return True

    async def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state in {"open", "half_open"}:
                self._state = "closed"
                self._half_open_calls = 0

    async def record_failure(self) -> None:
        with self._lock:
            if self._state == "half_open":
                self._state = "open"
                self._opened_at = monotonic()
                self._failure_count = 0
                self._half_open_calls = 0
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = "open"
                self._opened_at = monotonic()
                self._failure_count = 0

    async def state(self) -> str:
        with self._lock:
            return self._state

    async def remaining_open_seconds(self) -> float:
        with self._lock:
            if self._state != "open":
                return 0.0
            elapsed = monotonic() - self._opened_at
            return max(0.0, self.recovery_seconds - elapsed)


class CircuitBreakerRegistry:
    _lock = Lock()
    _breakers: dict[tuple[str], AsyncCircuitBreaker] = {}

    @classmethod
    def get_breaker(
        cls,
        name: str,
        failure_threshold: int,
        recovery_seconds: float,
        half_open_max_calls: int,
    ) -> AsyncCircuitBreaker:
        key = (name.strip().lower(),)
        normalized_threshold = max(1, int(failure_threshold))
        normalized_recovery = max(0.5, float(recovery_seconds))
        normalized_half_open = max(1, int(half_open_max_calls))
        with cls._lock:
            breaker = cls._breakers.get(key)
            if breaker is None:
                breaker = AsyncCircuitBreaker(
                    failure_threshold=normalized_threshold,
                    recovery_seconds=normalized_recovery,
                    half_open_max_calls=normalized_half_open,
                )
                cls._breakers[key] = breaker
                return breaker
            if (
                breaker.failure_threshold != normalized_threshold
                or abs(breaker.recovery_seconds - normalized_recovery) > 1e-9
                or breaker.half_open_max_calls != normalized_half_open
            ):
                breaker = AsyncCircuitBreaker(
                    failure_threshold=normalized_threshold,
                    recovery_seconds=normalized_recovery,
                    half_open_max_calls=normalized_half_open,
                )
                cls._breakers[key] = breaker
            return breaker
