from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.shared.schemas.pipeline import MarketTickInput


class SourceStrategy(ABC):
    @abstractmethod
    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None
