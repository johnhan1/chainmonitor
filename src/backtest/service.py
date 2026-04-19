from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from src.backtest.attribution import BacktestAttribution
from src.backtest.batch import BacktestBatchCenter
from src.backtest.engine import BacktestEngine
from src.backtest.optimizer import BacktestParameterOptimizer
from src.backtest.reporting import BacktestReportExporter
from src.backtest.validator import Gate2Validator
from src.shared.db import PipelineRepository, get_engine
from src.shared.schemas.backtest import (
    AttributionReport,
    BacktestConfig,
    BacktestMetrics,
    BacktestRunReport,
    BacktestTradeResult,
    BatchBacktestJobReport,
    ParameterSearchReport,
)


class BacktestService:
    _batch_center = BacktestBatchCenter()

    def __init__(self, chain_id: str) -> None:
        self.chain_id = chain_id
        self.engine = BacktestEngine(chain_id=chain_id)
        self.validator = Gate2Validator(engine=self.engine)
        self.optimizer = BacktestParameterOptimizer(engine=self.engine)
        self.attribution = BacktestAttribution()
        self.reporter = BacktestReportExporter()
        self.repo = PipelineRepository(get_engine())

    async def run_backtest(self, config: BacktestConfig | None = None) -> BacktestRunReport:
        normalized = config or self._default_config()
        report, _, _ = await self._execute_backtest(normalized)
        return report

    async def optimize_parameters(
        self, config: BacktestConfig | None = None
    ) -> ParameterSearchReport:
        normalized = config or self._default_config()
        return await self.optimizer.grid_search(normalized)

    async def run_batch_backtest(
        self,
        configs: list[BacktestConfig],
        gate2_required: bool = False,
    ) -> BatchBacktestJobReport:
        normalized_list = [
            config.model_copy(update={"chain_id": self.chain_id}) for config in configs
        ]
        runner = self.run_gate2_check if gate2_required else self.run_backtest
        return await self._batch_center.submit(
            chain_id=self.chain_id,
            configs=normalized_list,
            runner=runner,
        )

    def get_batch_job(self, job_id: str) -> BatchBacktestJobReport | None:
        return self._batch_center.get(job_id)

    async def export_backtest_report(
        self,
        config: BacktestConfig | None = None,
    ) -> dict[str, Any]:
        normalized = config or self._default_config()
        report, trades, _ = await self._execute_backtest(normalized)
        attribution = self.attribution.build(trades)
        files = self.reporter.export(
            report=report,
            config=normalized,
            attribution=attribution,
        )
        return {
            "run": report.model_dump(),
            "attribution": attribution.model_dump(),
            "files": files,
        }

    async def build_attribution(self, config: BacktestConfig | None = None) -> AttributionReport:
        normalized = config or self._default_config()
        _, trades, _ = await self._execute_backtest(normalized)
        return self.attribution.build(trades)

    async def _execute_backtest(
        self, config: BacktestConfig
    ) -> tuple[BacktestRunReport, list[BacktestTradeResult], BacktestMetrics]:
        trades, metrics = await self.engine.run(config)
        run_id = self._build_run_id(config)
        self.repo.save_backtest_run(
            run_id=run_id,
            config=config,
            status="success",
            metrics=metrics,
        )
        return (
            BacktestRunReport(
                run_id=run_id,
                chain_id=config.chain_id,
                strategy_version=config.strategy_version,
                period_start=config.period_start,
                period_end=config.period_end,
                status="success",
                metrics=metrics,
            ),
            trades,
            metrics,
        )

    async def run_gate2_check(self, config: BacktestConfig | None = None) -> BacktestRunReport:
        normalized = config or self._default_config()
        run_id = self._build_run_id(normalized)
        gate2 = await self.validator.check(normalized)
        status = "success" if gate2.passed else "failed"
        self.repo.save_backtest_run(
            run_id=run_id,
            config=normalized,
            status=status,
            metrics=gate2.metrics,
        )
        self.repo.save_gate2_check_result(run_id=run_id, gate2_payload=gate2.model_dump())
        return BacktestRunReport(
            run_id=run_id,
            chain_id=normalized.chain_id,
            strategy_version=normalized.strategy_version,
            period_start=normalized.period_start,
            period_end=normalized.period_end,
            status=status,
            metrics=gate2.metrics,
            gate2=gate2,
        )

    def list_recent_backtests(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repo.list_recent_backtest_runs(chain_id=self.chain_id, limit=limit)

    def _default_config(self) -> BacktestConfig:
        end = datetime.now(tz=UTC).replace(second=0, microsecond=0)
        start = end - timedelta(minutes=30)
        return BacktestConfig(
            chain_id=self.chain_id,
            strategy_version=self.engine.settings.get_strategy_version(chain_id=self.chain_id),
            period_start=start,
            period_end=end,
        )

    @staticmethod
    def _build_run_id(config: BacktestConfig) -> str:
        payload = (
            f"{config.chain_id}|{config.strategy_version}|"
            f"{config.period_start.isoformat()}|{config.period_end.isoformat()}|"
            f"{config.conviction_threshold}|{config.trade_size_usd}"
        )
        digest = sha256(payload.encode("utf-8")).hexdigest()
        return f"bt_{digest[:24]}"
