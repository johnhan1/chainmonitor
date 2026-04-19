from __future__ import annotations

from datetime import datetime

from src.ingestion.chain_ingestion_source_base import ChainIngestionSourceBase
from src.ingestion.contracts.source_strategy import SourceStrategy
from src.shared.schemas.pipeline import MarketTickInput


class MockSourceStrategy(ChainIngestionSourceBase, SourceStrategy):
    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        target_ts = self._normalize_ts(ts_minute)
        return self._mock_rows(symbols=self._symbols(), ts_minute=target_ts)

    def _mock_rows(self, symbols: list[str], ts_minute: datetime) -> list[MarketTickInput]:
        rows: list[MarketTickInput] = []
        for symbol in symbols:
            seed = self._seed(symbol=symbol, ts=ts_minute)
            price = 1 + (seed % 50_000) / 1_000
            volume_1m = 5_000 + (seed % 80_000)
            volume_5m = volume_1m * (1.1 + (seed % 30) / 100)
            liquidity = 100_000 + (seed % 900_000)
            buys = 20 + seed % 80
            sells = 10 + seed % 60
            rows.append(
                MarketTickInput(
                    chain_id=self.chain_id,
                    token_id=self._token_id(symbol),
                    ts_minute=ts_minute,
                    price_usd=round(price, 6),
                    volume_1m=float(volume_1m),
                    volume_5m=float(volume_5m),
                    liquidity_usd=float(liquidity),
                    buys_1m=buys,
                    sells_1m=sells,
                    tx_count_1m=buys + sells + seed % 20,
                )
            )
        return rows
