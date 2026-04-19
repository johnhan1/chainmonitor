from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from threading import Lock
from time import monotonic, time
from urllib.parse import quote_plus
from uuid import uuid4

import httpx
from httpx import AsyncClient
from prometheus_client import Counter, Gauge, Histogram
from src.ingestion.chain_ingestion_source_base import ChainIngestionSourceBase
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.source_strategy import SourceStrategy
from src.ingestion.resilience.controls import AsyncCircuitBreaker, AsyncTokenBucket
from src.shared.schemas.pipeline import MarketTickInput

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
INGEST_ADDRESS_MAPPING_MISSING_TOTAL = Counter(
    "cm_ingestion_address_mapping_missing_total",
    "Total missing token address mappings",
    ["chain_id"],
)
INGEST_SUCCESS_RATIO = Gauge(
    "cm_ingestion_success_ratio",
    "Ratio of successful symbols in one ingestion run",
    ["chain_id"],
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


class DexScreenerSourceStrategy(ChainIngestionSourceBase, SourceStrategy):
    def __init__(self, chain_id: str, data_mode: str | None = None) -> None:
        super().__init__(chain_id=chain_id, data_mode=data_mode)
        self._bucket = AsyncTokenBucket(
            rate_per_second=self.settings.get_market_data_rate_limit_per_second(
                chain_id=self.chain_id
            ),
            capacity=self.settings.market_data_rate_limit_capacity,
        )
        self._breakers: dict[str, AsyncCircuitBreaker] = {}
        self._breaker_lock = asyncio.Lock()
        self._blocked_since_by_endpoint: dict[str, float] = {}
        self._blocked_since_lock = asyncio.Lock()
        self._cache_ttl_seconds = max(0.0, self.settings.market_data_cache_ttl_seconds)
        self._cache_max_entries = max(1, int(self.settings.market_data_cache_max_entries))
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
        self._http_client_timeout = max(0.5, self.settings.market_data_timeout_seconds)
        self._http_client_limits = httpx.Limits(
            max_connections=max(1, self.settings.market_data_http_max_connections),
            max_keepalive_connections=max(
                1, self.settings.market_data_http_max_keepalive_connections
            ),
            keepalive_expiry=max(1.0, self.settings.market_data_http_keepalive_expiry_seconds),
        )

    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        target_ts = self._normalize_ts(ts_minute)
        trace_id = uuid4().hex[:12]
        symbols = self._symbols()
        ds_chain_id = self.settings.get_dexscreener_chain_id(self.chain_id)
        max_concurrency = self.settings.get_market_data_max_concurrency(chain_id=self.chain_id)
        semaphore = asyncio.Semaphore(max_concurrency)
        client = await self._get_http_client()
        address_map = self.settings.get_chain_token_addresses(self.chain_id)
        required_address_symbols = self._required_address_symbols(symbols=symbols)
        self._validate_required_mappings(
            symbols=symbols,
            address_map=address_map,
            required_address_symbols=required_address_symbols,
            trace_id=trace_id,
        )
        live_pairs = await self._collect_live_pairs(
            client=client,
            semaphore=semaphore,
            ds_chain_id=ds_chain_id,
            symbols=symbols,
            address_map=address_map,
            required_address_symbols=required_address_symbols,
            trace_id=trace_id,
        )
        self._validate_success_ratio(
            symbols=symbols,
            live_pairs=live_pairs,
            trace_id=trace_id,
        )
        rows = self._build_rows(
            symbols=symbols,
            live_pairs=live_pairs,
            ts_minute=target_ts,
        )
        self._validate_required_rows(
            required_address_symbols=required_address_symbols,
            rows=rows,
            trace_id=trace_id,
        )
        if not rows:
            raise IngestionFetchError(
                reason="no_valid_rows",
                detail="all pairs filtered by quality gates",
                chain_id=self.chain_id,
                trace_id=trace_id,
            )
        return rows

    def _validate_required_mappings(
        self,
        symbols: list[str],
        address_map: dict[str, str],
        required_address_symbols: set[str],
        trace_id: str,
    ) -> None:
        missing_address_symbols = [symbol for symbol in symbols if symbol not in address_map]
        if missing_address_symbols:
            INGEST_ADDRESS_MAPPING_MISSING_TOTAL.labels(chain_id=self.chain_id).inc(
                len(missing_address_symbols)
            )
            logger.warning(
                "missing token address mapping chain=%s trace_id=%s symbols=%s",
                self.chain_id,
                trace_id,
                ",".join(missing_address_symbols),
            )
        missing_required_mapping = [
            symbol for symbol in required_address_symbols if symbol not in address_map
        ]
        if missing_required_mapping:
            detail = f"symbols={','.join(sorted(missing_required_mapping))}"
            INGEST_ERROR_TOTAL.labels(
                chain_id=self.chain_id, reason="required_mapping_missing"
            ).inc()
            raise IngestionFetchError(
                reason="required_mapping_missing",
                detail=detail,
                chain_id=self.chain_id,
                trace_id=trace_id,
            )

    async def _collect_live_pairs(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        ds_chain_id: str,
        symbols: list[str],
        address_map: dict[str, str],
        required_address_symbols: set[str],
        trace_id: str,
    ) -> dict[str, dict]:
        live_pairs: dict[str, dict] = {}
        if address_map:
            address_pairs = await self._fetch_pairs_by_addresses(
                client=client,
                ds_chain_id=ds_chain_id,
                symbol_to_address=address_map,
                trace_id=trace_id,
            )
            live_pairs.update(address_pairs)
        unresolved_required = [
            symbol for symbol in required_address_symbols if symbol not in live_pairs
        ]
        if unresolved_required:
            detail = f"symbols={','.join(sorted(unresolved_required))}"
            INGEST_ERROR_TOTAL.labels(
                chain_id=self.chain_id, reason="required_symbol_unresolved"
            ).inc()
            raise IngestionFetchError(
                reason="required_symbol_unresolved",
                detail=detail,
                chain_id=self.chain_id,
                trace_id=trace_id,
            )

        remaining_symbols = [
            symbol
            for symbol in symbols
            if symbol not in live_pairs and symbol not in required_address_symbols
        ]
        if not remaining_symbols:
            return live_pairs
        tasks = [
            self._fetch_pair_by_symbol(
                client=client,
                semaphore=semaphore,
                ds_chain_id=ds_chain_id,
                symbol=symbol,
                trace_id=trace_id,
            )
            for symbol in remaining_symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="symbol_task_error").inc()
                logger.warning(
                    "symbol fetch task failed chain=%s trace_id=%s error=%s",
                    self.chain_id,
                    trace_id,
                    result,
                )
                continue
            symbol, pair = result
            if pair is not None:
                live_pairs[symbol] = pair
        return live_pairs

    def _validate_success_ratio(
        self,
        symbols: list[str],
        live_pairs: dict[str, dict],
        trace_id: str,
    ) -> None:
        min_success_ratio = self.settings.get_market_data_min_success_ratio(chain_id=self.chain_id)
        success_ratio = len(live_pairs) / max(1, len(symbols))
        INGEST_SUCCESS_RATIO.labels(chain_id=self.chain_id).set(success_ratio)
        if success_ratio < min_success_ratio:
            logger.warning(
                "ingestion success ratio too low chain=%s trace_id=%s ratio=%.3f threshold=%.3f",
                self.chain_id,
                trace_id,
                success_ratio,
                min_success_ratio,
            )
            raise IngestionFetchError(
                reason="insufficient_coverage",
                detail=f"ratio={success_ratio:.3f}, threshold={min_success_ratio:.3f}",
                chain_id=self.chain_id,
                trace_id=trace_id,
            )

    def _build_rows(
        self,
        symbols: list[str],
        live_pairs: dict[str, dict],
        ts_minute: datetime,
    ) -> list[MarketTickInput]:
        rows: list[MarketTickInput] = []
        for symbol in symbols:
            pair = live_pairs.get(symbol)
            if pair is None:
                continue
            if not self._pair_quality_ok(pair):
                continue
            tick = self._build_tick(symbol=symbol, ts_minute=ts_minute, pair=pair)
            if tick is None:
                continue
            rows.append(tick)
        return rows

    def _validate_required_rows(
        self,
        required_address_symbols: set[str],
        rows: list[MarketTickInput],
        trace_id: str,
    ) -> None:
        row_token_ids = {row.token_id for row in rows}
        missing_required_rows = [
            symbol
            for symbol in required_address_symbols
            if self._token_id(symbol) not in row_token_ids
        ]
        if missing_required_rows:
            detail = f"symbols={','.join(sorted(missing_required_rows))}"
            INGEST_ERROR_TOTAL.labels(
                chain_id=self.chain_id, reason="required_symbol_invalid"
            ).inc()
            raise IngestionFetchError(
                reason="required_symbol_invalid",
                detail=detail,
                chain_id=self.chain_id,
                trace_id=trace_id,
            )

    async def _fetch_pair_by_symbol(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        ds_chain_id: str,
        symbol: str,
        trace_id: str,
    ) -> tuple[str, dict | None]:
        async with semaphore:
            url = f"https://api.dexscreener.com/latest/dex/search?q={quote_plus(symbol)}"
            payload = await self._request_json(
                client=client,
                url=url,
                endpoint="search",
                trace_id=trace_id,
                trace=f"symbol:{symbol}",
            )
        if payload is None:
            return symbol, None
        pairs = payload.get("pairs", [])
        if not isinstance(pairs, list):
            INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="invalid_pairs_payload").inc()
            return symbol, None
        candidates = self._filter_symbol_candidates(
            ds_chain_id=ds_chain_id,
            symbol=symbol,
            pairs=pairs,
        )
        if not candidates:
            return symbol, None
        return symbol, self._pick_best_pair(candidates)

    async def _fetch_pairs_by_addresses(
        self,
        client: httpx.AsyncClient,
        ds_chain_id: str,
        symbol_to_address: dict[str, str],
        trace_id: str,
    ) -> dict[str, dict]:
        if not symbol_to_address:
            return {}
        normalized = {
            self._normalize_address(address): symbol
            for symbol, address in symbol_to_address.items()
        }
        addresses = list(normalized.keys())
        semaphore = asyncio.Semaphore(
            self.settings.get_market_data_max_concurrency(chain_id=self.chain_id)
        )
        tasks = [
            self._fetch_pairs_by_addresses_chunk(
                client=client,
                semaphore=semaphore,
                ds_chain_id=ds_chain_id,
                chunk=chunk,
                normalized=normalized,
                trace_id=trace_id,
            )
            for chunk in self._chunk(addresses, size=20)
        ]
        results: dict[str, dict] = {}
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
        for chunk_result in chunk_results:
            if isinstance(chunk_result, Exception):
                INGEST_ERROR_TOTAL.labels(
                    chain_id=self.chain_id, reason="address_chunk_task_error"
                ).inc()
                logger.warning(
                    "address chunk fetch task failed chain=%s trace_id=%s error=%s",
                    self.chain_id,
                    trace_id,
                    chunk_result,
                )
                continue
            results.update(chunk_result)
        return results

    async def _fetch_pairs_by_addresses_chunk(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        ds_chain_id: str,
        chunk: list[str],
        normalized: dict[str, str],
        trace_id: str,
    ) -> dict[str, dict]:
        async with semaphore:
            token_path = ",".join(chunk)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_path}"
            payload = await self._request_json(
                client=client,
                url=url,
                endpoint="tokens",
                trace_id=trace_id,
                trace=f"address:{len(chunk)}",
            )
        if payload is None:
            return {}
        pairs = payload.get("pairs", [])
        if not isinstance(pairs, list):
            INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="invalid_pairs_payload").inc()
            return {}
        grouped: dict[str, list[dict]] = {}
        for pair in pairs:
            if pair.get("chainId") != ds_chain_id:
                continue
            base_address = self._normalize_address(
                str(pair.get("baseToken", {}).get("address", ""))
            )
            if not base_address or base_address not in normalized:
                continue
            if not self._pair_quality_ok(pair):
                continue
            grouped.setdefault(base_address, []).append(pair)
        rows: dict[str, dict] = {}
        for address, address_pairs in grouped.items():
            symbol = normalized[address]
            rows[symbol] = self._pick_best_pair(address_pairs)
        return rows

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        endpoint: str,
        trace_id: str,
        trace: str,
    ) -> dict | None:
        cached = await self._cache_get(url=url)
        if cached is not None:
            INGEST_REQ_TOTAL.labels(
                chain_id=self.chain_id, endpoint=endpoint, status="cache_hit"
            ).inc()
            return cached

        leader_future, is_leader = await self._inflight_acquire(url=url)
        if not is_leader:
            INGEST_REQ_TOTAL.labels(
                chain_id=self.chain_id, endpoint=endpoint, status="singleflight_wait"
            ).inc()
            return await leader_future

        try:
            result = await self._request_json_uncached(
                client=client,
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
        client: httpx.AsyncClient,
        url: str,
        endpoint: str,
        trace_id: str,
        trace: str,
    ) -> dict | None:
        breaker = await self._breaker_for_endpoint(endpoint=endpoint)
        now = monotonic()
        if not await breaker.allow_request():
            INGEST_CIRCUIT_OPEN.labels(chain_id=self.chain_id, endpoint=endpoint).set(1)
            await self._record_circuit_blocked(endpoint=endpoint, now=now)
            INGEST_REQ_TOTAL.labels(
                chain_id=self.chain_id, endpoint=endpoint, status="blocked"
            ).inc()
            INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="circuit_open").inc()
            return None
        await self._clear_circuit_blocked(endpoint=endpoint)
        INGEST_CIRCUIT_OPEN.labels(chain_id=self.chain_id, endpoint=endpoint).set(0)
        max_attempts = self.settings.get_market_data_retry_attempts(chain_id=self.chain_id)
        backoff = max(0.05, self.settings.market_data_retry_base_seconds)
        for attempt in range(1, max_attempts + 1):
            try:
                await self._bucket.acquire()
                started = asyncio.get_running_loop().time()
                response = await client.get(url)
                INGEST_REQ_LATENCY.labels(chain_id=self.chain_id, endpoint=endpoint).observe(
                    asyncio.get_running_loop().time() - started
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    if response.status_code == 429:
                        INGEST_RATE_LIMIT_TOTAL.labels(
                            chain_id=self.chain_id, endpoint=endpoint
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
                    chain_id=self.chain_id, endpoint=endpoint, status="success"
                ).inc()
                await breaker.record_success()
                await self._cache_set(url=url, payload=payload)
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                INGEST_REQ_TOTAL.labels(
                    chain_id=self.chain_id, endpoint=endpoint, status="error"
                ).inc()
                reason = self._error_reason(exc)
                INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason=reason).inc()
                if not self._is_retryable_exception(exc):
                    logger.warning(
                        "dexscreener request fail-fast chain=%s trace_id=%s trace=%s reason=%s: %s",
                        self.chain_id,
                        trace_id,
                        trace,
                        reason,
                        exc,
                    )
                    await breaker.record_failure()
                    return None
                if attempt >= max_attempts:
                    logger.warning(
                        "dexscreener request failed chain=%s trace_id=%s trace=%s attempt=%s reason=%s: %s",  # noqa: E501
                        self.chain_id,
                        trace_id,
                        trace,
                        attempt,
                        reason,
                        exc,
                    )
                    await breaker.record_failure()
                    return None
                INGEST_RETRY_TOTAL.labels(chain_id=self.chain_id, endpoint=endpoint).inc()
                sleep_seconds = self._retry_sleep_seconds(
                    exc=exc,
                    base_backoff=backoff,
                    attempt=attempt,
                )
                await asyncio.sleep(sleep_seconds)
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

    def _build_tick(self, symbol: str, ts_minute: datetime, pair: dict) -> MarketTickInput | None:
        txns_m5 = pair.get("txns", {}).get("m5", {})
        volume = pair.get("volume", {})

        price_usd = self._safe_float(pair.get("priceUsd"), default=None)
        volume_5m = self._safe_float(volume.get("m5"), default=None)
        liquidity_usd = self._safe_float(pair.get("liquidity", {}).get("usd"), default=None)
        buys_5m = self._safe_float(txns_m5.get("buys", 0), default=None)
        sells_5m = self._safe_float(txns_m5.get("sells", 0), default=None)

        if (
            price_usd is None
            or volume_5m is None
            or liquidity_usd is None
            or buys_5m is None
            or sells_5m is None
        ):
            INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="invalid_pair_numeric").inc()
            return None
        if price_usd <= 0:
            INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="invalid_price").inc()
            return None
        if volume_5m < 0 or liquidity_usd < 0 or buys_5m < 0 or sells_5m < 0:
            INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="invalid_pair_range").inc()
            return None

        buys_1m = max(0, int(buys_5m / 5))
        sells_1m = max(0, int(sells_5m / 5))
        return MarketTickInput(
            chain_id=self.chain_id,
            token_id=self._token_id(symbol),
            ts_minute=ts_minute,
            price_usd=price_usd,
            volume_1m=max(0.0, volume_5m / 5.0),
            volume_5m=max(0.0, volume_5m),
            liquidity_usd=max(0.0, liquidity_usd),
            buys_1m=buys_1m,
            sells_1m=sells_1m,
            tx_count_1m=max(0, buys_1m + sells_1m),
        )

    def _filter_symbol_candidates(
        self, ds_chain_id: str, symbol: str, pairs: list[dict]
    ) -> list[dict]:
        candidates: list[dict] = []
        for pair in pairs:
            if pair.get("chainId") != ds_chain_id:
                continue
            base_symbol = str(pair.get("baseToken", {}).get("symbol", "")).upper()
            if base_symbol != symbol:
                continue
            if not self._pair_quality_ok(pair):
                continue
            candidates.append(pair)
        return candidates

    @staticmethod
    def _pick_best_pair(candidates: list[dict]) -> dict:
        candidates.sort(
            key=lambda item: DexScreenerSourceStrategy._safe_float(
                item.get("liquidity", {}).get("usd"), default=0.0
            )
            or 0.0,
            reverse=True,
        )
        return candidates[0]

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"User-Agent": "chainmonitor-phase1/1.0"}

    @staticmethod
    def _chunk(items: list[str], size: int) -> list[list[str]]:
        if size <= 0:
            return [items]
        return [items[idx : idx + size] for idx in range(0, len(items), size)]

    def _pair_quality_ok(self, pair: dict) -> bool:
        dex_id = str(pair.get("dexId", "")).lower()
        if dex_id and dex_id in self.settings.dex_blacklist_ids:
            return False

        pair_label = str(pair.get("pairAddress", "")).lower()
        url = str(pair.get("url", "")).lower()
        route_signal = f"{pair_label}|{url}"
        if any(keyword in route_signal for keyword in self.settings.route_blacklist_keywords):
            return False

        # pairCreatedAt is ms epoch for most DexScreener pairs.
        created_at_ms = pair.get("pairCreatedAt")
        if created_at_ms is None:
            return False
        try:
            age_seconds = time() - (float(created_at_ms) / 1000.0)
        except (TypeError, ValueError):
            return False
        min_age = self.settings.get_market_data_min_pair_age_seconds(chain_id=self.chain_id)
        if age_seconds < min_age:
            return False
        liquidity = self._safe_float(pair.get("liquidity", {}).get("usd"), default=0.0)
        volume_5m = self._safe_float(pair.get("volume", {}).get("m5"), default=0.0)
        if liquidity is None or volume_5m is None:
            return False
        max_ratio = self.settings.get_market_data_max_volume_liquidity_ratio(chain_id=self.chain_id)
        if liquidity > 0 and volume_5m / liquidity > max_ratio:
            return False
        return True

    @staticmethod
    def _normalize_address(address: str) -> str:
        if address.startswith("0x"):
            return address.lower()
        return address

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
    def _safe_float(value: object, default: float | None = None) -> float | None:
        if value is None:
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed

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
        max_sleep_seconds = max(0.05, float(self.settings.market_data_retry_max_sleep_seconds))
        if retry_after_seconds is not None:
            return min(max_sleep_seconds, retry_after_seconds)
        jitter = random.uniform(0.0, base_backoff)
        return min(max_sleep_seconds, base_backoff * (2 ** (attempt - 1)) + jitter)

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
                "redis cache get failed chain=%s key=%s", self.chain_id, key, exc_info=True
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
                "redis cache set failed chain=%s key=%s", self.chain_id, key, exc_info=True
            )

    def _cache_key(self, url: str) -> str:
        digest = sha256(f"{self.chain_id}:{url}".encode()).hexdigest()
        return f"{self._cache_namespace}:{self.chain_id}:{digest}"

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

    async def _get_http_client(self) -> AsyncClient:
        async with self._http_client_lock:
            if self._http_client is None or self._http_client.is_closed:
                self._http_client = httpx.AsyncClient(
                    timeout=self._http_client_timeout,
                    headers=self._headers(),
                    limits=self._http_client_limits,
                )
            return self._http_client

    async def _breaker_for_endpoint(self, endpoint: str) -> AsyncCircuitBreaker:
        async with self._breaker_lock:
            breaker = self._breakers.get(endpoint)
            if breaker is None:
                breaker = AsyncCircuitBreaker(
                    failure_threshold=self.settings.get_market_data_circuit_failure_threshold(
                        chain_id=self.chain_id
                    ),
                    recovery_seconds=self.settings.get_market_data_circuit_recovery_seconds(
                        chain_id=self.chain_id
                    ),
                    half_open_max_calls=self.settings.market_data_circuit_half_open_max_calls,
                )
                self._breakers[endpoint] = breaker
            return breaker

    def _required_address_symbols(self, symbols: list[str]) -> set[str]:
        symbol_set = set(symbols)
        configured = self.settings.get_market_data_required_address_symbols(chain_id=self.chain_id)
        if configured:
            return configured & symbol_set
        if (
            self.settings.is_production
            and self.settings.market_data_require_address_mapping_in_production
        ):
            return symbol_set
        return set()

    def _record_cache_lookup(self, hit: bool) -> None:
        with self._cache_metrics_lock:
            if hit:
                self._cache_hits += 1
                INGEST_CACHE_LOOKUP_TOTAL.labels(chain_id=self.chain_id, result="hit").inc()
            else:
                self._cache_misses += 1
                INGEST_CACHE_LOOKUP_TOTAL.labels(chain_id=self.chain_id, result="miss").inc()
            total = self._cache_hits + self._cache_misses
            if total > 0:
                INGEST_CACHE_HIT_RATIO.labels(chain_id=self.chain_id).set(self._cache_hits / total)

    def _cache_compact_locked(self) -> None:
        while len(self._response_cache) > self._cache_max_entries:
            self._response_cache.popitem(last=False)

    async def _record_circuit_blocked(self, endpoint: str, now: float) -> None:
        async with self._blocked_since_lock:
            last_blocked_seen = self._blocked_since_by_endpoint.get(endpoint)
            if last_blocked_seen is None:
                self._blocked_since_by_endpoint[endpoint] = now
                return
            blocked_seconds = max(0.0, now - last_blocked_seen)
            if blocked_seconds > 0:
                INGEST_CIRCUIT_OPEN_SECONDS.labels(chain_id=self.chain_id, endpoint=endpoint).inc(
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
                logger.debug("redis client close failed chain=%s", self.chain_id, exc_info=True)

    async def __aenter__(self) -> DexScreenerSourceStrategy:
        await self._get_http_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.aclose()

    def _build_redis_client(self):  # noqa: ANN202
        if redis_asyncio is None:
            return None
        redis_url = self.settings.redis_url.strip()
        if not redis_url:
            return None
        try:
            return redis_asyncio.from_url(redis_url, encoding="utf-8", decode_responses=True)
        except Exception:
            logger.warning(
                "redis cache disabled due to client init failure chain=%s",
                self.chain_id,
                exc_info=True,
            )
            return None
