# Shared Resilience Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract transport-agnostic resilience primitives (circuit breaker, rate limiter, backoff, retry) into `src/shared/resilience/` with a generic `ResilientExecutor` that composes them, eliminating the duplicate `src/scanner/resilience.py`.

**Architecture:** Move `AsyncCircuitBreaker`/`AsyncTokenBucket` from `src/ingestion/resilience/` to `src/shared/resilience/` unchanged. Extract `BackoffGuard` from `ProviderBackoffGuard` into its own file. Create generic `RetryStrategy` protocol and `ResilientExecutor` composer. Ingestion resilience modules become thin re-export shims for backward compatibility. Scanner uses shared executor with subprocess-specific retry predicate.

**Tech Stack:** Python 3.12, asyncio, pytest, httpx (ingestion), subprocess (scanner)

---

### Task 0: Commit design doc

**Files:**
- Create: `docs/superpowers/specs/2026-04-29-shared-resilience-layer.md`

- [ ] **Step 1: Stage and commit**

```powershell
git add docs/superpowers/specs/2026-04-29-shared-resilience-layer.md
git commit -m "docs: add shared resilience layer design spec"
```

- [ ] **Step 2: Verify commit**

```powershell
git log --oneline -3
```

---

### Task 1: Create `src/shared/resilience/` package + tests for migrated circuit_breaker

**Files:**
- Create: `src/shared/resilience/__init__.py`
- Create: `src/shared/resilience/circuit_breaker.py`
- Test: `tests/test_shared_resilience_circuit_breaker.py`

Copy `AsyncCircuitBreaker` and `CircuitBreakerRegistry` from `src/ingestion/resilience/circuit_breaker.py`. **One signature change:** `CircuitBreakerRegistry.get_breaker` takes a single `name: str` instead of `(provider, chain_id, endpoint)`, keyed by `(name,)` tuple instead of `(provider, chain, endpoint)`. The `ProviderBackoffGuard/ProviderBackoffRegistry` stay in ingestion for now (extracted to shared as `BackoffGuard` in Task 3).

- [ ] **Step 1: Create package `__init__.py`**

```python
from __future__ import annotations
```

- [ ] **Step 2: Write tests for shared circuit breaker**

```python
# tests/test_shared_resilience_circuit_breaker.py
from __future__ import annotations

import pytest
from src.shared.resilience.circuit_breaker import AsyncCircuitBreaker


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
    cb = AsyncCircuitBreaker(
        failure_threshold=2, recovery_seconds=0.05, half_open_max_calls=1
    )
    await cb.record_failure()
    await cb.record_failure()
    assert await cb.allow_request() is False
    import asyncio
    await asyncio.sleep(0.06)
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_success_in_half_open_resets_to_closed() -> None:
    cb = AsyncCircuitBreaker(
        failure_threshold=2, recovery_seconds=0.05, half_open_max_calls=1
    )
    await cb.record_failure()
    await cb.record_failure()
    import asyncio
    await asyncio.sleep(0.06)
    await cb.allow_request()
    await cb.record_success()
    assert await cb.allow_request() is True
    assert await cb.state() == "closed"


@pytest.mark.asyncio
async def test_failure_in_half_open_reopens() -> None:
    cb = AsyncCircuitBreaker(
        failure_threshold=2, recovery_seconds=0.05, half_open_max_calls=1
    )
    await cb.record_failure()
    await cb.record_failure()
    import asyncio
    await asyncio.sleep(0.06)
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
```

- [ ] **Step 3: Run tests to verify they fail**

```powershell
.\scripts\dev.ps1 -Command check 2>&1 | Select-String -Pattern "FAILED|PASSED|ERROR"
```
Expected: import errors since `src/shared/resilience/circuit_breaker.py` doesn't exist yet.

- [ ] **Step 4: Copy circuit_breaker to shared with signature change**

Copy `src/ingestion/resilience/circuit_breaker.py` → `src/shared/resilience/circuit_breaker.py`.

Changes to the copy:
1. Remove `ProviderBackoffGuard` and `ProviderBackoffRegistry`
2. Change `CircuitBreakerRegistry` to key by single `name: str`:

