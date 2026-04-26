from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from src.scanner.detector import AlphaScorer
from src.scanner.gmgn_client import GmgnClient
from src.scanner.models import Snapshot, TokenRisk
from src.scanner.notifier import TelegramNotifier
from src.scanner.snapshot_store import SnapshotStore

logger = logging.getLogger(__name__)


class ScannerOrchestrator:
    def __init__(
        self,
        chains: list[str],
        client: GmgnClient | None = None,
        store: SnapshotStore | None = None,
        scorer: AlphaScorer | None = None,
        notifier: TelegramNotifier | None = None,
        surge_threshold: int = 10,
        spike_ratio: float = 2.0,
        trending_limit: int = 50,
        interval_1h_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
        cooldown_high_seconds: int = 900,
        cooldown_medium_seconds: int = 1800,
    ) -> None:
        self._chains = chains
        self._client = client
        self._store = store
        self._scorer = scorer
        self._notifier = notifier
        self._trending_limit = trending_limit
        self._interval_1h_seconds = interval_1h_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_1h_run: float = self._clock().timestamp()
        self._cooldown: dict[str, float] = {}
        self._cooldown_high_seconds = cooldown_high_seconds
        self._cooldown_medium_seconds = cooldown_medium_seconds

    async def run_cycle(self) -> None:
        for chain in self._chains:
            try:
                await self._run_chain(chain, "1m")
            except Exception:
                logger.exception("Scanner 1m cycle failed for chain=%s", chain)

        now = self._clock().timestamp()
        if now - self._last_1h_run >= self._interval_1h_seconds:
            self._last_1h_run = now
            for chain in self._chains:
                try:
                    await self._run_chain(chain, "1h")
                except Exception:
                    logger.exception("Scanner 1h cycle failed for chain=%s", chain)

    def _is_cooling(self, address: str) -> bool:
        expires = self._cooldown.get(address, 0.0)
        return expires > self._clock().timestamp()

    async def _run_chain(self, chain: str, interval: str) -> None:
        logger.info("Scanner polling chain=%s interval=%s", chain, interval)
        tokens = await self._client.fetch_trending(
            chain=chain, interval=interval, limit=self._trending_limit
        )
        if not tokens:
            logger.warning("Scanner empty result chain=%s interval=%s", chain, interval)
            return

        curr = Snapshot(chain=chain, interval=interval, tokens=tokens, taken_at=self._clock())
        prev = self._store.load(chain, interval)

        risks: dict[str, TokenRisk] = {}
        seen = set()
        for t in tokens:
            if t.address in seen:
                continue
            seen.add(t.address)
            if t.liquidity is not None and t.liquidity < 100_000:
                risk = await self._client.fetch_token_security(chain, t.address)
                if risk:
                    risks[t.address] = risk

        signals = self._scorer.detect(prev, curr, risks)
        for sig in signals:
            addr = sig.token.token.address
            if self._is_cooling(addr):
                logger.debug("Cooldown skip %s (%s)", sig.token.token.symbol, addr)
                continue

            logger.info(
                "AlphaSignal level=%s score=%d chain=%s symbol=%s",
                sig.level,
                sig.token.score,
                chain,
                sig.token.token.symbol,
            )
            await self._notifier.send_alpha(sig)

            cooldown_sec = (
                self._cooldown_high_seconds
                if sig.level == "HIGH"
                else self._cooldown_medium_seconds
            )
            self._cooldown[addr] = self._clock().timestamp() + cooldown_sec

        self._store.save(chain, interval, curr)

    async def run_forever(self, interval_seconds: int = 60) -> None:
        logger.info("Scanner starting, interval=%ds chains=%s", interval_seconds, self._chains)
        while True:
            await self.run_cycle()
            await asyncio.sleep(interval_seconds)
