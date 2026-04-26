from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from src.scanner.detector import Detector
from src.scanner.gmgn_client import GmgnClient
from src.scanner.models import Snapshot
from src.scanner.notifier import TelegramNotifier
from src.scanner.snapshot_store import SnapshotStore

logger = logging.getLogger(__name__)


class ScannerOrchestrator:
    def __init__(
        self,
        chains: list[str],
        client: GmgnClient | None = None,
        store: SnapshotStore | None = None,
        detector: Detector | None = None,
        notifier: TelegramNotifier | None = None,
        surge_threshold: int = 10,
        spike_ratio: float = 2.0,
        trending_limit: int = 50,
        interval_1h_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._chains = chains
        self._client = client
        self._store = store
        self._detector = detector
        self._notifier = notifier
        self._trending_limit = trending_limit
        self._interval_1h_seconds = interval_1h_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_1h_run: float = self._clock().timestamp()

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

        events = self._detector.detect(prev, curr)
        if events:
            logger.info(
                "Scanner anomalies chain=%s interval=%s count=%d", chain, interval, len(events)
            )
            await self._notifier.send_anomalies(chain, interval, events)

        self._store.save(chain, interval, curr)

    async def run_forever(self, interval_seconds: int = 60) -> None:
        logger.info("Scanner starting, interval=%ds chains=%s", interval_seconds, self._chains)
        while True:
            await self.run_cycle()
            await asyncio.sleep(interval_seconds)