```python
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
        # ... rest same as original
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
.\scripts\dev.ps1 -Command check 2>&1 | Select-String -Pattern "FAILED|PASSED|ERROR"
```
Expected: all tests pass (including pre-existing ingestion tests).

- [ ] **Step 6: Commit**

```powershell
git add src/shared/resilience/ tests/test_shared_resilience_circuit_breaker.py
git commit -m "feat: add shared resilience package with circuit breaker"
```

---

### Task 2: Migrate rate_limiter to shared

**Files:**
- Create: `src/shared/resilience/rate_limiter.py`
- Test: `tests/test_shared_resilience_rate_limiter.py`

- [ ] **Step 1: Write tests for shared rate limiter**

```python
# tests/test_shared_resilience_rate_limiter.py
from __future__ import annotations

import asyncio
import pytest
from src.shared.resilience.rate_limiter import AsyncTokenBucket, RateLimiterRegistry


@pytest.mark.asyncio
async def test_token_bucket_allows_immediate_acquisition() -> None:
    bucket = AsyncTokenBucket(rate_per_second=100.0, capacity=10)
    await bucket.acquire()
    assert True


@pytest.mark.asyncio
async def test_token_bucket_blocks_when_empty() -> None:
    bucket = AsyncTokenBucket(rate_per_second=999999.0, capacity=1)
    await bucket.acquire()
    t0 = asyncio.get_running_loop().time()
    await asyncio.wait_for(bucket.acquire(), timeout=0.5)
    elapsed = asyncio.get_running_loop().time() - t0
    assert elapsed > 0.001


@pytest.mark.asyncio
async def test_rate_limiter_registry_returns_singleton() -> None:
    b1 = RateLimiterRegistry.get_bucket(name="test", rate_per_second=10.0, capacity=5)
    b2 = RateLimiterRegistry.get_bucket(name="test", rate_per_second=10.0, capacity=5)
    assert b1 is b2


@pytest.mark.asyncio
async def test_rate_limiter_registry_different_names() -> None:
    b1 = RateLimiterRegistry.get_bucket(name="alpha", rate_per_second=10.0, capacity=5)
    b2 = RateLimiterRegistry.get_bucket(name="beta", rate_per_second=10.0, capacity=5)
    assert b1 is not b2
```

- [ ] **Step 2: Run tests to see them fail**

```powershell
pytest tests/test_shared_resilience_rate_limiter.py -v 2>&1
```
Expected: import error.

- [ ] **Step 3: Copy rate_limiter to shared with signature change**

Copy `src/ingestion/resilience/rate_limiter.py` → `src/shared/resilience/rate_limiter.py`.

**One signature change:** `RateLimiterRegistry.get_bucket` takes a single `name: str` instead of `(provider: str, chain_id: str)`, keyed by `(name,)` tuple instead of `(provider, chain)`:

```python
class RateLimiterRegistry:
    _lock = Lock()
    _buckets: dict[tuple[str], AsyncTokenBucket] = {}

    @classmethod
    def get_bucket(
        cls,
        name: str,
        rate_per_second: float,
        capacity: int,
    ) -> AsyncTokenBucket:
        key = (name.strip().lower(),)
        normalized_rate = max(0.01, float(rate_per_second))
        normalized_capacity = max(1, int(capacity))
        # ... rest same as original
```

- [ ] **Step 4: Run tests to see them pass**

```powershell
pytest tests/test_shared_resilience_rate_limiter.py -v 2>&1
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/shared/resilience/rate_limiter.py tests/test_shared_resilience_rate_limiter.py
git commit -m "feat: add shared rate limiter"
```

---

### Task 3: Create shared backoff.py

**Files:**
- Create: `src/shared/resilience/backoff.py`
- Test: `tests/test_shared_resilience_backoff.py`

Extract `BackoffGuard` and `BackoffRegistry` from `ProviderBackoffGuard`/`ProviderBackoffRegistry`, renamed and generalized (key by string name instead of `(provider, chain)` tuple).

- [ ] **Step 1: Write tests for shared backoff**

