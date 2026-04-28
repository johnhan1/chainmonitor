from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from src.scanner.cooldown import CooldownManager
from src.scanner.detector import AlphaScorer
from src.scanner.events import (
    ChainScanCompleted,
    ChainScanStarted,
    CooldownSkipped,
    EventBus,
    SignalEmitted,
    TokenFiltered,
    TokenScored,
    TokenSecurityChecked,
    TrendingFetched,
)
from src.scanner.gmgn_client import GmgnClient
from src.scanner.models import Snapshot, TokenRisk, TrendingToken
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
        event_bus: EventBus | None = None,
        cooldown: CooldownManager | None = None,
        score_high: int = 75,
        score_medium: int = 65,
        score_low: int = 55,
    ) -> None:
        self._chains = chains
        self._client = client
        self._store = store
        self._scorer = scorer or AlphaScorer(
            score_high=score_high,
            score_medium=score_medium,
            score_low=score_low,
        )
        self._notifier = notifier
        self._trending_limit = trending_limit
        self._interval_1h_seconds = interval_1h_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_1h_run: float = self._clock().timestamp()
        self._event_bus = event_bus or EventBus()
        self._cooldown = cooldown or CooldownManager(clock=self._clock)

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
        t0 = self._clock()
        self._event_bus.publish(ChainScanStarted(chain=chain, interval=interval, timestamp=t0))

        tokens = await self._client.fetch_trending(
            chain=chain, interval=interval, limit=self._trending_limit
        )
        fetch_dur = (self._clock() - t0).total_seconds() * 1000
        self._event_bus.publish(
            TrendingFetched(
                chain=chain,
                interval=interval,
                token_count=len(tokens),
                duration_ms=fetch_dur,
                success=bool(tokens),
            )
        )

        if not tokens:
            logger.warning("Scanner empty result chain=%s interval=%s", chain, interval)
            return

        curr = Snapshot(chain=chain, interval=interval, tokens=tokens, taken_at=self._clock())
        prev = self._store.load(chain, interval)

        risks: dict[str, TokenRisk] = {}
        seen: set[str] = set()
        security_tasks: list[tuple[str, str, asyncio.Task]] = []
        for t in tokens:
            if t.address in seen:
                continue
            seen.add(t.address)
            if t.liquidity is not None and t.liquidity < 100_000:
                task = asyncio.create_task(self._client.fetch_token_security(chain, t.address))
                security_tasks.append((t.address, t.symbol, task))

        for addr, symbol, task in security_tasks:
            try:
                t0 = self._clock()
                risk = await task
                sec_dur = (self._clock() - t0).total_seconds() * 1000
                self._event_bus.publish(
                    TokenSecurityChecked(
                        chain=chain,
                        address=addr,
                        symbol=symbol,
                        duration_ms=sec_dur,
                        success=risk is not None,
                    )
                )
                if risk:
                    risks[addr] = risk
            except Exception:
                logger.exception("Security check failed for %s", addr)

        signals = self._scorer.detect(prev, curr, risks)

        prev_map: dict[str, TrendingToken] = {}
        if prev:
            prev_map = {t.address: t for t in prev.tokens}

        for token in curr.tokens:
            risk = risks.get(token.address)
            fr = self._scorer.hard_filter(token, risk)
            self._event_bus.publish(
                TokenFiltered(
                    chain=chain,
                    address=token.address,
                    symbol=token.symbol,
                    passed=fr.passed,
                    reason=fr.reason,
                )
            )
            if fr.passed:
                prev_token = prev_map.get(token.address)
                scored = self._scorer.score(token, prev_token, risk)
                self._event_bus.publish(
                    TokenScored(
                        chain=chain,
                        address=token.address,
                        symbol=token.symbol,
                        total_score=scored.score,
                        breakdown=scored.breakdown,
                        passed_filters=True,
                        filter_reason="",
                    )
                )
            else:
                self._event_bus.publish(
                    TokenScored(
                        chain=chain,
                        address=token.address,
                        symbol=token.symbol,
                        total_score=0,
                        breakdown={},
                        passed_filters=False,
                        filter_reason=fr.reason,
                    )
                )

        for sig in signals:
            addr = sig.token.token.address
            if self._cooldown.is_cooling(addr):
                self._event_bus.publish(
                    CooldownSkipped(
                        chain=chain,
                        address=addr,
                        symbol=sig.token.token.symbol,
                    )
                )
                logger.debug("Cooldown skip %s (%s)", sig.token.token.symbol, addr)
                continue

            # Apply decay for repeat signals
            decay = self._cooldown.decay_factor(addr)
            if decay < 1.0:
                sig.token.score = int(sig.token.score * decay)
                sig.token.breakdown = {}
                logger.info(
                    "Decayed signal for %s: factor=%.1f score=%d",
                    sig.token.token.symbol,
                    decay,
                    sig.token.score,
                )

            self._event_bus.publish(
                SignalEmitted(
                    chain=chain,
                    address=addr,
                    symbol=sig.token.token.symbol,
                    level=sig.level,
                    score=sig.token.score,
                )
            )
            logger.info(
                "AlphaSignal level=%s score=%d chain=%s symbol=%s",
                sig.level,
                sig.token.score,
                chain,
                sig.token.token.symbol,
            )
            await self._notifier.send_alpha(sig)
            self._cooldown.mark(addr, sig.level)

        self._store.save(chain, interval, curr)

        total_dur = (self._clock() - t0).total_seconds() * 1000
        self._event_bus.publish(
            ChainScanCompleted(
                chain=chain,
                interval=interval,
                total_duration_ms=total_dur,
                token_count=len(tokens),
                signal_count=len(signals),
            )
        )

    async def run_forever(self, interval_seconds: int = 60) -> None:
        logger.info("Scanner starting, interval=%ds chains=%s", interval_seconds, self._chains)
        while True:
            await self.run_cycle()
            await asyncio.sleep(interval_seconds)
