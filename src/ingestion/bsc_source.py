from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from src.shared.config import get_settings
from src.shared.schemas.pipeline import MarketTickInput


class BscIngestionSource:
    """MVP data source: deterministic synthetic ticks for BSC symbols."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        if ts_minute is None:
            ts_minute = datetime.now(tz=UTC).replace(second=0, microsecond=0)
        else:
            ts_minute = ts_minute.astimezone(UTC).replace(second=0, microsecond=0)
        symbols = [
            s.strip().upper() for s in self.settings.bsc_default_symbols.split(",") if s.strip()
        ]
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
                    chain_id=self.settings.bsc_chain_id,
                    token_id=f"bsc_{symbol.lower()}",
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

    @staticmethod
    def _seed(symbol: str, ts: datetime) -> int:
        digest = sha256(f"{symbol}:{ts.isoformat()}".encode()).hexdigest()
        return int(digest[:12], 16)