```python
# tests/test_shared_resilience_backoff.py
from __future__ import annotations

import pytest
from src.shared.resilience.backoff import BackoffGuard, BackoffRegistry
from time import monotonic


@pytest.mark.asyncio
async def test_backoff_guard_allows_initial_request() -> None:
    guard = BackoffGuard()
    assert guard.allow_request(monotonic()) is True


@pytest.mark.asyncio
async def test_backoff_guard_blocks_after_failure() -> None:
    guard = BackoffGuard()
    now = monotonic()
    guard.record_failure(now=now, base_seconds=60.0, max_seconds=300.0)
    assert guard.allow_request(now + 1.0) is False


@pytest.mark.asyncio
async def test_backoff_guard_recovers_after_timeout() -> None:
    guard = BackoffGuard()
    now = monotonic()
    guard.record_failure(now=now, base_seconds=0.01, max_seconds=0.02)
    assert guard.allow_request(now + 0.03) is True


@pytest.mark.asyncio
async def test_backoff_guard_resets_on_success() -> None:
    guard = BackoffGuard()
    now = monotonic()
    guard.record_failure(now=now, base_seconds=60.0, max_seconds=300.0)
    guard.record_success()
    assert guard.allow_request(now + 1.0) is True


@pytest.mark.asyncio
async def test_backoff_guard_increases_backoff_on_consecutive_failures() -> None:
    guard = BackoffGuard()
    now = monotonic()
    guard.record_failure(now=now, base_seconds=1.0, max_seconds=100.0)
    t1 = guard.remaining_blocked_seconds(now)
    guard.record_failure(now=now, base_seconds=1.0, max_seconds=100.0)
    t2 = guard.remaining_blocked_seconds(now)
    assert t2 > t1


@pytest.mark.asyncio
async def test_backoff_registry_singleton() -> None:
    g1 = BackoffRegistry.get_guard(name="test")
    g2 = BackoffRegistry.get_guard(name="test")
    assert g1 is g2


@pytest.mark.asyncio
async def test_backoff_registry_different_names() -> None:
    g1 = BackoffRegistry.get_guard(name="alpha")
    g2 = BackoffRegistry.get_guard(name="beta")
    assert g1 is not g2
```

- [ ] **Step 2: Run tests to see them fail**

```powershell
pytest tests/test_shared_resilience_backoff.py -v 2>&1
```
Expected: import error.

- [ ] **Step 3: Create backoff.py**

```python
from __future__ import annotations

from threading import Lock
from time import monotonic


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
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
pytest tests/test_shared_resilience_backoff.py -v 2>&1
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/shared/resilience/backoff.py tests/test_shared_resilience_backoff.py
git commit -m "feat: add shared backoff guard"
```

---

### Task 4: Create shared retry.py

**Files:**
- Create: `src/shared/resilience/retry.py`
- Test: `tests/test_shared_resilience_retry.py`

- [ ] **Step 1: Write tests for shared retry**

```python
# tests/test_shared_resilience_retry.py
from __future__ import annotations

from src.shared.resilience.retry import retry_sleep_seconds


def test_retry_sleep_increases_with_attempt() -> None:
    t1 = retry_sleep_seconds(attempt=1, base_seconds=1.0, max_seconds=60.0)
    t2 = retry_sleep_seconds(attempt=2, base_seconds=1.0, max_seconds=60.0)
    assert t2 > t1


def test_retry_sleep_capped_by_max() -> None:
    t = retry_sleep_seconds(attempt=10, base_seconds=10.0, max_seconds=15.0)
    assert t <= 15.0


def test_retry_sleep_includes_jitter() -> None:
    values = {
        retry_sleep_seconds(attempt=1, base_seconds=5.0, max_seconds=60.0)
        for _ in range(20)
    }
    assert len(values) > 1  # jitter produces variation
```

- [ ] **Step 2: Run tests to see them fail**

```powershell
pytest tests/test_shared_resilience_retry.py -v 2>&1
```
Expected: import error.

- [ ] **Step 3: Create retry.py**

```python
from __future__ import annotations

import random
from collections.abc import Callable


def retry_sleep_seconds(
    attempt: int,
    base_seconds: float,
    max_seconds: float,
) -> float:
    jitter = random.uniform(0.0, base_seconds)
    return min(max_seconds, base_seconds * (2 ** (attempt - 1)) + jitter)


RetryableCheck = Callable[[Exception], bool]
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
pytest tests/test_shared_resilience_retry.py -v 2>&1
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/shared/resilience/retry.py tests/test_shared_resilience_retry.py
git commit -m "feat: add shared retry utilities"
```

