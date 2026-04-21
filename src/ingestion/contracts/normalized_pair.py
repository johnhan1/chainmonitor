from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizedPair:
    chain_id: str
    symbol: str
    source: str
    price_usd: float
    volume_5m: float
    liquidity_usd: float
    buys_5m: int
    sells_5m: int
    pair_created_at_ms: int | None = None
    dex_id: str = ""
    pair_address: str = ""
    url: str = ""
    base_token_address: str | None = None
