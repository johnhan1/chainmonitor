from __future__ import annotations

from datetime import datetime

from src.ingestion.chain_ingestion_source_base import ChainIngestionSourceBase
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.contracts.source_strategy import SourceStrategy
from src.shared.schemas.pipeline import MarketTickInput


class FallbackSourceChain(ChainIngestionSourceBase, SourceStrategy):
    def __init__(
        self,
        chain_id: str,
        primary: SourceStrategy,
        secondary: SourceStrategy,
        data_mode: str | None = None,
    ) -> None:
        super().__init__(chain_id=chain_id, data_mode=data_mode)
        self.primary = primary
        self.secondary = secondary

    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        if self.data_mode == "mock":
            return await self.secondary.fetch_market_ticks(ts_minute=ts_minute)
        if self.data_mode == "live":
            return await self.primary.fetch_market_ticks(ts_minute=ts_minute)
        if self.data_mode != "hybrid":
            raise ValueError(f"unsupported market_data_mode: {self.data_mode}")

        target_ts = self._normalize_ts(ts_minute)
        symbols = self._symbols()
        primary_error: IngestionFetchError | None = None
        try:
            live_rows = await self.primary.fetch_market_ticks(ts_minute=target_ts)
        except IngestionFetchError as exc:
            primary_error = exc
            live_rows = []
        if len(live_rows) == len(symbols):
            return live_rows

        by_token = {row.token_id: row for row in live_rows}
        try:
            fallback_rows = await self.secondary.fetch_market_ticks(ts_minute=target_ts)
        except IngestionFetchError as exc:
            detail = (
                f"primary={primary_error.reason if primary_error else 'partial_live'};"
                f" secondary={exc.reason}"
            )
            raise IngestionFetchError(
                reason="all_sources_failed",
                detail=detail,
                chain_id=self.chain_id,
                trace_id=exc.trace_id,
            ) from exc
        for row in fallback_rows:
            by_token.setdefault(row.token_id, row)
        missing_symbols = [symbol for symbol in symbols if self._token_id(symbol) not in by_token]
        if missing_symbols:
            trace_id = primary_error.trace_id if primary_error else "fallback-missing"
            raise IngestionFetchError(
                reason="incomplete_fallback",
                detail=f"missing={','.join(missing_symbols)}",
                chain_id=self.chain_id,
                trace_id=trace_id,
            )
        return [by_token[self._token_id(symbol)] for symbol in symbols]

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.secondary.aclose()
