from __future__ import annotations

import asyncio
import logging
from time import monotonic

import httpx
from httpx import AsyncClient
from src.ingestion.resilience.cache_store import ResponseCacheStore
from src.ingestion.resilience.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitBreakerRegistry,
    ProviderBackoffGuard,
    ProviderBackoffRegistry,
)
from src.ingestion.resilience.metrics import (
    INGEST_ERROR_TOTAL,
    ResilienceMetrics,
)
from src.ingestion.resilience.rate_limiter import RateLimiterRegistry
from src.ingestion.resilience.retry_policy import RetryPolicy
from src.ingestion.resilience.singleflight import SingleFlightGroup
from src.shared.config.infra import get_infra_settings
from src.shared.config.ingestion import IngestionSettings

logger = logging.getLogger(__name__)
__all__ = ["ResilientHttpClient", "INGEST_ERROR_TOTAL"]


class ResilientHttpClient:
    def __init__(
        self,
        chain_id: str,
        provider: str,
        settings: IngestionSettings,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chain_id = chain_id
        self._provider = provider.strip().lower()
        self._settings = settings
        infra_settings = get_infra_settings()
        self._headers = headers or {}
        self._metrics = ResilienceMetrics(chain_id=chain_id, provider=self._provider)
        self._bucket = RateLimiterRegistry.get_bucket(
            provider=self._provider,
            chain_id=self._chain_id,
            rate_per_second=self._settings.get_rate_limit_per_second(
                chain_id=self._chain_id,
                provider=self._provider,
            ),
            capacity=self._settings.get_rate_limit_capacity(
                chain_id=self._chain_id,
                provider=self._provider,
            ),
        )
        self._provider_backoff_guard: ProviderBackoffGuard = ProviderBackoffRegistry.get_guard(
            provider=self._provider,
            chain_id=self._chain_id,
        )
        self._provider_backoff_base_seconds = max(
            0.1,
            float(self._settings.retry_base_seconds),
        )
        self._provider_backoff_max_seconds = max(
            0.5,
            float(self._settings.retry_max_sleep_seconds),
        )
        self._blocked_since_by_endpoint: dict[str, float] = {}
        self._blocked_since_lock = asyncio.Lock()
        self._cache = ResponseCacheStore(
            chain_id=self._chain_id,
            provider=self._provider,
            redis_url=infra_settings.redis_url,
            ttl_seconds=self._settings.cache_ttl_seconds,
            max_entries=self._settings.cache_max_entries,
            metrics=self._metrics,
        )
        self._singleflight = SingleFlightGroup()
        self._http_client: AsyncClient | None = None
        self._http_client_lock = asyncio.Lock()
        self._http_client_timeout = max(0.5, self._settings.timeout_seconds)
        self._http_client_limits = httpx.Limits(
            max_connections=max(1, self._settings.http_max_connections),
            max_keepalive_connections=max(1, self._settings.http_max_keepalive_connections),
            keepalive_expiry=max(1.0, self._settings.http_keepalive_expiry_seconds),
        )

    async def get_json(
        self,
        url: str,
        endpoint: str,
        trace_id: str,
        trace: str,
    ) -> dict | None:
        cached = await self._cache.get(url=url)
        if cached is not None:
            self._metrics.request(endpoint=endpoint, status="cache_hit")
            return cached

        leader_future, is_leader = await self._singleflight.acquire(key=url)
        if not is_leader:
            self._metrics.request(endpoint=endpoint, status="singleflight_wait")
            return await leader_future

        try:
            result = await self._request_json_uncached(
                url=url,
                endpoint=endpoint,
                trace_id=trace_id,
                trace=trace,
            )
            if not leader_future.done():
                leader_future.set_result(result)
            return result
        except BaseException as exc:
            if not leader_future.done():
                leader_future.set_exception(exc)
            raise
        finally:
            await self._singleflight.release(key=url, holder=leader_future)

    async def _request_json_uncached(
        self,
        url: str,
        endpoint: str,
        trace_id: str,
        trace: str,
    ) -> dict | None:
        breaker = await self._breaker_for_endpoint(endpoint=endpoint)
        now = monotonic()
        if not self._provider_backoff_guard.allow_request(now=now):
            self._metrics.circuit_open_state(endpoint=endpoint, opened=True)
            await self._record_circuit_blocked(endpoint=endpoint, now=now)
            self._metrics.request(endpoint=endpoint, status="blocked")
            self._metrics.error(reason="provider_backoff_open")
            return None
        if not await breaker.allow_request():
            self._metrics.circuit_open_state(endpoint=endpoint, opened=True)
            await self._record_circuit_blocked(endpoint=endpoint, now=now)
            self._metrics.request(endpoint=endpoint, status="blocked")
            self._metrics.error(reason="circuit_open")
            return None
        await self._clear_circuit_blocked(endpoint=endpoint)
        self._metrics.circuit_open_state(endpoint=endpoint, opened=False)
        max_attempts = self._settings.get_retry_attempts(chain_id=self._chain_id)
        backoff = max(0.05, self._settings.retry_base_seconds)
        max_sleep_seconds = max(0.05, float(self._settings.retry_max_sleep_seconds))
        for attempt in range(1, max_attempts + 1):
            try:
                await self._bucket.acquire()
                started = asyncio.get_running_loop().time()
                client = await self._get_http_client()
                response = await client.get(url)
                self._metrics.latency(
                    endpoint=endpoint,
                    seconds=asyncio.get_running_loop().time() - started,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    if response.status_code == 429:
                        self._metrics.rate_limited(endpoint=endpoint)
                    raise httpx.HTTPStatusError(
                        f"retryable status={response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("unexpected non-dict payload")
                self._metrics.request(endpoint=endpoint, status="success")
                await breaker.record_success()
                self._provider_backoff_guard.record_success()
                await self._cache.set(url=url, payload=payload)
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                self._metrics.request(endpoint=endpoint, status="error")
                reason = RetryPolicy.error_reason(exc)
                self._metrics.error(reason=reason)
                if not RetryPolicy.is_retryable_exception(exc):
                    logger.warning(
                        "ingestion request fail-fast chain=%s trace_id=%s trace=%s reason=%s: %s",
                        self._chain_id,
                        trace_id,
                        trace,
                        reason,
                        exc,
                    )
                    await breaker.record_failure()
                    self._provider_backoff_guard.record_failure(
                        now=monotonic(),
                        base_seconds=self._provider_backoff_base_seconds,
                        max_seconds=self._provider_backoff_max_seconds,
                    )
                    return None
                if attempt >= max_attempts:
                    logger.warning(
                        "ingestion request failed chain=%s trace_id=%s trace=%s "
                        "attempt=%s reason=%s: %s",
                        self._chain_id,
                        trace_id,
                        trace,
                        attempt,
                        reason,
                        exc,
                    )
                    await breaker.record_failure()
                    self._provider_backoff_guard.record_failure(
                        now=monotonic(),
                        base_seconds=self._provider_backoff_base_seconds,
                        max_seconds=self._provider_backoff_max_seconds,
                    )
                    return None
                self._metrics.retry(endpoint=endpoint)
                sleep_seconds = RetryPolicy.retry_sleep_seconds(
                    exc=exc,
                    base_backoff=backoff,
                    attempt=attempt,
                    max_sleep_seconds=max_sleep_seconds,
                )
                await asyncio.sleep(sleep_seconds)
        return None

    async def _get_http_client(self) -> AsyncClient:
        async with self._http_client_lock:
            if self._http_client is None or self._http_client.is_closed:
                self._http_client = httpx.AsyncClient(
                    timeout=self._http_client_timeout,
                    headers=self._headers,
                    limits=self._http_client_limits,
                )
            return self._http_client

    async def _breaker_for_endpoint(self, endpoint: str) -> AsyncCircuitBreaker:
        return CircuitBreakerRegistry.get_breaker(
            provider=self._provider,
            chain_id=self._chain_id,
            endpoint=endpoint,
            failure_threshold=self._settings.get_circuit_failure_threshold(chain_id=self._chain_id),
            recovery_seconds=self._settings.get_circuit_recovery_seconds(chain_id=self._chain_id),
            half_open_max_calls=self._settings.circuit_half_open_max_calls,
        )

    async def _record_circuit_blocked(self, endpoint: str, now: float) -> None:
        async with self._blocked_since_lock:
            last_blocked_seen = self._blocked_since_by_endpoint.get(endpoint)
            if last_blocked_seen is None:
                self._blocked_since_by_endpoint[endpoint] = now
                return
            blocked_seconds = max(0.0, now - last_blocked_seen)
            if blocked_seconds > 0:
                self._metrics.circuit_open_seconds(
                    endpoint=endpoint, blocked_seconds=blocked_seconds
                )
            self._blocked_since_by_endpoint[endpoint] = now

    async def _clear_circuit_blocked(self, endpoint: str) -> None:
        async with self._blocked_since_lock:
            last_blocked_seen = self._blocked_since_by_endpoint.pop(endpoint, None)
            if last_blocked_seen is not None:
                blocked_seconds = max(0.0, monotonic() - last_blocked_seen)
                if blocked_seconds > 0:
                    self._metrics.circuit_open_seconds(
                        endpoint=endpoint, blocked_seconds=blocked_seconds
                    )

    async def aclose(self) -> None:
        async with self._http_client_lock:
            if self._http_client is not None:
                await self._http_client.aclose()
                self._http_client = None
        await self._cache.aclose()

    async def __aenter__(self) -> ResilientHttpClient:
        await self._get_http_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.aclose()

    @staticmethod
    def _retry_after_seconds(response: httpx.Response | None) -> float | None:
        return RetryPolicy.retry_after_seconds(response=response)
