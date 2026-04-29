from __future__ import annotations

from src.shared.resilience.rate_limiter import (
    AsyncTokenBucket,
)
from src.shared.resilience.rate_limiter import (
    RateLimiterRegistry as _SharedRateLimiterRegistry,
)


class RateLimiterRegistry:
    @classmethod
    def get_bucket(
        cls,
        provider: str,
        chain_id: str,
        rate_per_second: float,
        capacity: int,
    ) -> AsyncTokenBucket:
        name = f"{provider}.{chain_id}"
        return _SharedRateLimiterRegistry.get_bucket(
            name=name,
            rate_per_second=rate_per_second,
            capacity=capacity,
        )


__all__ = [
    "AsyncTokenBucket",
    "RateLimiterRegistry",
]
