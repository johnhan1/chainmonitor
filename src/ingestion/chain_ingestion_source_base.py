from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from src.shared.config import Settings, get_settings


class ChainIngestionSourceBase:
    def __init__(self, chain_id: str, data_mode: str | None = None) -> None:
        self.settings: Settings = get_settings()
        if chain_id not in self.settings.supported_chains:
            raise ValueError(f"unsupported chain_id: {chain_id}")
        self.chain_id = chain_id
        self.data_mode = (data_mode or self.settings.market_data_mode).strip().lower()

    def _symbols(self) -> list[str]:
        raw = self.settings.get_chain_symbols(self.chain_id)
        return [s.strip().upper() for s in raw.split(",") if s.strip()]

    def _token_id(self, symbol: str) -> str:
        return f"{self.chain_id}_{symbol.lower()}"

    @staticmethod
    def _normalize_ts(ts_minute: datetime | None) -> datetime:
        if ts_minute is None:
            return datetime.now(tz=UTC).replace(second=0, microsecond=0)
        return ts_minute.astimezone(UTC).replace(second=0, microsecond=0)

    @staticmethod
    def _seed(symbol: str, ts: datetime) -> int:
        digest = sha256(f"{symbol}:{ts.isoformat()}".encode()).hexdigest()
        return int(digest[:12], 16)
