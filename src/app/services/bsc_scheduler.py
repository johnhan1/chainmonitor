from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.app.services.bsc_pipeline import BscPipelineService
from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class BscPipelineScheduler:
    def __init__(self, pipeline: BscPipelineService) -> None:
        self.settings = get_settings()
        self.pipeline = pipeline
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop(), name="bsc-pipeline-scheduler")

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
        await asyncio.sleep(max(0, self.settings.bsc_scheduler_initial_delay_seconds))
        interval = max(10, self.settings.bsc_scheduler_interval_seconds)
        while True:
            try:
                summary = self.pipeline.run_once(trigger="scheduler")
                logger.info("bsc scheduler tick completed: %s", summary.model_dump())
            except Exception as exc:  # noqa: BLE001
                logger.exception("bsc scheduler tick failed: %s", exc)
            now = datetime.now(tz=timezone.utc)
            sleep_seconds = interval - (int(now.timestamp()) % interval)
            await asyncio.sleep(max(1, sleep_seconds))

