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
PROVIDER = "geckoterminal"


class GeckoTerminalProviderAdapter(ProviderAdapter):
    def __init__(self, chain_id: str, settings: Settings, http_client: ResilientHttpClient) -> None:
        self._chain_id = chain_id
        self._settings = settings
        self._http_client = http_client
        self._network = self._settings.get_geckoterminal_network(chain_id=chain_id)
        self._api_base = self._settings.market_data_geckoterminal_api_base.rstrip("/")
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
            self._fetch_token_pools(
                semaphore=semaphore,
                symbol=symbol.upper(),
                token_address=self._normalize_address(address),
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
                    reason="geckoterminal_address_task_error",
                ).inc()
                logger.warning(
                    "geckoterminal address task failed chain=%s trace_id=%s error=%s",
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
        url = (
            f"{self._api_base}/search/pools"
            f"?query={quote_plus(symbol_upper)}&network={quote_plus(self._network)}"
        )
        payload = await self._http_client.get_json(
            url=url,
            endpoint="gecko_search",
            trace_id=trace_id,
            trace=f"symbol:{symbol_upper}",
        )
        if payload is None:
            return None
        pools = payload.get("data", [])
        if not isinstance(pools, list):
            INGEST_ERROR_TOTAL.labels(
                chain_id=self._chain_id,
                provider=PROVIDER,
                reason="invalid_gecko_payload",
            ).inc()
            return None
        included = payload.get("included", [])
        included_tokens = self._build_token_lookup(included=included)
        candidates: list[dict] = []
        for pool in pools:
            attributes = pool.get("attributes", {})
            if not isinstance(attributes, dict):
                continue
            if not self._network_match(attributes=attributes):
                continue
            candidate_symbol = self._resolve_base_token_symbol(
                pool=pool,
                attributes=attributes,
                token_lookup=included_tokens,
            )
            if candidate_symbol != symbol_upper:
                continue
            candidates.append(pool)
        if not candidates:
            return None
        best = self._pick_best_pool(candidates=candidates)
        return self._normalize_pool(pool=best, symbol=symbol_upper, token_lookup=included_tokens)

    async def _fetch_token_pools(
        self,
        semaphore: asyncio.Semaphore,
        symbol: str,
        token_address: str,
        trace_id: str,
    ) -> tuple[str, NormalizedPair | None]:
        async with semaphore:
            url = (
                f"{self._api_base}/networks/{quote_plus(self._network)}"
                f"/tokens/{quote_plus(token_address)}/pools"
            )
            payload = await self._http_client.get_json(
                url=url,
                endpoint="gecko_token_pools",
                trace_id=trace_id,
                trace=f"address:{symbol}",
            )
        if payload is None:
            return symbol, None
        pools = payload.get("data", [])
        if not isinstance(pools, list) or not pools:
            return symbol, None
        included = payload.get("included", [])
        included_tokens = self._build_token_lookup(included=included)
        best = self._pick_best_pool(candidates=pools)
        return symbol, self._normalize_pool(pool=best, symbol=symbol, token_lookup=included_tokens)

    def _normalize_pool(
        self,
        pool: dict,
        symbol: str,
        token_lookup: dict[str, dict],
    ) -> NormalizedPair | None:
        attributes = pool.get("attributes", {})
        if not isinstance(attributes, dict):
            return None
        price_usd = self._safe_float(attributes.get("base_token_price_usd"), default=None)
        volume_5m = self._extract_volume_5m(attributes=attributes)
        liquidity_usd = self._safe_float(attributes.get("reserve_in_usd"), default=None)
        buys_5m, sells_5m = self._extract_tx_5m(attributes=attributes)
        if (
            price_usd is None
            or volume_5m is None
            or liquidity_usd is None
            or buys_5m is None
            or sells_5m is None
        ):
            INGEST_ERROR_TOTAL.labels(
                chain_id=self._chain_id,
                provider=PROVIDER,
                reason="invalid_pair_numeric",
            ).inc()
            return None
        dex_id = str(attributes.get("dex_id", ""))
        pool_address = str(attributes.get("address", ""))
        gt_url = str(attributes.get("pool_url", ""))
        created_at_ms = self._extract_created_at_ms(attributes=attributes)
        base_token_address = self._resolve_base_token_address(
            pool=pool,
            attributes=attributes,
            token_lookup=token_lookup,
        )
        return NormalizedPair(
            chain_id=self._chain_id,
            symbol=symbol,
            source="geckoterminal",
            price_usd=price_usd,
            volume_5m=volume_5m,
            liquidity_usd=liquidity_usd,
            buys_5m=buys_5m,
            sells_5m=sells_5m,
            pair_created_at_ms=created_at_ms,
            dex_id=dex_id,
            pair_address=pool_address,
            url=gt_url,
            base_token_address=base_token_address,
        )

    def _resolve_base_token_symbol(
        self,
        pool: dict,
        attributes: dict,
        token_lookup: dict[str, dict],
    ) -> str:
        value = str(attributes.get("base_token_symbol", "")).upper()
        if value:
            return value
        rel = pool.get("relationships", {}).get("base_token", {}).get("data", {})
        rel_key = f"{rel.get('type', '')}:{rel.get('id', '')}"
        token_obj = token_lookup.get(rel_key, {})
        return str(token_obj.get("symbol", "")).upper()

    def _resolve_base_token_address(
        self,
        pool: dict,
        attributes: dict,
        token_lookup: dict[str, dict],
    ) -> str | None:
        addr = str(attributes.get("base_token_address", ""))
        if addr:
            return self._normalize_address(addr)
        rel = pool.get("relationships", {}).get("base_token", {}).get("data", {})
        rel_key = f"{rel.get('type', '')}:{rel.get('id', '')}"
        token_obj = token_lookup.get(rel_key, {})
        token_address = str(token_obj.get("address", ""))
        if not token_address:
            return None
        return self._normalize_address(token_address)

    def _build_token_lookup(self, included: object) -> dict[str, dict]:
        if not isinstance(included, list):
            return {}
        lookup: dict[str, dict] = {}
        for item in included:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('type', '')}:{item.get('id', '')}"
            attrs = item.get("attributes", {})
            if not key or not isinstance(attrs, dict):
                continue
            lookup[key] = attrs
        return lookup

    def _network_match(self, attributes: dict) -> bool:
        network = str(attributes.get("network", ""))
        if not network:
            return True
        return network.strip().lower() == self._network.lower()

    def _extract_volume_5m(self, attributes: dict) -> float | None:
        volume_usd = attributes.get("volume_usd")
        if isinstance(volume_usd, dict):
            for key in ("m5", "h1", "h6", "h24"):
                parsed = self._safe_float(volume_usd.get(key), default=None)
                if parsed is None:
                    continue
                if key == "m5":
                    return parsed
                if key == "h1":
                    return parsed / 12.0
                if key == "h6":
                    return parsed / 72.0
                if key == "h24":
                    return parsed / 288.0
        parsed = self._safe_float(attributes.get("volume_usd_h24"), default=None)
        if parsed is not None:
            return parsed / 288.0
        return None

    def _extract_tx_5m(self, attributes: dict) -> tuple[int | None, int | None]:
        txns = attributes.get("transactions")
        if not isinstance(txns, dict):
            return None, None
        m5 = txns.get("m5")
        if isinstance(m5, dict):
            buys = self._safe_float(m5.get("buys"), default=None)
            sells = self._safe_float(m5.get("sells"), default=None)
            if buys is not None and sells is not None:
                return max(0, int(buys)), max(0, int(sells))
        h1 = txns.get("h1")
        if isinstance(h1, dict):
            buys = self._safe_float(h1.get("buys"), default=None)
            sells = self._safe_float(h1.get("sells"), default=None)
            if buys is not None and sells is not None:
                return max(0, int(buys / 12.0)), max(0, int(sells / 12.0))
        return None, None

    def _extract_created_at_ms(self, attributes: dict) -> int | None:
        candidates = [
            attributes.get("pool_created_at_unix"),
            attributes.get("pool_created_at"),
            attributes.get("created_at"),
        ]
        for candidate in candidates:
            parsed = self._safe_float(candidate, default=None)
            if parsed is None:
                continue
            if parsed > 10_000_000_000:
                return int(parsed)
            return int(parsed * 1000.0)
        return None

    @staticmethod
    def _pick_best_pool(candidates: list[dict]) -> dict:
        def _score(item: dict) -> float:
            attrs = item.get("attributes", {})
            if not isinstance(attrs, dict):
                return 0.0
            return (
                GeckoTerminalProviderAdapter._safe_float(
                    attrs.get("reserve_in_usd"),
                    default=0.0,
                )
                or 0.0
            )

        candidates.sort(key=_score, reverse=True)
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

    async def aclose(self) -> None:
        await self._http_client.aclose()
