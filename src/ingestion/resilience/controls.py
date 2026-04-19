from __future__ import annotations

import asyncio
from time import monotonic


class AsyncTokenBucket:
    def __init__(self, rate_per_second: float, capacity: int) -> None:
        self.rate_per_second = max(0.01, rate_per_second)
        self.capacity = max(1.0, float(capacity))
        self._tokens = self.capacity
        self._last_refill = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = monotonic()
                elapsed = max(0.0, now - self._last_refill)
                self._last_refill = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_second)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                missing = 1.0 - self._tokens
                wait_seconds = missing / self.rate_per_second
            await asyncio.sleep(max(0.001, wait_seconds))


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
        self._lock = asyncio.Lock()

    async def allow_request(self) -> bool:
        async with self._lock:
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
        async with self._lock:
            self._failure_count = 0
            if self._state in {"open", "half_open"}:
                self._state = "closed"
                self._half_open_calls = 0

    async def record_failure(self) -> None:
        async with self._lock:
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
        async with self._lock:
            return self._state

    async def remaining_open_seconds(self) -> float:
        async with self._lock:
            if self._state != "open":
                return 0.0
            elapsed = monotonic() - self._opened_at
            return max(0.0, self.recovery_seconds - elapsed)
