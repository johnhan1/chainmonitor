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
        sources: list[SourceStrategy],
    ) -> None:
        super().__init__(chain_id=chain_id)
        if not sources:
            raise ValueError("fallback source chain requires at least one source strategy")
        self.sources = sources

    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        target_ts = self._normalize_ts(ts_minute)
        symbols = self._symbols()
        by_token: dict[str, MarketTickInput] = {}
        source_errors: list[str] = []
        trace_id = "fallback-missing"
        for index, source in enumerate(self.sources):
            pending_symbols = [
                symbol for symbol in symbols if self._token_id(symbol) not in by_token
            ]
            if not pending_symbols:
                break
            try:
                source_rows = await source.fetch_market_ticks(ts_minute=target_ts)
            except IngestionFetchError as exc:
                source_errors.append(f"s{index + 1}:{exc.reason}")
                trace_id = exc.trace_id
                continue
            for row in source_rows:
                by_token.setdefault(row.token_id, row)
        missing_symbols = [symbol for symbol in symbols if self._token_id(symbol) not in by_token]
        if missing_symbols:
            if source_errors and len(by_token) == 0:
                raise IngestionFetchError(
                    reason="all_sources_failed",
                    detail=";".join(source_errors),
                    chain_id=self.chain_id,
                    trace_id=trace_id,
                )
            raise IngestionFetchError(
                reason="incomplete_fallback",
                detail=f"missing={','.join(missing_symbols)}",
                chain_id=self.chain_id,
                trace_id=trace_id,
            )
        return [by_token[self._token_id(symbol)] for symbol in symbols]

    async def aclose(self) -> None:
        for source in self.sources:
            await source.aclose()
