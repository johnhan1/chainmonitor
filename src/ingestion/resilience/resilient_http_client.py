from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from threading import Lock
from time import monotonic

import httpx
from httpx import AsyncClient
from prometheus_client import Counter, Gauge, Histogram
from src.ingestion.resilience.controls import AsyncCircuitBreaker, AsyncTokenBucket
from src.shared.config import Settings

try:
    import redis.asyncio as redis_asyncio
except Exception:  # pragma: no cover - optional dependency
    redis_asyncio = None

logger = logging.getLogger(__name__)

INGEST_REQ_TOTAL = Counter(
    "cm_ingestion_requests_total",
    "Total ingestion HTTP requests by endpoint",
    ["chain_id", "endpoint", "status"],
)
INGEST_REQ_LATENCY = Histogram(
    "cm_ingestion_request_latency_seconds",
    "Ingestion HTTP request latency seconds",
    ["chain_id", "endpoint"],
)
INGEST_RETRY_TOTAL = Counter(
    "cm_ingestion_retries_total",
    "Total ingestion retries",
    ["chain_id", "endpoint"],
)
INGEST_RATE_LIMIT_TOTAL = Counter(
    "cm_ingestion_rate_limited_total",
    "Total ingestion rate-limited events",
    ["chain_id", "endpoint"],
)
INGEST_ERROR_TOTAL = Counter(
    "cm_ingestion_errors_total",
    "Total ingestion errors by reason",
    ["chain_id", "reason"],
)
INGEST_CIRCUIT_OPEN_SECONDS = Counter(
    "cm_ingestion_circuit_open_seconds_total",
    "Total blocked seconds due to open circuit",
    ["chain_id", "endpoint"],
)
INGEST_CIRCUIT_OPEN = Gauge(
    "cm_ingestion_circuit_open",
    "Whether ingestion circuit breaker is open (1=true)",
    ["chain_id", "endpoint"],
)
INGEST_CACHE_LOOKUP_TOTAL = Counter(
    "cm_ingestion_cache_lookups_total",
    "Total ingestion cache lookups",
    ["chain_id", "result"],
)
INGEST_CACHE_HIT_RATIO = Gauge(
    "cm_ingestion_cache_hit_ratio",
    "Ingestion cache hit ratio",
    ["chain_id"],
)


@dataclass(frozen=True)
class _CacheEntry:
    expire_at: float
    payload: dict


