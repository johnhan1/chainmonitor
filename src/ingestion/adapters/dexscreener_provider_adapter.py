from __future__ import annotations

import asyncio
import logging
import math
from urllib.parse import quote_plus

from src.ingestion.contracts.normalized_pair import NormalizedPair
from src.ingestion.contracts.provider_adapter import ProviderAdapter
from src.ingestion.resilience.resilient_http_client import (
    INGEST_ERROR_TOTAL,
    ResilientHttpClient,
)
from src.shared.config import Settings

logger = logging.getLogger(__name__)


class DexScreenerProviderAdapter(ProviderAdapter):
    def __init__(self, chain_id: str, settings: Settings, http_client: ResilientHttpClient) -> None:
        self._chain_id = chain_id
        self._settings = settings
        self._http_client = http_client
        self._ds_chain_id = self._settings.get_dexscreener_chain_id(chain_id)
        self._max_concurrency = self._settings.get_market_data_max_concurrency(chain_id=chain_id)

    async def fetch_pairs_by_addresses(
        self,
        symbol_to_address: dict[str, str],
        trace_id: str,
    ) -> dict[str, NormalizedPair]:
        if not symbol_to_address:
            return {}
        normalized = {
            self._normalize_address(address): symbol.upper()
            for symbol, address in symbol_to_address.items()
            if address.strip()
        }
        addresses = list(normalized.keys())
        semaphore = asyncio.Semaphore(max(1, self._max_concurrency))
        tasks = [
            self._fetch_pairs_by_addresses_chunk(
                semaphore=semaphore,
                chunk=chunk,
                normalized=normalized,
                trace_id=trace_id,
            )
            for chunk in self._chunk(addresses, size=20)
        ]
        results: dict[str, NormalizedPair] = {}
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
        for chunk_result in chunk_results:
            if isinstance(chunk_result, Exception):
                INGEST_ERROR_TOTAL.labels(
                    chain_id=self._chain_id, reason="address_chunk_task_error"
                ).inc()
                logger.warning(
                    "address chunk fetch task failed chain=%s trace_id=%s error=%s",
                    self._chain_id,
                    trace_id,
                    chunk_result,
                )
                continue
            results.update(chunk_result)
        return results

    async def fetch_pair_by_symbol(self, symbol: str, trace_id: str) -> NormalizedPair | None:
        symbol_upper = symbol.upper()
        url = f"https://api.dexscreener.com/latest/dex/search?q={quote_plus(symbol_upper)}"
        payload = await self._http_client.get_json(
            url=url,
            endpoint="search",
            trace_id=trace_id,
            trace=f"symbol:{symbol_upper}",
        )
        if payload is None:
            return None
        pairs = payload.get("pairs", [])
        if not isinstance(pairs, list):
            INGEST_ERROR_TOTAL.labels(chain_id=self._chain_id, reason="invalid_pairs_payload").inc()
            return None
        candidates = self._filter_symbol_candidates(symbol=symbol_upper, pairs=pairs)
        if not candidates:
            return None
        best_pair = self._pick_best_pair(candidates)
        return self._normalize_pair(raw_pair=best_pair, symbol=symbol_upper)

    async def _fetch_pairs_by_addresses_chunk(
        self,
        semaphore: asyncio.Semaphore,
        chunk: list[str],
        normalized: dict[str, str],
        trace_id: str,
    ) -> dict[str, NormalizedPair]:
        async with semaphore:
            token_path = ",".join(chunk)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_path}"
            payload = await self._http_client.get_json(
                url=url,
                endpoint="tokens",
                trace_id=trace_id,
                trace=f"address:{len(chunk)}",
            )
        if payload is None:
            return {}
        pairs = payload.get("pairs", [])
        if not isinstance(pairs, list):
            INGEST_ERROR_TOTAL.labels(chain_id=self._chain_id, reason="invalid_pairs_payload").inc()
            return {}

        grouped: dict[str, list[dict]] = {}
        for raw_pair in pairs:
            if raw_pair.get("chainId") != self._ds_chain_id:
                continue
            base_address = self._normalize_address(
                str(raw_pair.get("baseToken", {}).get("address", ""))
            )
            if not base_address or base_address not in normalized:
                continue
            grouped.setdefault(base_address, []).append(raw_pair)

        rows: dict[str, NormalizedPair] = {}
        for address, address_pairs in grouped.items():
            symbol = normalized[address]
            best_pair = self._pick_best_pair(address_pairs)
            pair = self._normalize_pair(raw_pair=best_pair, symbol=symbol)
            if pair is not None:
                rows[symbol] = pair
        return rows

    def _filter_symbol_candidates(self, symbol: str, pairs: list[dict]) -> list[dict]:
        candidates: list[dict] = []
        for pair in pairs:
            if pair.get("chainId") != self._ds_chain_id:
                continue
            base_symbol = str(pair.get("baseToken", {}).get("symbol", "")).upper()
            if base_symbol != symbol:
                continue
            candidates.append(pair)
        return candidates

    def _normalize_pair(self, raw_pair: dict, symbol: str) -> NormalizedPair | None:
        price_usd = self._safe_float(raw_pair.get("priceUsd"), default=None)
        volume_5m = self._safe_float(raw_pair.get("volume", {}).get("m5"), default=None)
        liquidity_usd = self._safe_float(raw_pair.get("liquidity", {}).get("usd"), default=None)
        buys_5m = self._safe_float(raw_pair.get("txns", {}).get("m5", {}).get("buys"), default=None)
        sells_5m = self._safe_float(
            raw_pair.get("txns", {}).get("m5", {}).get("sells"), default=None
        )
        if (
            price_usd is None
            or volume_5m is None
            or liquidity_usd is None
            or buys_5m is None
            or sells_5m is None
        ):
            INGEST_ERROR_TOTAL.labels(chain_id=self._chain_id, reason="invalid_pair_numeric").inc()
            return None
        pair_created_at = raw_pair.get("pairCreatedAt")
        pair_created_at_ms = None
        if pair_created_at is not None:
            try:
                pair_created_at_ms = int(float(pair_created_at))
            except (TypeError, ValueError):
                pair_created_at_ms = None
        return NormalizedPair(
            chain_id=self._chain_id,
            symbol=symbol,
            source="dexscreener",
            price_usd=price_usd,
            volume_5m=volume_5m,
            liquidity_usd=liquidity_usd,
            buys_5m=max(0, int(buys_5m)),
            sells_5m=max(0, int(sells_5m)),
            pair_created_at_ms=pair_created_at_ms,
            dex_id=str(raw_pair.get("dexId", "")),
            pair_address=str(raw_pair.get("pairAddress", "")),
            url=str(raw_pair.get("url", "")),
            base_token_address=self._normalize_address(
                str(raw_pair.get("baseToken", {}).get("address", ""))
            )
            or None,
        )

    @staticmethod
    def _pick_best_pair(candidates: list[dict]) -> dict:
        candidates.sort(
            key=lambda item: DexScreenerProviderAdapter._safe_float(
                item.get("liquidity", {}).get("usd"), default=0.0
            )
            or 0.0,
            reverse=True,
        )
        return candidates[0]

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
    def _normalize_address(address: str) -> str:
        if address.startswith("0x"):
            return address.lower()
        return address

    @staticmethod
    def _chunk(items: list[str], size: int) -> list[list[str]]:
        if size <= 0:
            return [items]
        return [items[idx : idx + size] for idx in range(0, len(items), size)]

    async def aclose(self) -> None:
        await self._http_client.aclose()
