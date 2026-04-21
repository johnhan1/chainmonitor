from __future__ import annotations

import asyncio
import logging
from abc import ABC
from datetime import datetime
from uuid import uuid4

from src.ingestion.chain_ingestion_source_base import ChainIngestionSourceBase
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.normalized_pair import NormalizedPair
from src.ingestion.contracts.pair_quality_policy import (
    DefaultPairQualityPolicy,
    PairQualityPolicy,
)
from src.ingestion.contracts.provider_adapter import ProviderAdapter
from src.ingestion.contracts.source_strategy import SourceStrategy
from src.shared.schemas.pipeline import MarketTickInput

logger = logging.getLogger(__name__)


class BaseLiveSourceStrategy(ChainIngestionSourceBase, SourceStrategy, ABC):
    def __init__(
        self,
        chain_id: str,
        adapter: ProviderAdapter,
        quality_policy: PairQualityPolicy | None = None,
    ) -> None:
        super().__init__(chain_id=chain_id)
        self._adapter = adapter
        self._quality_policy = quality_policy or DefaultPairQualityPolicy(settings=self.settings)

    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        target_ts = self._normalize_ts(ts_minute)
        trace_id = uuid4().hex[:12]
        symbols = self._symbols()
        pairs_by_symbol = await self._collect_pairs(symbols=symbols, trace_id=trace_id)
        rows = self._to_rows(symbols=symbols, pairs_by_symbol=pairs_by_symbol, ts_minute=target_ts)
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
        trace_id: str,
    ) -> dict[str, NormalizedPair]:
        pairs_by_symbol: dict[str, NormalizedPair] = {}
        symbol_to_address = self.settings.get_chain_token_addresses(self.chain_id)
        if symbol_to_address:
            pairs_by_symbol.update(
                await self._adapter.fetch_pairs_by_addresses(
                    symbol_to_address=symbol_to_address,
                    trace_id=trace_id,
                )
            )
        remaining = [symbol for symbol in symbols if symbol not in pairs_by_symbol]
        if not remaining:
            return pairs_by_symbol
        tasks = [
            self._adapter.fetch_pair_by_symbol(symbol=symbol, trace_id=trace_id)
            for symbol in remaining
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for symbol, result in zip(remaining, results, strict=False):
            if isinstance(result, Exception):
                logger.warning(
                    "live source symbol fetch failed chain=%s trace_id=%s symbol=%s error=%s",
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

    def _to_rows(
        self,
        symbols: list[str],
        pairs_by_symbol: dict[str, NormalizedPair],
        ts_minute: datetime,
    ) -> list[MarketTickInput]:
        rows: list[MarketTickInput] = []
        for symbol in symbols:
            pair = pairs_by_symbol.get(symbol)
            if pair is None:
                continue
            if not self._quality_policy.is_acceptable(pair=pair, chain_id=self.chain_id):
                continue
            rows.append(
                MarketTickInput(
                    chain_id=self.chain_id,
                    token_id=self._token_id(symbol),
                    ts_minute=ts_minute,
                    price_usd=pair.price_usd,
                    volume_1m=max(0.0, pair.volume_5m / 5.0),
                    volume_5m=max(0.0, pair.volume_5m),
                    liquidity_usd=max(0.0, pair.liquidity_usd),
                    buys_1m=max(0, int(pair.buys_5m / 5)),
                    sells_1m=max(0, int(pair.sells_5m / 5)),
                    tx_count_1m=max(0, int((pair.buys_5m + pair.sells_5m) / 5)),
                )
            )
        return rows

    async def aclose(self) -> None:
        await self._adapter.aclose()
