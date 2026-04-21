from __future__ import annotations

from abc import ABC, abstractmethod
from time import time

from src.ingestion.contracts.normalized_pair import NormalizedPair
from src.shared.config import Settings


class PairQualityPolicy(ABC):
    @abstractmethod
    def is_acceptable(self, pair: NormalizedPair, chain_id: str) -> bool:
        raise NotImplementedError


class DefaultPairQualityPolicy(PairQualityPolicy):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_acceptable(self, pair: NormalizedPair, chain_id: str) -> bool:
        dex_id = pair.dex_id.strip().lower()
        if dex_id and dex_id in self._settings.dex_blacklist_ids:
            return False
        route_signal = f"{pair.pair_address.lower()}|{pair.url.lower()}"
        if any(keyword in route_signal for keyword in self._settings.route_blacklist_keywords):
            return False
        if pair.pair_created_at_ms is None:
            return False
        age_seconds = time() - (pair.pair_created_at_ms / 1000.0)
        min_age_seconds = self._settings.get_market_data_min_pair_age_seconds(chain_id=chain_id)
        if age_seconds < min_age_seconds:
            return False
        if pair.price_usd <= 0:
            return False
        if pair.volume_5m < 0 or pair.liquidity_usd < 0 or pair.buys_5m < 0 or pair.sells_5m < 0:
            return False
        max_ratio = self._settings.get_market_data_max_volume_liquidity_ratio(chain_id=chain_id)
        if pair.liquidity_usd > 0 and pair.volume_5m / pair.liquidity_usd > max_ratio:
            return False
        return True