---

### Task 5: Create shared executor.py

**Files:**
- Create: `src/shared/resilience/executor.py`
- Test: `tests/test_shared_resilience_executor.py`

- [ ] **Step 1: Write tests for ResilientExecutor**

```python
# tests/test_shared_resilience_executor.py
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
    result = await executor.execute(_ok)  # circuit open
    assert result is None  # blocked by circuit breaker
```

- [ ] **Step 2: Run tests to see them fail**

```powershell
pytest tests/test_shared_resilience_executor.py -v 2>&1
```
Expected: import error.

- [ ] **Step 3: Create executor.py**

```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic

from src.shared.resilience.backoff import BackoffRegistry
from src.shared.resilience.circuit_breaker import CircuitBreakerRegistry
from src.shared.resilience.rate_limiter import RateLimiterRegistry
from src.shared.resilience.retry import retry_sleep_seconds, RetryableCheck

logger = logging.getLogger(__name__)


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
        fn: Callable[[], Awaitable],
    ):
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
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
pytest tests/test_shared_resilience_executor.py -v 2>&1
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/shared/resilience/executor.py tests/test_shared_resilience_executor.py
git commit -m "feat: add generic ResilientExecutor"
```

---

### Task 6: Refactor ingestion resilience to re-export from shared

**Files:**
- Modify: `src/ingestion/resilience/circuit_breaker.py` — replace with re-exports from shared + keep `ProviderBackoff*` aliases
- Modify: `src/ingestion/resilience/rate_limiter.py` — replace with re-exports from shared
- Modify: `src/ingestion/resilience/retry_policy.py` — keep httpx-specific logic, re-export `retry_sleep_seconds`
- Modify: `src/ingestion/resilience/__init__.py` — re-export from shared via circuit_breaker and rate_limiter

- [ ] **Step 1: Replace `src/ingestion/resilience/circuit_breaker.py`**

The shared `CircuitBreakerRegistry.get_breaker` takes a single `name` parameter.
Ingestion callers pass `(provider, chain_id, endpoint)`. Provide a compatibility wrapper:

```python
from __future__ import annotations

from src.shared.resilience.backoff import BackoffGuard, BackoffRegistry
from src.shared.resilience.circuit_breaker import (
    AsyncCircuitBreaker,
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


ProviderBackoffGuard = BackoffGuard
ProviderBackoffRegistry = BackoffRegistry

__all__ = [
    "AsyncCircuitBreaker",
    "CircuitBreakerRegistry",
    "ProviderBackoffGuard",
    "ProviderBackoffRegistry",
    "BackoffGuard",
    "BackoffRegistry",
]
```

- [ ] **Step 2: Replace `src/ingestion/resilience/rate_limiter.py`**

The shared `RateLimiterRegistry.get_bucket` takes a single `name` parameter.
Ingestion callers pass `(provider, chain_id)`. Add a compatibility wrapper:

```python
from __future__ import annotations

from src.shared.resilience.rate_limiter import (
    AsyncTokenBucket,
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
```

- [ ] **Step 3: Update `src/ingestion/resilience/retry_policy.py`**

Edit to import `retry_sleep_seconds` from shared:

```python
# Add at the top:
from src.shared.resilience.retry import retry_sleep_seconds  # noqa: F401
```

- [ ] **Step 4: Run ingestion tests to verify backward compatibility**

```powershell
pytest tests/test_ingestion_resilience.py -v 2>&1
```
Expected: all passed.

- [ ] **Step 5: Run full test suite**

```powershell
.\scripts\dev.ps1 -Command check 2>&1
```
Expected: all passed (ignore pre-commit failures on unrelated files).

- [ ] **Step 6: Commit**

```powershell
git add src/ingestion/resilience/
git commit -m "refactor: ingestion resilience re-exports from shared package"
```

---

### Task 7: Update scanner to use shared resilience (delete scanner/resilience.py)

**Files:**
- Delete: `src/scanner/resilience.py`
- Modify: `src/scanner/gmgn_client.py`
- Modify: `src/scanner/__main__.py`

- [ ] **Step 1: Update `src/scanner/gmgn_client.py`**

Replace usage of `src.scanner.resilience` with `src.shared.resilience.executor`:

