from __future__ import annotations

from abc import ABC, abstractmethod

from src.ingestion.contracts.normalized_pair import NormalizedPair


class ProviderAdapter(ABC):
    @abstractmethod
    async def fetch_pairs_by_addresses(
        self,
        symbol_to_address: dict[str, str],
        trace_id: str,
    ) -> dict[str, NormalizedPair]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_pair_by_symbol(self, symbol: str, trace_id: str) -> NormalizedPair | None:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None
