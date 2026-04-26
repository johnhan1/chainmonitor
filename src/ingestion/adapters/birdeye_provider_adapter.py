from __future__ import annotations

import asyncio
import logging
import math
from urllib.parse import quote_plus

from src.ingestion.contracts.normalized_pair import NormalizedPair
from src.ingestion.contracts.provider_adapter import ProviderAdapter
from src.ingestion.resilience.resilient_http_client import INGEST_ERROR_TOTAL, ResilientHttpClient
from src.shared.config import Settings

logger = logging.getLogger(__name__)
PROVIDER = "birdeye"


class BirdeyeProviderAdapter(ProviderAdapter):
    def __init__(self, chain_id: str, settings: Settings, http_client: ResilientHttpClient) -> None:
        self._chain_id = chain_id
        self._settings = settings
        self._http_client = http_client
        self._api_base = self._settings.market_data_birdeye_api_base.rstrip("/")
        self._birdeye_chain = self._settings.get_birdeye_chain(chain_id=chain_id)
        self._max_concurrency = self._settings.get_market_data_max_concurrency(chain_id=chain_id)

    async def fetch_pairs_by_addresses(
        self,
        symbol_to_address: dict[str, str],
        trace_id: str,
    ) -> dict[str, NormalizedPair]:
        if not symbol_to_address:
            return {}
        semaphore = asyncio.Semaphore(max(1, self._max_concurrency))
        tasks = [
            self._fetch_by_address(
                semaphore=semaphore,
                symbol=symbol.upper(),
                address=self._normalize_address(address),
                trace_id=trace_id,
            )
            for symbol, address in symbol_to_address.items()
            if address.strip()
        ]
        rows: dict[str, NormalizedPair] = {}
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                INGEST_ERROR_TOTAL.labels(
                    chain_id=self._chain_id,
                    provider=PROVIDER,
                    reason="birdeye_address_task_error",
                ).inc()
                logger.warning(
                    "birdeye address task failed chain=%s trace_id=%s error=%s",
                    self._chain_id,
                    trace_id,
                    result,
                )
                continue
            symbol, pair = result
            if pair is not None:
                rows[symbol] = pair
        return rows

    async def fetch_pair_by_symbol(self, symbol: str, trace_id: str) -> NormalizedPair | None:
        symbol_upper = symbol.upper()
        search_url = (
            f"{self._api_base}/v3/search?keyword={quote_plus(symbol_upper)}"
            f"&chain={quote_plus(self._birdeye_chain)}"
        )
        payload = await self._http_client.get_json(
            url=search_url,
            endpoint="birdeye_search",
            trace_id=trace_id,
            trace=f"symbol:{symbol_upper}",
        )
        if payload is None:
            return None
        data = payload.get("data", {})
        if not isinstance(data, dict):
            return None
        items = data.get("items", [])
        if not isinstance(items, list):
            return None
        address = ""
        for item in items:
            if not isinstance(item, dict):
                continue
            item_symbol = str(item.get("symbol", "")).upper()
            if item_symbol != symbol_upper:
                continue
            address = self._normalize_address(str(item.get("address", "")))
            if address:
                break
        if not address:
            return None
        return await self._fetch_market_data(
            symbol=symbol_upper, address=address, trace_id=trace_id
        )

    async def _fetch_by_address(
        self,
        semaphore: asyncio.Semaphore,
        symbol: str,
        address: str,
        trace_id: str,
    ) -> tuple[str, NormalizedPair | None]:
        async with semaphore:
            pair = await self._fetch_market_data(symbol=symbol, address=address, trace_id=trace_id)
        return symbol, pair

    async def _fetch_market_data(
        self,
        symbol: str,
        address: str,
        trace_id: str,
    ) -> NormalizedPair | None:
        url = (
            f"{self._api_base}/v3/token/market-data?address={quote_plus(address)}"
            f"&chain={quote_plus(self._birdeye_chain)}"
        )
        payload = await self._http_client.get_json(
            url=url,
            endpoint="birdeye_token_market",
            trace_id=trace_id,
            trace=f"address:{symbol}",
        )
        if payload is None:
            return None
        data = payload.get("data", {})
        if not isinstance(data, dict):
            INGEST_ERROR_TOTAL.labels(
                chain_id=self._chain_id,
                provider=PROVIDER,
                reason="invalid_birdeye_payload",
            ).inc()
            return None
        price_usd = self._safe_float(data.get("price"), default=None)
        liquidity_usd = self._safe_float(
            data.get("liquidity"),
            default=self._safe_float(data.get("liquidity_usd"), default=None),
        )
        volume_24h = self._safe_float(data.get("volume24h"), default=None)
        trade_24h = self._safe_float(data.get("trade24h"), default=None)
        if price_usd is None or liquidity_usd is None or volume_24h is None or trade_24h is None:
            INGEST_ERROR_TOTAL.labels(
                chain_id=self._chain_id,
                provider=PROVIDER,
                reason="invalid_pair_numeric",
            ).inc()
            return None
        volume_5m = max(0.0, volume_24h / 288.0)
        tx_5m = max(0, int(trade_24h / 288.0))
        created_at_ms = self._extract_created_at_ms(data=data)
        return NormalizedPair(
            chain_id=self._chain_id,
            symbol=symbol,
            source="birdeye",
            price_usd=price_usd,
            volume_5m=volume_5m,
            liquidity_usd=max(0.0, liquidity_usd),
            buys_5m=max(0, tx_5m // 2),
            sells_5m=max(0, tx_5m - (tx_5m // 2)),
            pair_created_at_ms=created_at_ms,
            dex_id=str(data.get("dex", "birdeye")),
            pair_address=address,
            url=str(data.get("url", "")),
            base_token_address=address,
        )

    @staticmethod
    def _extract_created_at_ms(data: dict) -> int | None:
        candidates = [data.get("createdAt"), data.get("createTime"), data.get("listedAt")]
        for candidate in candidates:
            parsed = BirdeyeProviderAdapter._safe_float(candidate, default=None)
            if parsed is None:
                continue
            if parsed > 10_000_000_000:
                return int(parsed)
            return int(parsed * 1000.0)
        return None

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

    async def aclose(self) -> None:
        await self._http_client.aclose()
