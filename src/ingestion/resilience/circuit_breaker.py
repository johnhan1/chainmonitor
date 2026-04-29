from __future__ import annotations

from src.shared.resilience.backoff import BackoffGuard
from src.shared.resilience.backoff import BackoffRegistry as _SharedBackoffRegistry
from src.shared.resilience.circuit_breaker import (
    AsyncCircuitBreaker,
)
from src.shared.resilience.circuit_breaker import (
    CircuitBreakerRegistry as _SharedCircuitBreakerRegistry,
)


class CircuitBreakerRegistry:
    @classmethod
    def get_breaker(
        cls,
        provider: str,
        chain_id: str,
        endpoint: str,
        failure_threshold: int,
        recovery_seconds: float,
        half_open_max_calls: int,
    ) -> AsyncCircuitBreaker:
        name = f"{provider}.{chain_id}.{endpoint}"
        return _SharedCircuitBreakerRegistry.get_breaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_seconds=recovery_seconds,
            half_open_max_calls=half_open_max_calls,
        )


class ProviderBackoffRegistry:
    @classmethod
    def get_guard(cls, provider: str, chain_id: str) -> BackoffGuard:
        name = f"{provider}.{chain_id}"
        return _SharedBackoffRegistry.get_guard(name=name)


ProviderBackoffGuard = BackoffGuard
BackoffRegistry = _SharedBackoffRegistry

__all__ = [
    "AsyncCircuitBreaker",
    "CircuitBreakerRegistry",
    "ProviderBackoffGuard",
    "ProviderBackoffRegistry",
    "BackoffGuard",
    "BackoffRegistry",
]
