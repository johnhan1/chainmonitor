from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta

from src.app.services.chain_pipeline_service import ChainPipelineService

logger = logging.getLogger(__name__)


class ChainPipelineScheduler:
    def __init__(
        self,
        chain_id: str,
        pipeline: ChainPipelineService,
        interval_seconds: int,
        initial_delay_seconds: int,
        startup_jitter_seconds: int = 0,
    ) -> None:
        self.chain_id = chain_id
        self.pipeline = pipeline
        self.interval_seconds = max(10, interval_seconds)
        self.initial_delay_seconds = max(0, initial_delay_seconds)
        self.startup_jitter_seconds = max(0, startup_jitter_seconds)
        self.catchup_windows = max(1, self.pipeline.settings.pipeline_scheduler_catchup_windows)
        self.window_step_minutes = max(1, round(self.interval_seconds / 60))
        self._task: asyncio.Task | None = None
        self._last_window_ts: datetime | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run_loop(),
            name=f"{self.chain_id}-pipeline-scheduler",
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self) -> None:
        jitter = random.uniform(0.0, float(self.startup_jitter_seconds))
        await asyncio.sleep(self.initial_delay_seconds + jitter)
        while True:
            target_windows = self._build_due_windows()
            for window_ts in target_windows:
                try:
                    claim: tuple[str, str, datetime] | None = None
                    with self.pipeline.repo.scheduler_lock(chain_id=self.chain_id) as acquired:
                        if not acquired:
                            logger.info(
                                "%s scheduler tick skipped: lock not acquired", self.chain_id
                            )
                            continue
                        claim = await asyncio.to_thread(
                            self.pipeline.claim_scheduler_window,
                            window_ts,
                        )

                    if claim is None:
                        logger.info(
                            "%s scheduler tick skipped: duplicate run window", self.chain_id
                        )
                        self._last_window_ts = window_ts
                        continue
                    run_id, strategy_version, run_ts = claim
                    summary = await self.pipeline.run_claimed(
                        run_id=run_id,
                        strategy_version=strategy_version,
                        run_ts=run_ts,
                        trigger="scheduler",
                    )
                    logger.info(
                        "%s scheduler tick completed: %s", self.chain_id, summary.model_dump()
                    )
                    self._last_window_ts = window_ts
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("%s scheduler tick failed: %s", self.chain_id, exc)
            now = datetime.now(tz=UTC)
            sleep_seconds = self.interval_seconds - (int(now.timestamp()) % self.interval_seconds)
            await asyncio.sleep(max(1, sleep_seconds))

    def _build_due_windows(self) -> list[datetime]:
        current = datetime.now(tz=UTC).replace(second=0, microsecond=0)
        step = timedelta(minutes=self.window_step_minutes)
        if self._last_window_ts is None:
            return [current]
        next_window = self._last_window_ts + step
        due_windows: list[datetime] = []
        while next_window <= current:
            due_windows.append(next_window)
            next_window = next_window + step
        if not due_windows:
            return [current]
        if len(due_windows) > self.catchup_windows:
            return due_windows[-self.catchup_windows :]
        return due_windows
