from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from prometheus_client import Counter, Gauge
from src.ingestion.adapters.dexscreener_provider_adapter import DexScreenerProviderAdapter
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.normalized_pair import NormalizedPair
from src.ingestion.resilience.resilient_http_client import INGEST_ERROR_TOTAL, ResilientHttpClient
from src.ingestion.strategies.base_live_source_strategy import BaseLiveSourceStrategy
from src.shared.config import get_settings
from src.shared.schemas.pipeline import MarketTickInput

logger = logging.getLogger(__name__)

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


class DexScreenerSourceStrategy(BaseLiveSourceStrategy):
    def __init__(self, chain_id: str) -> None:
        settings = get_settings()
        http_client = ResilientHttpClient(
            chain_id=chain_id,
            settings=settings,
        )
        super().__init__(
            chain_id=chain_id,
            adapter=DexScreenerProviderAdapter(
                chain_id=chain_id,
                settings=settings,
                http_client=http_client,
            ),
        )

    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        target_ts = self._normalize_ts(ts_minute)
        trace_id = uuid4().hex[:12]
        symbols = self._symbols()
        address_map = self.settings.get_chain_token_addresses(self.chain_id)
        required_address_symbols = self._required_address_symbols(symbols=symbols)
        self._validate_required_mappings(
            symbols=symbols,
            address_map=address_map,
            required_address_symbols=required_address_symbols,
            trace_id=trace_id,
        )
        pairs_by_symbol = await self._collect_pairs(
            symbols=symbols,
            address_map=address_map,
            required_address_symbols=required_address_symbols,
            trace_id=trace_id,
        )
        self._validate_success_ratio(
            symbols=symbols,
            pairs_by_symbol=pairs_by_symbol,
            trace_id=trace_id,
        )
        rows = self._to_rows(symbols=symbols, pairs_by_symbol=pairs_by_symbol, ts_minute=target_ts)
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

    async def _collect_pairs(
        self,
        symbols: list[str],
        address_map: dict[str, str],
        required_address_symbols: set[str],
        trace_id: str,
    ) -> dict[str, NormalizedPair]:
        pairs_by_symbol: dict[str, NormalizedPair] = {}
        if address_map:
            pairs_by_symbol.update(
                await self._adapter.fetch_pairs_by_addresses(
                    symbol_to_address=address_map,
                    trace_id=trace_id,
                )
            )

        unresolved_required = [
            symbol for symbol in required_address_symbols if symbol not in pairs_by_symbol
        ]
        if unresolved_required:
            detail = f"symbols={','.join(sorted(unresolved_required))}"
            INGEST_ERROR_TOTAL.labels(
                chain_id=self.chain_id,
                reason="required_symbol_unresolved",
            ).inc()
            raise IngestionFetchError(
                reason="required_symbol_unresolved",
                detail=detail,
                chain_id=self.chain_id,
                trace_id=trace_id,
            )

        remaining = [
            symbol
            for symbol in symbols
            if symbol not in pairs_by_symbol and symbol not in required_address_symbols
        ]
        if not remaining:
            return pairs_by_symbol
        tasks = [
            self._adapter.fetch_pair_by_symbol(symbol=symbol, trace_id=trace_id)
            for symbol in remaining
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for symbol, result in zip(remaining, results, strict=False):
            if isinstance(result, Exception):
                INGEST_ERROR_TOTAL.labels(chain_id=self.chain_id, reason="symbol_task_error").inc()
                logger.warning(
                    "symbol fetch task failed chain=%s trace_id=%s symbol=%s error=%s",
                    self.chain_id,
                    trace_id,
                    symbol,
                    result,
                )
                continue
            if result is None:
                continue
            pairs_by_symbol[symbol] = result
        return pairs_by_symbol

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

    def _validate_success_ratio(
        self,
        symbols: list[str],
        pairs_by_symbol: dict[str, NormalizedPair],
        trace_id: str,
    ) -> None:
        min_success_ratio = self.settings.get_market_data_min_success_ratio(chain_id=self.chain_id)
        success_ratio = len(pairs_by_symbol) / max(1, len(symbols))
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
                chain_id=self.chain_id,
                reason="required_symbol_invalid",
            ).inc()
            raise IngestionFetchError(
                reason="required_symbol_invalid",
                detail=detail,
                chain_id=self.chain_id,
                trace_id=trace_id,
            )

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
