from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from src.shared.schemas.backtest import (
    BacktestConfig,
    BacktestRunReport,
    BatchBacktestItem,
    BatchBacktestJobReport,
)


class BacktestBatchCenter:
    def __init__(self) -> None:
        self._jobs: dict[str, BatchBacktestJobReport] = {}

    async def submit(
        self,
        chain_id: str,
        configs: list[BacktestConfig],
        runner: Callable[[BacktestConfig], Awaitable[BacktestRunReport]],
    ) -> BatchBacktestJobReport:
        job_id = f"btjob_{uuid4().hex[:12]}"
        job = BatchBacktestJobReport(
            job_id=job_id,
            chain_id=chain_id,
            status="running",
            total=len(configs),
            succeeded=0,
            failed=0,
            items=[],
        )
        self._jobs[job_id] = job
        items: list[BatchBacktestItem] = []
        succeeded = 0
        failed = 0

        for index, config in enumerate(configs):
            item_id = f"{job_id}_{index + 1}"
            try:
                result = await runner(config)
                succeeded += 1
                items.append(
                    BatchBacktestItem(
                        item_id=item_id,
                        chain_id=chain_id,
                        status="success",
                        result=result,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                items.append(
                    BatchBacktestItem(
                        item_id=item_id,
                        chain_id=chain_id,
                        status="failed",
                        error=str(exc),
                    )
                )
        status = "success" if failed == 0 else "partial_failed"
        finalized = BatchBacktestJobReport(
            job_id=job_id,
            chain_id=chain_id,
            status=status,
            total=len(configs),
            succeeded=succeeded,
            failed=failed,
            items=items,
        )
        self._jobs[job_id] = finalized
        return finalized

    def get(self, job_id: str) -> BatchBacktestJobReport | None:
        return self._jobs.get(job_id)
