# Shared Resilience Layer

Date: 2026-04-29
Status: Draft

## Problem

The project has two independent callers of external services:

| Caller | Transport | Retryable Exceptions |
|--------|-----------|---------------------|
| `ingestion/` (3 providers) | `httpx` HTTP | `httpx.TimeoutException`, `httpx.HTTPStatusError` (429, 5xx) |
| `scanner/` (gmgn-cli) | `asyncio` subprocess | `TimeoutError`, `OSError` |

Both need the same resilience primitives: rate limiting, circuit breaking, backoff, retry.
Currently these primitives live in `src/ingestion/resilience/` but are hardwired into
`ResilientHttpClient` and `RetryPolicy` (both httpx-specific). The scanner got a
duplicate copy (`src/scanner/resilience.py`) — exactly the outcome to avoid going forward.

## Architecture

Extract transport-agnostic primitives into `src/shared/resilience/`, with a generic
`ResilientExecutor` that composes them. Ingestion and scanner each provide only
the transport-specific glue (execute function + retryable-exception predicate).

```
┌─────────────────────────────────────────────────────┐
│                   Caller (ingestion/scanner/...)     │
│  result = await executor.execute(lambda: do_io())    │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│  src/shared/resilience/executor.py                  │
│  ResilientExecutor                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Circuit  │  │  Rate    │  │  Retry loop      │  │
│  │ Breaker  │→ │  Limiter │→ │  (is_retryable?) │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## Component Details

### `src/shared/resilience/circuit_breaker.py`

Transported verbatim from `src/ingestion/resilience/circuit_breaker.py`:

- `AsyncCircuitBreaker` — state machine (closed → open → half-open), thread-safe
- `CircuitBreakerRegistry` — singleton registry keyed by `(name,)` tuple
- `BackoffGuard` — per-name exponential backoff guard (renamed from `ProviderBackoffGuard`)
- `BackoffRegistry` — singleton registry for backoff guards (renamed from `ProviderBackoffRegistry`)

Changes: `ProviderBackoff*` → `Backoff*`, key type from `(provider, chain)` to `(name,)`.

### `src/shared/resilience/rate_limiter.py`

Transported verbatim from `src/ingestion/resilience/rate_limiter.py`:

- `AsyncTokenBucket` — token-bucket rate limiter, thread-safe
- `RateLimiterRegistry` — singleton registry keyed by `(name,)`

Changes: None (already generic).

### `src/shared/resilience/backoff.py`

Extracted from circuit_breaker's `ProviderBackoffGuard`/`ProviderBackoffRegistry`:

- `BackoffGuard` — tracks failure streak, computes exponential backoff with capped multiplier
- `BackoffRegistry` — singleton registry keyed by string name

Reason for separation: backoff is conceptually distinct from circuit breaking
and may be useful independently.

### `src/shared/resilience/retry.py`

Generic retry utilities, httpx-independent:

- `retry_sleep_seconds(attempt, base_seconds, max_seconds)` → exponential backoff + jitter
- `RetryStrategy` protocol: a callable `(Exception) → bool` that decides retryability

```python
# Example: scanner's retry strategy
is_retryable = lambda e: isinstance(e, (TimeoutError, OSError))

# Example: ingestion's retry strategy (in ingestion/resilience/retry_policy.py)
def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    if isinstance(exc, httpx.HTTPError):
        return True
    return False
```

### `src/shared/resilience/executor.py`

The orchestration layer. Composes all primitives into a single callable.

```python
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
        is_retryable: Callable[[Exception], bool],
    ):
        self._breaker = CircuitBreakerRegistry.get_breaker(...)
        self._limiter = RateLimiterRegistry.get_bucket(...)
        self._backoff = BackoffRegistry.get_guard(...)
        self._config = config
        self._is_retryable = is_retryable

    async def execute(self, fn: Callable[[], Awaitable[T]]) -> T | None:
        # 1. Backoff guard check
        # 2. Circuit breaker check
        # 3. Retry loop:
        #    a. Acquire rate limit token
        #    b. Call fn()
        #    c. On success: record success, return result
        #    d. On exception: check retryability, sleep & retry or record failure & return None
```

Key design decisions:
- Returns `None` on exhaustion (caller distinguishes "empty result" from "failed")
- Retry loop only catches exceptions the caller marked as retryable; non-retryable exceptions propagate
- Rate limiting happens inside the retry loop (each attempt consumes a token)
- Circuit breaker records per-attempt (not per-call), so partial failures within a retry batch count

## Ingestion Migration (Backward-Compatible)

`src/ingestion/resilience/` becomes a thin shim:

| File | Action |
|------|--------|
| `circuit_breaker.py` | `from src.shared.resilience.circuit_breaker import *` + `ProviderBackoffGuard = BackoffGuard` aliases |
| `rate_limiter.py` | `from src.shared.resilience.rate_limiter import *` |
| `retry_policy.py` | Keep httpx-specific `is_retryable_exception`, `error_reason`, `retry_after_seconds`; re-export `retry_sleep_seconds` from shared |
| `resilient_http_client.py` | Replace internal raw usage of breaker/limiter with `ResilientExecutor` |
| `cache_store.py`, `metrics.py`, `singleflight.py` | Unchanged |

All existing import paths (`src.ingestion.resilience.*`) continue to work.

## Scanner Migration

1. **Delete** `src/scanner/resilience.py` (my quick duplicate)
2. **Update** `GmgnClient` to create a `ResilientExecutor` per endpoint
3. The `ConcurrencyLimiter` stays in `GmgnClient` (it's specific to scanner's per-token security check pattern)
4. The `ScannerCircuitBreakerRegistry` is replaced by shared `CircuitBreakerRegistry`
5. The `ScannerRateLimiterRegistry` is replaced by shared `RateLimiterRegistry`
6. The `ScannerTokenBucket` is replaced by shared `AsyncTokenBucket`

## Future Transport

A new transport (e.g., websocket, gRPC) requires exactly:

```python
executor = ResilientExecutor(
    name="my_service",
    config=ResilienceConfig(...),
    is_retryable=lambda e: isinstance(e, (MySpecificError, TimeoutError)),
)
result = await executor.execute(lambda: my_call(...))
```

No new circuit breakers, rate limiters, backoff guards, or retry loops.

## Testing

- Existing tests for `ingestion/resilience/` should pass without modification (backward-compatible re-exports)
- New tests for `ResilientExecutor` with mock `fn` and mock `is_retryable`
- Scanner tests already pass with the quick implementation; after migration they should continue passing
- New test: verify that a non-retryable exception propagates through the executor
- New test: verify that circuit breaker blocks after N failures
- New test: verify rate limiter delays calls

## Open Questions

1. Should `ConcurrencyLimiter` (scanner-specific semaphore) also move to shared? It's simple enough (`asyncio.Semaphore` wrapper) that it could live in `src/shared/resilience/` as a utility, but it's technically not a "resilience" pattern — it's a resource management pattern. Decision: keep in scanner for now; if another caller needs it, promote later.

2. `BackoffGuard` vs circuit breaker: these overlap somewhat. The current design keeps both because they serve different purposes — backoff guards are per-name and activate on any failure (no threshold), while circuit breakers are per-endpoint and require a threshold of failures. This dual-layer defense is intentional.
