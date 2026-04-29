from __future__ import annotations

import pytest
from src.shared.resilience.executor import ResilienceConfig, ResilientExecutor


class _RetryableError(Exception):
    pass


class _NonRetryableError(Exception):
    pass


def _is_retryable(e: Exception) -> bool:
    return isinstance(e, _RetryableError)


async def _ok() -> str:
    return "ok"


async def _always_fails_retryable() -> str:
    raise _RetryableError("boom")


async def _always_fails_nonretryable() -> str:
    raise _NonRetryableError("boom")


@pytest.mark.asyncio
async def test_executor_returns_result_on_success() -> None:
    executor = ResilientExecutor(
        name="utest_ok",
        config=ResilienceConfig(retry_attempts=1),
        is_retryable=_is_retryable,
    )
    result = await executor.execute(_ok)
    assert result == "ok"


@pytest.mark.asyncio
async def test_executor_returns_none_on_retry_exhaustion() -> None:
    executor = ResilientExecutor(
        name="utest_exhaust",
        config=ResilienceConfig(retry_attempts=2),
        is_retryable=_is_retryable,
    )
    result = await executor.execute(_always_fails_retryable)
    assert result is None


@pytest.mark.asyncio
async def test_executor_propagates_non_retryable_exception() -> None:
    executor = ResilientExecutor(
        name="utest_prop",
        config=ResilienceConfig(retry_attempts=2),
        is_retryable=_is_retryable,
    )
    with pytest.raises(_NonRetryableError):
        await executor.execute(_always_fails_nonretryable)


@pytest.mark.asyncio
async def test_executor_circuit_breaker_blocks_after_failures() -> None:
    executor = ResilientExecutor(
        name="utest_circuit",
        config=ResilienceConfig(
            retry_attempts=1,
            circuit_failure_threshold=2,
            circuit_recovery_seconds=60.0,
        ),
        is_retryable=_is_retryable,
    )
    await executor.execute(_always_fails_retryable)  # failure 1
    await executor.execute(_always_fails_retryable)  # failure 2 -> opens circuit
    result = await executor.execute(_ok)
    assert result is None  # blocked by circuit breaker