```python
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from src.scanner.models import TokenRisk, TrendingToken
from src.scanner.resilience import ConcurrencyLimiter
from src.shared.resilience.executor import ResilienceConfig, ResilientExecutor

logger = logging.getLogger(__name__)

# ConcurrencyLimiter stays in scanner (it's not a resilience primitive, it's a resource manager)


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))

    async def run(self, coro_factory):
        async with self._semaphore:
            return await coro_factory()


class GmgnClient:
    def __init__(
        self,
        gmgn_cli_path: str = "gmgn-cli",
        api_key: str = "",
        trending_timeout_seconds: float = 30.0,
        security_timeout_seconds: float = 15.0,
        rate_limit_per_second: float = 2.0,
        rate_limit_capacity: int = 5,
        circuit_failure_threshold: int = 5,
        circuit_recovery_seconds: float = 30.0,
        circuit_half_open_max_calls: int = 2,
        retry_attempts: int = 3,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 30.0,
        security_max_concurrency: int = 5,
    ) -> None:
        self._cli_path = gmgn_cli_path
        self._api_key = api_key
        self._trending_timeout = trending_timeout_seconds
        self._security_timeout = security_timeout_seconds

        def _is_retryable(e: Exception) -> bool:
            return isinstance(e, (TimeoutError, OSError))

        base_config = ResilienceConfig(
            rate_limit_per_second=rate_limit_per_second,
            rate_limit_capacity=rate_limit_capacity,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_recovery_seconds=circuit_recovery_seconds,
            circuit_half_open_max_calls=circuit_half_open_max_calls,
            retry_attempts=retry_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
            backoff_base_seconds=retry_base_seconds,
            backoff_max_seconds=retry_max_seconds,
        )
        self._trending_executor = ResilientExecutor(
            name="gmgn_trending",
            config=base_config,
            is_retryable=_is_retryable,
        )
        self._security_executor = ResilientExecutor(
            name="gmgn_security",
            config=base_config,
            is_retryable=_is_retryable,
        )
        self._concurrency_limiter = ConcurrencyLimiter(max_concurrent=security_max_concurrency)

    async def fetch_trending(
        self,
        chain: str,
        interval: str,
        limit: int = 50,
    ) -> list[TrendingToken]:
        return await self._trending_executor.execute(
            lambda: self._do_fetch_trending(chain, interval, limit)
        )

    async def _do_fetch_trending(
        self,
        chain: str,
        interval: str,
        limit: int,
    ) -> list[TrendingToken]:
        env = dict(os.environ)
        if self._api_key:
            env["GMGN_API_KEY"] = self._api_key

        try:
            if sys.platform == "win32":
                args = (
                    f"{self._cli_path} market trending"
                    f" --chain {chain} --interval {interval}"
                    f" --limit {limit} --raw"
                )
                proc = await asyncio.create_subprocess_shell(
                    args,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                cmd = [
                    self._cli_path,
                    "market",
                    "trending",
                    "--chain",
                    chain,
                    "--interval",
                    interval,
                    "--limit",
                    str(limit),
                    "--raw",
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._trending_timeout
            )
            if proc.returncode != 0:
                logger.error(
                    "gmgn-cli failed (exit=%d) stderr=%s stdout=%s",
                    proc.returncode,
                    stderr.decode()[:500],
                    stdout.decode()[:500],
                )
                return []
        except (TimeoutError, OSError) as e:
            logger.error("gmgn-cli error: %s", e)
            raise

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error("gmgn-cli JSON parse error: %s (stdout=%s)", e, stdout.decode()[:500])
            return []

        inner = data.get("data", {}) if isinstance(data, dict) else data
        if isinstance(inner, list):
            raw_tokens = inner
        elif isinstance(inner, dict):
            raw_tokens = next((v for v in inner.values() if isinstance(v, list)), [])
        else:
            raw_tokens = []
        if not isinstance(raw_tokens, list):
            logger.warning("gmgn-cli unexpected data format")
            return []
        result: list[TrendingToken] = []
        for t in raw_tokens:
            if not isinstance(t, dict):
                logger.warning("gmgn-cli skipping non-dict token: %s", type(t).__name__)
                continue
            result.append(
                TrendingToken(
                    address=t.get("address", ""),
                    symbol=t.get("symbol", ""),
                    name=t.get("name", ""),
                    price_usd=float(t.get("price_usd", 0) or 0),
                    volume_1m=_safe_float(t, "volume_1m"),
                    volume_1h=_safe_float(t, "volume_1h"),
                    market_cap=_safe_float(t, "market_cap"),
                    liquidity=_safe_float(t, "liquidity"),
                    smart_degen_count=t.get("smart_degen_count"),
                    rank=int(t.get("rank", 0)),
                    chain=chain,
                )
            )
        return result

    async def fetch_token_security(self, chain: str, address: str) -> TokenRisk | None:
        return await self._concurrency_limiter.run(
            lambda: self._security_executor.execute(
                lambda: self._do_fetch_token_security(chain, address)
            )
        )

    async def _do_fetch_token_security(self, chain: str, address: str) -> TokenRisk | None:
        cmd = [
            self._cli_path,
            "token",
            "security",
            "--chain",
            chain,
            "--address",
            address,
            "--raw",
        ]
        env = dict(os.environ)
        if self._api_key:
            env["GMGN_API_KEY"] = self._api_key
        try:
            if sys.platform == "win32":
                args = " ".join(cmd)
                proc = await asyncio.create_subprocess_shell(
                    args,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._security_timeout
            )
            if proc.returncode != 0:
                logger.error(
                    "gmgn-cli security failed (exit=%d) stderr=%s",
                    proc.returncode,
                    stderr.decode()[:500],
                )
                return None
            data = json.loads(stdout)
            inner = data.get("data", {}) if isinstance(data, dict) else data
            if not isinstance(inner, dict):
                return None
            return TokenRisk(
                rug_risk=float(inner.get("rug_risk", 0) or 0),
                is_honeypot=bool(inner.get("is_honeypot", False)),
                bundler_ratio=float(inner.get("bundler_trader_amount_rate", 0) or 0),
                rat_ratio=float(inner.get("rat_trader_amount_rate", 0) or 0),
                sniper_count=int(inner.get("sniper_count", 0) or 0),
                top10_holder_pct=float(inner.get("top10_holder_rate", 0) or 0),
            )
        except (json.JSONDecodeError, TimeoutError, OSError) as e:
            logger.warning("fetch_token_security failed for %s: %s", address, e)
            raise


def _safe_float(d: dict, key: str) -> float | None:
    val = d.get(key)
    if val is None:
        return None
    return float(val)
```

