from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic

from src.ingestion.resilience.metrics import ResilienceMetrics

try:
    import redis.asyncio as redis_asyncio
except Exception:  # pragma: no cover - optional dependency
    redis_asyncio = None

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CacheEntry:
    expire_at: float
    payload: dict


class ResponseCacheStore:
    def __init__(
        self,
        chain_id: str,
        provider: str,
        redis_url: str,
        ttl_seconds: float,
        max_entries: int,
        metrics: ResilienceMetrics,
        namespace: str = "cm:ingestion:v1",
        redis_timeout_seconds: float = 0.2,
    ) -> None:
        self._chain_id = chain_id
        self._provider = provider.strip().lower()
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._max_entries = max(1, int(max_entries))
        self._metrics = metrics
        self._cache_namespace = namespace
        self._redis_timeout_seconds = redis_timeout_seconds
        self._redis_url = redis_url.strip()
        self._redis_client = self._build_redis_client()
        self._response_cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._cache_lock = asyncio.Lock()

    async def get(self, url: str) -> dict | None:
        if self._ttl_seconds <= 0:
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
            self._metrics.cache_lookup(hit=True)
            return cached_payload
        if self._redis_client is None:
            self._metrics.cache_lookup(hit=False)
            return None
        try:
            key = self._cache_key(url)
            raw = await asyncio.wait_for(
                self._redis_client.get(key),
                timeout=self._redis_timeout_seconds,
            )
            if not raw:
                self._metrics.cache_lookup(hit=False)
                return None
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                self._metrics.cache_lookup(hit=False)
                return None
            expire_at = monotonic() + self._ttl_seconds
            async with self._cache_lock:
                self._response_cache[url] = _CacheEntry(expire_at=expire_at, payload=payload)
                self._compact_locked()
            self._metrics.cache_lookup(hit=True)
            return payload
        except Exception:
            self._metrics.cache_lookup(hit=False)
            logger.debug(
                "redis cache get failed chain=%s key=%s",
                self._chain_id,
                key,
                exc_info=True,
            )
            return None

    async def set(self, url: str, payload: dict) -> None:
        if self._ttl_seconds <= 0:
            return
        key = self._cache_key(url)
        expire_at = monotonic() + self._ttl_seconds
        async with self._cache_lock:
            self._response_cache.pop(url, None)
            self._response_cache[url] = _CacheEntry(expire_at=expire_at, payload=payload)
            self._compact_locked()
        if self._redis_client is None:
            return
        ttl_seconds = max(1, int(self._ttl_seconds))
        try:
            serialized = json.dumps(payload, separators=(",", ":"))
            await asyncio.wait_for(
                self._redis_client.setex(key, ttl_seconds, serialized),
                timeout=self._redis_timeout_seconds,
            )
        except Exception:
            logger.debug(
                "redis cache set failed chain=%s key=%s",
                self._chain_id,
                key,
                exc_info=True,
            )

    async def aclose(self) -> None:
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception:
                logger.debug("redis client close failed chain=%s", self._chain_id, exc_info=True)

    def _cache_key(self, url: str) -> str:
        digest = sha256(f"{self._provider}:{self._chain_id}:{url}".encode()).hexdigest()
        return f"{self._cache_namespace}:{self._provider}:{self._chain_id}:{digest}"

    def _compact_locked(self) -> None:
        while len(self._response_cache) > self._max_entries:
            self._response_cache.popitem(last=False)

    def _build_redis_client(self):  # noqa: ANN202
        if redis_asyncio is None:
            return None
        if not self._redis_url:
            return None
        try:
            return redis_asyncio.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception:
            logger.warning(
                "redis cache disabled due to client init failure chain=%s",
                self._chain_id,
                exc_info=True,
            )
            return None
