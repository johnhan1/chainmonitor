import asyncio
from datetime import UTC, datetime, timedelta

from src.backtest.attribution import BacktestAttribution
from src.backtest.batch import BacktestBatchCenter
from src.backtest.engine import BacktestEngine
from src.backtest.optimizer import BacktestParameterOptimizer
from src.backtest.reporting import BacktestReportExporter
from src.shared.config import get_settings
from src.shared.schemas.backtest import BacktestConfig, BacktestRunReport


def _config() -> BacktestConfig:
    settings = get_settings()
    end = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
    start = end - timedelta(minutes=60)
    return BacktestConfig(
        chain_id=settings.bsc_chain_id,
        strategy_version=settings.get_strategy_version(chain_id=settings.bsc_chain_id),
        period_start=start,
        period_end=end,
        conviction_threshold=60.0,
    )


def test_phase2_full_parameter_optimizer_returns_best() -> None:
    config = _config()
    report = asyncio.run(
        BacktestParameterOptimizer(BacktestEngine(config.chain_id)).grid_search(config)
    )

    assert report.tested_count > 1
    assert len(report.leaderboard) > 0
    assert report.best.pf >= report.leaderboard[-1].pf


def test_phase2_full_attribution_and_reporting(tmp_path) -> None:
    config = _config()
    trades, metrics = asyncio.run(BacktestEngine(config.chain_id).run(config))
    attribution = BacktestAttribution().build(trades)

    report = BacktestRunReport(
        run_id="bt_test_report",
        chain_id=config.chain_id,
        strategy_version=config.strategy_version,
        period_start=config.period_start,
        period_end=config.period_end,
        status="success",
        metrics=metrics,
    )
    files = BacktestReportExporter(root_dir=str(tmp_path)).export(
        report=report,
        config=config,
        attribution=attribution,
    )

    assert (tmp_path / f"{config.chain_id}_{report.run_id}.json").exists()
    assert (tmp_path / f"{config.chain_id}_{report.run_id}.csv").exists()
    assert (tmp_path / f"{config.chain_id}_{report.run_id}.md").exists()
    assert set(files.keys()) == {"json", "csv", "md"}


def test_phase2_full_batch_center() -> None:
    config = _config()
    center = BacktestBatchCenter()

    async def _runner(cfg: BacktestConfig) -> BacktestRunReport:
        _, metrics = await BacktestEngine(cfg.chain_id).run(cfg)
        return BacktestRunReport(
            run_id="bt_batch_item",
            chain_id=cfg.chain_id,
            strategy_version=cfg.strategy_version,
            period_start=cfg.period_start,
            period_end=cfg.period_end,
            status="success",
            metrics=metrics,
        )

    job = asyncio.run(
        center.submit(chain_id=config.chain_id, configs=[config, config], runner=_runner)
    )
    loaded = center.get(job.job_id)

    assert loaded is not None
    assert loaded.status == "success"
    assert loaded.total == 2
    assert loaded.succeeded == 2
    assert loaded.failed == 0