- [ ] **Step 2: Delete `src/scanner/resilience.py`**

```powershell
git rm src/scanner/resilience.py
```

- [ ] **Step 3: Run scanner tests**

```powershell
pytest tests/test_scanner_gmgn_client.py -v 2>&1
```
Expected: all passed.

- [ ] **Step 4: Run full test suite**

```powershell
.\scripts\dev.ps1 -Command check 2>&1
```
Expected: all passed (ignore pre-commit failures on unrelated files).

- [ ] **Step 5: Commit**

```powershell
git add src/scanner/gmgn_client.py src/scanner/__main__.py
git commit -m "refactor: scanner uses shared ResilientExecutor"
```

---

### Task 8: Remove unused scanner resilience config (optional cleanup)

**Files:**
- Modify: `src/shared/config.py` — the resilience config (`scanner_rate_limit_*`, etc.) was already added; no cleanup needed. But the `scanner_resilience.py`-specific settings can stay — they're consumed by `__main__.py` → `GmgnClient`.

No changes needed — the config is already consumed by `GmgnClient` via `__main__.py`.

---

### Task 9: Final verification

- [ ] **Step 1: Run lint**

```powershell
ruff check src/shared/resilience/ src/ingestion/resilience/ src/scanner/
```
Expected: no errors.

- [ ] **Step 2: Run all tests**

```powershell
pytest tests/test_shared_resilience_*.py tests/test_scanner_*.py tests/test_ingestion*.py -v 2>&1 | Select-String -Pattern "FAILED|passed|failed"
```
Expected: all passed.

- [ ] **Step 3: Run full check**

```powershell
.\scripts\dev.ps1 -Command check 2>&1 | Select-String -Pattern "checks passed|FAILED|error"
```
Expected: "All checks passed!" for ruff + pytest.
