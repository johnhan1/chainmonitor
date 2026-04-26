from __future__ import annotations

from threading import Lock

from prometheus_client import Counter, Gauge, Histogram

INGEST_REQ_TOTAL = Counter(
    "cm_ingestion_requests_total",
    "Total ingestion HTTP requests by endpoint",
    ["chain_id", "provider", "endpoint", "status"],
)
INGEST_REQ_LATENCY = Histogram(
    "cm_ingestion_request_latency_seconds",
    "Ingestion HTTP request latency seconds",
    ["chain_id", "provider", "endpoint"],
)
INGEST_RETRY_TOTAL = Counter(
    "cm_ingestion_retries_total",
    "Total ingestion retries",
    ["chain_id", "provider", "endpoint"],
)
INGEST_RATE_LIMIT_TOTAL = Counter(
    "cm_ingestion_rate_limited_total",
    "Total ingestion rate-limited events",
    ["chain_id", "provider", "endpoint"],
)
INGEST_ERROR_TOTAL = Counter(
    "cm_ingestion_errors_total",
    "Total ingestion errors by reason",
    ["chain_id", "provider", "reason"],
)
INGEST_CIRCUIT_OPEN_SECONDS = Counter(
    "cm_ingestion_circuit_open_seconds_total",
    "Total blocked seconds due to open circuit",
    ["chain_id", "provider", "endpoint"],
)
INGEST_CIRCUIT_OPEN = Gauge(
    "cm_ingestion_circuit_open",
    "Whether ingestion circuit breaker is open (1=true)",
    ["chain_id", "provider", "endpoint"],
)
INGEST_CACHE_LOOKUP_TOTAL = Counter(
    "cm_ingestion_cache_lookups_total",
    "Total ingestion cache lookups",
    ["chain_id", "provider", "result"],
)
INGEST_CACHE_HIT_RATIO = Gauge(
    "cm_ingestion_cache_hit_ratio",
    "Ingestion cache hit ratio",
    ["chain_id", "provider"],
)


class ResilienceMetrics:
    def __init__(self, chain_id: str, provider: str) -> None:
        self._chain_id = chain_id
        self._provider = provider.strip().lower()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_metrics_lock = Lock()

    def request(self, endpoint: str, status: str) -> None:
        INGEST_REQ_TOTAL.labels(
            chain_id=self._chain_id,
            provider=self._provider,
            endpoint=endpoint,
            status=status,
        ).inc()

    def latency(self, endpoint: str, seconds: float) -> None:
        INGEST_REQ_LATENCY.labels(
            chain_id=self._chain_id,
            provider=self._provider,
            endpoint=endpoint,
        ).observe(seconds)

    def retry(self, endpoint: str) -> None:
        INGEST_RETRY_TOTAL.labels(
            chain_id=self._chain_id,
            provider=self._provider,
            endpoint=endpoint,
        ).inc()

    def rate_limited(self, endpoint: str) -> None:
        INGEST_RATE_LIMIT_TOTAL.labels(
            chain_id=self._chain_id,
            provider=self._provider,
            endpoint=endpoint,
        ).inc()

    def error(self, reason: str) -> None:
        INGEST_ERROR_TOTAL.labels(
            chain_id=self._chain_id,
            provider=self._provider,
            reason=reason,
        ).inc()

    def circuit_open_state(self, endpoint: str, opened: bool) -> None:
        INGEST_CIRCUIT_OPEN.labels(
            chain_id=self._chain_id,
            provider=self._provider,
            endpoint=endpoint,
        ).set(1 if opened else 0)

    def circuit_open_seconds(self, endpoint: str, blocked_seconds: float) -> None:
        INGEST_CIRCUIT_OPEN_SECONDS.labels(
            chain_id=self._chain_id,
            provider=self._provider,
            endpoint=endpoint,
        ).inc(blocked_seconds)

    def cache_lookup(self, hit: bool) -> None:
        with self._cache_metrics_lock:
            if hit:
                self._cache_hits += 1
                INGEST_CACHE_LOOKUP_TOTAL.labels(
                    chain_id=self._chain_id,
                    provider=self._provider,
                    result="hit",
                ).inc()
            else:
                self._cache_misses += 1
                INGEST_CACHE_LOOKUP_TOTAL.labels(
                    chain_id=self._chain_id,
                    provider=self._provider,
                    result="miss",
                ).inc()
            total = self._cache_hits + self._cache_misses
            if total > 0:
                INGEST_CACHE_HIT_RATIO.labels(
                    chain_id=self._chain_id,
                    provider=self._provider,
                ).set(self._cache_hits / total)
