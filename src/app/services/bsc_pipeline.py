from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

from prometheus_client import Counter, Gauge, Histogram
from src.feature.bsc_feature_engine import BscFeatureEngine
from src.ingestion.bsc_source import BscIngestionSource
from src.scoring.bsc_scoring_engine import BscScoringEngine
from src.shared.config import get_settings
from src.shared.db import PipelineRepository, get_engine
from src.shared.schemas.pipeline import PipelineRunSummary

PIPELINE_RUNS = Counter(
    "cm_bsc_pipeline_runs_total",
    "BSC pipeline run count",
    ["status", "trigger"],
)
PIPELINE_DURATION = Histogram(
    "cm_bsc_pipeline_duration_seconds",
    "BSC pipeline run duration seconds",
    ["trigger"],
)
PIPELINE_LAST_SUCCESS_UNIX = Gauge(
    "cm_bsc_pipeline_last_success_unixtime",
    "Unix timestamp of last successful BSC pipeline run",
)
PIPELINE_LAST_CANDIDATE_COUNT = Gauge(
    "cm_bsc_pipeline_last_candidate_count",
    "Candidate count in last BSC pipeline run",
)


class BscPipelineService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.source = BscIngestionSource()
        self.feature_engine = BscFeatureEngine()
        self.scoring_engine = BscScoringEngine(strategy_version=self.settings.bsc_strategy_version)
        self.repo = PipelineRepository(get_engine())

    def run_once(
        self,
        trigger: str = "manual",
        force: bool = False,
        ts_minute: datetime | None = None,
    ) -> PipelineRunSummary:
        run_ts = (
            (ts_minute or datetime.now(tz=UTC))
            .astimezone(UTC)
            .replace(
                second=0,
                microsecond=0,
            )
        )
        strategy_version = self.settings.bsc_strategy_version

        if force:
            self.repo.upsert_pipeline_run_for_replay(
                chain_id=self.settings.bsc_chain_id,
                strategy_version=strategy_version,
                ts_minute=run_ts,
            )
            trigger = "replay"
        else:
            started = self.repo.try_start_pipeline_run(
                chain_id=self.settings.bsc_chain_id,
                strategy_version=strategy_version,
                ts_minute=run_ts,
                trigger=trigger,
            )
            if not started:
                PIPELINE_RUNS.labels(status="skipped", trigger=trigger).inc()
                return PipelineRunSummary(
                    chain_id=self.settings.bsc_chain_id,
                    strategy_version=strategy_version,
                    ts_minute=run_ts,
                    tick_count=0,
                    candidate_count=0,
                    status="skipped",
                    trigger=trigger,
                    skipped=True,
                )

        started_at = perf_counter()
        ticks = self.source.fetch_market_ticks(ts_minute=run_ts)
        features = self.feature_engine.build_features(ticks)
        scores = self.scoring_engine.score(ticks=ticks, features=features)

        candidate_count = len([s for s in scores if s.tier in {"A", "B", "C"}])
        try:
            self.repo.save_market_ticks(ticks)
            self.repo.save_features(features)
            self.repo.save_scores_and_candidates(scores)
            self.repo.mark_pipeline_run_status(
                chain_id=self.settings.bsc_chain_id,
                strategy_version=strategy_version,
                ts_minute=run_ts,
                status="success",
                tick_count=len(ticks),
                candidate_count=candidate_count,
            )
        except Exception as exc:
            self.repo.mark_pipeline_run_status(
                chain_id=self.settings.bsc_chain_id,
                strategy_version=strategy_version,
                ts_minute=run_ts,
                status="failed",
                tick_count=len(ticks),
                candidate_count=0,
                error_message=str(exc)[:500],
            )
            PIPELINE_RUNS.labels(status="failed", trigger=trigger).inc()
            raise

        duration = perf_counter() - started_at
        PIPELINE_DURATION.labels(trigger=trigger).observe(duration)
        PIPELINE_RUNS.labels(status="success", trigger=trigger).inc()
        PIPELINE_LAST_SUCCESS_UNIX.set(run_ts.timestamp())
        PIPELINE_LAST_CANDIDATE_COUNT.set(candidate_count)

        return PipelineRunSummary(
            chain_id=self.settings.bsc_chain_id,
            strategy_version=strategy_version,
            ts_minute=run_ts,
            tick_count=len(ticks),
            candidate_count=candidate_count,
            status="success",
            trigger=trigger,
            skipped=False,
        )

    def get_latest_candidates(self, tier: str | None = None, limit: int = 20) -> list[dict]:
        return self.repo.list_latest_candidates(
            chain_id=self.settings.bsc_chain_id,
            tier=tier,
            limit=limit,
        )

    def get_recent_runs(self, limit: int = 50) -> list[dict]:
        return self.repo.list_recent_pipeline_runs(
            chain_id=self.settings.bsc_chain_id,
            limit=limit,
        )

    def replay(self, ts_minute: datetime) -> PipelineRunSummary:
        return self.run_once(trigger="replay", force=True, ts_minute=ts_minute)