class ResilientHttpClient:
    def __init__(
        self,
        chain_id: str,
        settings: Settings,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chain_id = chain_id
        self._settings = settings
        self._headers = headers or {}
        self._bucket = AsyncTokenBucket(
            rate_per_second=self._settings.get_market_data_rate_limit_per_second(
                chain_id=self._chain_id
            ),
            capacity=self._settings.market_data_rate_limit_capacity,
        )
        self._breakers: dict[str, AsyncCircuitBreaker] = {}
        self._breaker_lock = asyncio.Lock()
        self._blocked_since_by_endpoint: dict[str, float] = {}
        self._blocked_since_lock = asyncio.Lock()
        self._cache_ttl_seconds = max(0.0, self._settings.market_data_cache_ttl_seconds)
        self._cache_max_entries = max(1, int(self._settings.market_data_cache_max_entries))
        self._cache_namespace = "cm:ingestion:v1"
        self._redis_timeout_seconds = 0.2
        self._redis_client = self._build_redis_client()
        self._response_cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_metrics_lock = Lock()
        self._inflight_requests: dict[str, asyncio.Future[dict | None]] = {}
        self._inflight_lock = asyncio.Lock()
        self._http_client: AsyncClient | None = None
        self._http_client_lock = asyncio.Lock()
        self._http_client_timeout = max(0.5, self._settings.market_data_timeout_seconds)
        self._http_client_limits = httpx.Limits(
            max_connections=max(1, self._settings.market_data_http_max_connections),
            max_keepalive_connections=max(
                1, self._settings.market_data_http_max_keepalive_connections
            ),
            keepalive_expiry=max(1.0, self._settings.market_data_http_keepalive_expiry_seconds),
        )

    async def get_json(
        self,
        url: str,
        endpoint: str,
        trace_id: str,
        trace: str,
    ) -> dict | None:
        cached = await self._cache_get(url=url)
        if cached is not None:
            INGEST_REQ_TOTAL.labels(
                chain_id=self._chain_id, endpoint=endpoint, status="cache_hit"
            ).inc()
            return cached

        leader_future, is_leader = await self._inflight_acquire(url=url)
        if not is_leader:
            INGEST_REQ_TOTAL.labels(
                chain_id=self._chain_id, endpoint=endpoint, status="singleflight_wait"
            ).inc()
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
            await self._inflight_release(url=url, holder=leader_future)

    async def _request_json_uncached(
        self,
        url: str,
        endpoint: str,
        trace_id: str,
        trace: str,
    ) -> dict | None:
        breaker = await self._breaker_for_endpoint(endpoint=endpoint)
        now = monotonic()
        if not await breaker.allow_request():
            INGEST_CIRCUIT_OPEN.labels(chain_id=self._chain_id, endpoint=endpoint).set(1)
            await self._record_circuit_blocked(endpoint=endpoint, now=now)
            INGEST_REQ_TOTAL.labels(
                chain_id=self._chain_id, endpoint=endpoint, status="blocked"
            ).inc()
            INGEST_ERROR_TOTAL.labels(chain_id=self._chain_id, reason="circuit_open").inc()
            return None
        await self._clear_circuit_blocked(endpoint=endpoint)
        INGEST_CIRCUIT_OPEN.labels(chain_id=self._chain_id, endpoint=endpoint).set(0)
        max_attempts = self._settings.get_market_data_retry_attempts(chain_id=self._chain_id)
        backoff = max(0.05, self._settings.market_data_retry_base_seconds)
        for attempt in range(1, max_attempts + 1):
            try:
                await self._bucket.acquire()
                started = asyncio.get_running_loop().time()
                client = await self._get_http_client()
                response = await client.get(url)
                INGEST_REQ_LATENCY.labels(chain_id=self._chain_id, endpoint=endpoint).observe(
                    asyncio.get_running_loop().time() - started
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    if response.status_code == 429:
                        INGEST_RATE_LIMIT_TOTAL.labels(
                            chain_id=self._chain_id, endpoint=endpoint
                        ).inc()
                    raise httpx.HTTPStatusError(
                        f"retryable status={response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("unexpected non-dict payload")
                INGEST_REQ_TOTAL.labels(
                    chain_id=self._chain_id, endpoint=endpoint, status="success"
                ).inc()
                await breaker.record_success()
                await self._cache_set(url=url, payload=payload)
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                INGEST_REQ_TOTAL.labels(
                    chain_id=self._chain_id, endpoint=endpoint, status="error"
                ).inc()
                reason = self._error_reason(exc)
                INGEST_ERROR_TOTAL.labels(chain_id=self._chain_id, reason=reason).inc()
                if not self._is_retryable_exception(exc):
                    logger.warning(
                        "ingestion request fail-fast chain=%s trace_id=%s trace=%s reason=%s: %s",
                        self._chain_id,
                        trace_id,
                        trace,
                        reason,
                        exc,
                    )
                    await breaker.record_failure()
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
                    return None
                INGEST_RETRY_TOTAL.labels(chain_id=self._chain_id, endpoint=endpoint).inc()
                sleep_seconds = self._retry_sleep_seconds(
                    exc=exc,
                    base_backoff=backoff,
                    attempt=attempt,
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
        async with self._breaker_lock:
            breaker = self._breakers.get(endpoint)
            if breaker is None:
                breaker = AsyncCircuitBreaker(
                    failure_threshold=self._settings.get_market_data_circuit_failure_threshold(
                        chain_id=self._chain_id
                    ),
                    recovery_seconds=self._settings.get_market_data_circuit_recovery_seconds(
                        chain_id=self._chain_id
                    ),
                    half_open_max_calls=self._settings.market_data_circuit_half_open_max_calls,
                )
                self._breakers[endpoint] = breaker
            return breaker

    async def _cache_get(self, url: str) -> dict | None:
        if self._cache_ttl_seconds <= 0:
            return None
        now = monotonic()
        async with self._cache_lock:
            entry = self._response_cache.get(url)
            if entry is None:
                cached_payload = None
            elif entry.expire_at <= now:
                self._response_cache.pop(url, None)
                cached_payload = None
            else:
                self._response_cache.pop(url, None)
                self._response_cache[url] = entry
                cached_payload = entry.payload
        if cached_payload is not None:
            self._record_cache_lookup(hit=True)
            return cached_payload
        if self._redis_client is None:
            self._record_cache_lookup(hit=False)
            return None
        try:
            key = self._cache_key(url)
            raw = await asyncio.wait_for(
                self._redis_client.get(key), timeout=self._redis_timeout_seconds
            )
            if not raw:
                self._record_cache_lookup(hit=False)
                return None
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                self._record_cache_lookup(hit=False)
                return None
            expire_at = monotonic() + self._cache_ttl_seconds
            async with self._cache_lock:
                self._response_cache[url] = _CacheEntry(expire_at=expire_at, payload=payload)
                self._cache_compact_locked()
            self._record_cache_lookup(hit=True)
            return payload
        except Exception:
            self._record_cache_lookup(hit=False)
            logger.debug(
                "redis cache get failed chain=%s key=%s", self._chain_id, key, exc_info=True
            )
            return None

    async def _cache_set(self, url: str, payload: dict) -> None:
        if self._cache_ttl_seconds <= 0:
            return
        key = self._cache_key(url)
        expire_at = monotonic() + self._cache_ttl_seconds
        async with self._cache_lock:
            self._response_cache.pop(url, None)
            self._response_cache[url] = _CacheEntry(expire_at=expire_at, payload=payload)
            self._cache_compact_locked()
        if self._redis_client is None:
            return
        ttl_seconds = max(1, int(self._cache_ttl_seconds))
        try:
            serialized = json.dumps(payload, separators=(",", ":"))
            await asyncio.wait_for(
                self._redis_client.setex(key, ttl_seconds, serialized),
                timeout=self._redis_timeout_seconds,
            )
        except Exception:
            logger.debug(
                "redis cache set failed chain=%s key=%s", self._chain_id, key, exc_info=True
            )

    async def _inflight_acquire(self, url: str) -> tuple[asyncio.Future[dict | None], bool]:
        async with self._inflight_lock:
            holder = self._inflight_requests.get(url)
            if holder is not None:
                return holder, False
            loop = asyncio.get_running_loop()
            holder = loop.create_future()
            self._inflight_requests[url] = holder
            return holder, True

    async def _inflight_release(self, url: str, holder: asyncio.Future[dict | None]) -> None:
        async with self._inflight_lock:
            current = self._inflight_requests.get(url)
            if current is holder:
                self._inflight_requests.pop(url, None)

    async def _record_circuit_blocked(self, endpoint: str, now: float) -> None:
        async with self._blocked_since_lock:
            last_blocked_seen = self._blocked_since_by_endpoint.get(endpoint)
            if last_blocked_seen is None:
                self._blocked_since_by_endpoint[endpoint] = now
                return
            blocked_seconds = max(0.0, now - last_blocked_seen)
            if blocked_seconds > 0:
                INGEST_CIRCUIT_OPEN_SECONDS.labels(chain_id=self._chain_id, endpoint=endpoint).inc(
                    blocked_seconds
                )
            self._blocked_since_by_endpoint[endpoint] = now

    async def _clear_circuit_blocked(self, endpoint: str) -> None:
        async with self._blocked_since_lock:
            self._blocked_since_by_endpoint.pop(endpoint, None)

    async def aclose(self) -> None:
        async with self._http_client_lock:
            if self._http_client is not None:
                await self._http_client.aclose()
                self._http_client = None
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception:
                logger.debug("redis client close failed chain=%s", self._chain_id, exc_info=True)

    async def __aenter__(self) -> ResilientHttpClient:
        await self._get_http_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.aclose()

    def _cache_key(self, url: str) -> str:
        digest = sha256(f"{self._chain_id}:{url}".encode()).hexdigest()
        return f"{self._cache_namespace}:{self._chain_id}:{digest}"

    def _cache_compact_locked(self) -> None:
        while len(self._response_cache) > self._cache_max_entries:
            self._response_cache.popitem(last=False)

    def _record_cache_lookup(self, hit: bool) -> None:
        with self._cache_metrics_lock:
            if hit:
                self._cache_hits += 1
                INGEST_CACHE_LOOKUP_TOTAL.labels(chain_id=self._chain_id, result="hit").inc()
            else:
                self._cache_misses += 1
                INGEST_CACHE_LOOKUP_TOTAL.labels(chain_id=self._chain_id, result="miss").inc()
            total = self._cache_hits + self._cache_misses
            if total > 0:
                INGEST_CACHE_HIT_RATIO.labels(chain_id=self._chain_id).set(self._cache_hits / total)

    def _build_redis_client(self):  # noqa: ANN202
        if redis_asyncio is None:
            return None
        redis_url = self._settings.redis_url.strip()
        if not redis_url:
            return None
        try:
            return redis_asyncio.from_url(redis_url, encoding="utf-8", decode_responses=True)
        except Exception:
            logger.warning(
                "redis cache disabled due to client init failure chain=%s",
                self._chain_id,
                exc_info=True,
            )
            return None

    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code if exc.response is not None else 0
            return code in {429, 500, 502, 503, 504}
        if isinstance(exc, httpx.HTTPError):
            return True
        return False

    @staticmethod
    def _error_reason(exc: Exception) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code if exc.response is not None else 0
            if code == 429:
                return "rate_limited"
            if 500 <= code <= 599:
                return "upstream_5xx"
            return f"http_{code}"
        if isinstance(exc, httpx.HTTPError):
            return "transport_error"
        return "parse_error"

    @staticmethod
    def _retry_after_seconds(response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            try:
                retry_after_dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
            if retry_after_dt.tzinfo is None:
                retry_after_dt = retry_after_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
            value = (retry_after_dt - datetime.now(tz=retry_after_dt.tzinfo)).total_seconds()
        if value <= 0:
            return None
        return value

    def _retry_sleep_seconds(self, exc: Exception, base_backoff: float, attempt: int) -> float:
        retry_after_seconds: float | None = None
        if (
            isinstance(exc, httpx.HTTPStatusError)
            and exc.response is not None
            and exc.response.status_code == 429
        ):
            retry_after_seconds = self._retry_after_seconds(exc.response)
        max_sleep_seconds = max(0.05, float(self._settings.market_data_retry_max_sleep_seconds))
        if retry_after_seconds is not None:
            return min(max_sleep_seconds, retry_after_seconds)
        jitter = random.uniform(0.0, base_backoff)
        return min(max_sleep_seconds, base_backoff * (2 ** (attempt - 1)) + jitter)
