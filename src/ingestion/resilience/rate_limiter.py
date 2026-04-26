from __future__ import annotations

import asyncio
from threading import Lock
from time import monotonic


class AsyncTokenBucket:
    def __init__(self, rate_per_second: float, capacity: int) -> None:
        self.rate_per_second = max(0.01, rate_per_second)
        self.capacity = max(1.0, float(capacity))
        self._tokens = self.capacity
        self._last_refill = monotonic()
        self._lock = Lock()

    async def acquire(self) -> None:
        while True:
            with self._lock:
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


class RateLimiterRegistry:
    _lock = Lock()
    _buckets: dict[tuple[str, str], AsyncTokenBucket] = {}

    @classmethod
    def get_bucket(
        cls,
        provider: str,
        chain_id: str,
        rate_per_second: float,
        capacity: int,
    ) -> AsyncTokenBucket:
        key = (provider.strip().lower(), chain_id.strip().lower())
        normalized_rate = max(0.01, float(rate_per_second))
        normalized_capacity = max(1, int(capacity))
        with cls._lock:
            bucket = cls._buckets.get(key)
            if bucket is None:
                bucket = AsyncTokenBucket(
                    rate_per_second=normalized_rate,
                    capacity=normalized_capacity,
                )
                cls._buckets[key] = bucket
                return bucket
            if (
                abs(bucket.rate_per_second - normalized_rate) > 1e-9
                or abs(bucket.capacity - float(normalized_capacity)) > 1e-9
            ):
                bucket = AsyncTokenBucket(
                    rate_per_second=normalized_rate,
                    capacity=normalized_capacity,
                )
                cls._buckets[key] = bucket
            return bucket
