from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar

from src.shared.resilience.backoff import BackoffRegistry
from src.shared.resilience.circuit_breaker import CircuitBreakerRegistry
from src.shared.resilience.rate_limiter import RateLimiterRegistry
from src.shared.resilience.retry import RetryableCheck, retry_sleep_seconds

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class ResilienceConfig:
    rate_limit_per_second: float = 2.0
    rate_limit_capacity: int = 5
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    circuit_half_open_max_calls: int = 2
    retry_attempts: int = 3
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 30.0
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0


class ResilientExecutor:
    def __init__(
        self,
        name: str,
        config: ResilienceConfig,
        is_retryable: RetryableCheck,
    ) -> None:
        self._name = name.strip().lower()
        self._config = config
        self._is_retryable = is_retryable

        self._breaker = CircuitBreakerRegistry.get_breaker(
            name=self._name,
            failure_threshold=config.circuit_failure_threshold,
            recovery_seconds=config.circuit_recovery_seconds,
            half_open_max_calls=config.circuit_half_open_max_calls,
        )
        self._limiter = RateLimiterRegistry.get_bucket(
            name=self._name,
            rate_per_second=config.rate_limit_per_second,
            capacity=config.rate_limit_capacity,
        )
        self._backoff = BackoffRegistry.get_guard(name=self._name)

    async def execute(
        self,
        fn: Callable[[], Awaitable[T]],
    ) -> T | None:
        now = monotonic()
        if not self._backoff.allow_request(now=now):
            logger.warning("Backoff active for %s, skipping", self._name)
            return None

        if not await self._breaker.allow_request():
            logger.warning("Circuit breaker open for %s, skipping", self._name)
            return None

        for attempt in range(1, self._config.retry_attempts + 1):
            try:
                await self._limiter.acquire()
                result = await fn()
                await self._breaker.record_success()
                self._backoff.record_success()
                return result
            except Exception as e:
                if not self._is_retryable(e):
                    raise
                if attempt < self._config.retry_attempts:
                    sleep = retry_sleep_seconds(
                        attempt=attempt,
                        base_seconds=self._config.retry_base_seconds,
                        max_seconds=self._config.retry_max_seconds,
                    )
                    logger.warning(
                        "Attempt %d/%d failed for %s: %s, retrying in %.1fs",
                        attempt,
                        self._config.retry_attempts,
                        self._name,
                        e,
                        sleep,
                    )
                    await asyncio.sleep(sleep)
                else:
                    logger.error(
                        "All %d attempts failed for %s: %s",
                        self._config.retry_attempts,
                        self._name,
                        e,
                    )

        await self._breaker.record_failure()
        self._backoff.record_failure(
            now=monotonic(),
            base_seconds=self._config.backoff_base_seconds,
            max_seconds=self._config.backoff_max_seconds,
        )
        return None
