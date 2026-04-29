from __future__ import annotations

import pytest
from src.shared.resilience.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerRegistry


@pytest.mark.asyncio
async def test_initial_state_is_closed() -> None:
    cb = AsyncCircuitBreaker(failure_threshold=3, recovery_seconds=10.0)
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_opens_after_threshold_failures() -> None:
    cb = AsyncCircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
    for _ in range(3):
        await cb.record_failure()
    assert await cb.allow_request() is False


@pytest.mark.asyncio
async def test_half_open_allows_probe() -> None:
    cb = AsyncCircuitBreaker(failure_threshold=2, recovery_seconds=0.5, half_open_max_calls=1)
    await cb.record_failure()
    await cb.record_failure()
    assert await cb.allow_request() is False
    import asyncio

    await asyncio.sleep(1.0)
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_success_in_half_open_resets_to_closed() -> None:
    cb = AsyncCircuitBreaker(failure_threshold=2, recovery_seconds=0.5, half_open_max_calls=1)
    await cb.record_failure()
    await cb.record_failure()
    import asyncio

    await asyncio.sleep(1.0)
    await cb.allow_request()
    await cb.record_success()
    assert await cb.allow_request() is True
    assert await cb.state() == "closed"


@pytest.mark.asyncio
async def test_failure_in_half_open_reopens() -> None:
    cb = AsyncCircuitBreaker(failure_threshold=2, recovery_seconds=0.5, half_open_max_calls=1)
    await cb.record_failure()
    await cb.record_failure()
    import asyncio

    await asyncio.sleep(1.0)
    assert await cb.allow_request() is True
    await cb.record_failure()
    await cb.record_failure()
    assert await cb.allow_request() is False  # back to open


@pytest.mark.asyncio
async def test_remaining_open_seconds() -> None:
    cb = AsyncCircuitBreaker(failure_threshold=1, recovery_seconds=60.0)
    await cb.record_failure()
    remaining = await cb.remaining_open_seconds()
    assert remaining > 55.0


@pytest.mark.asyncio
async def test_registry_get_breaker_by_name() -> None:
    cb1 = CircuitBreakerRegistry.get_breaker(
        "eth-mainnet", failure_threshold=3, recovery_seconds=30.0, half_open_max_calls=1
    )
    cb2 = CircuitBreakerRegistry.get_breaker(
        "eth-mainnet", failure_threshold=3, recovery_seconds=30.0, half_open_max_calls=1
    )
    assert cb1 is cb2


@pytest.mark.asyncio
async def test_registry_name_case_insensitive() -> None:
    cb1 = CircuitBreakerRegistry.get_breaker(
        "Eth-Mainnet", failure_threshold=3, recovery_seconds=30.0, half_open_max_calls=1
    )
    cb2 = CircuitBreakerRegistry.get_breaker(
        "eth-mainnet", failure_threshold=3, recovery_seconds=30.0, half_open_max_calls=1
    )
    assert cb1 is cb2


@pytest.mark.asyncio
async def test_registry_different_names_different_breakers() -> None:
    cb1 = CircuitBreakerRegistry.get_breaker(
        "eth-mainnet", failure_threshold=3, recovery_seconds=30.0, half_open_max_calls=1
    )
    cb2 = CircuitBreakerRegistry.get_breaker(
        "bsc-mainnet", failure_threshold=3, recovery_seconds=30.0, half_open_max_calls=1
    )
    assert cb1 is not cb2


@pytest.mark.asyncio
async def test_registry_updates_params_on_reget() -> None:
    cb1 = CircuitBreakerRegistry.get_breaker(
        "eth-mainnet", failure_threshold=3, recovery_seconds=30.0, half_open_max_calls=1
    )
    cb2 = CircuitBreakerRegistry.get_breaker(
        "eth-mainnet", failure_threshold=5, recovery_seconds=60.0, half_open_max_calls=2
    )
    assert cb1 is not cb2
    assert cb2.failure_threshold == 5
