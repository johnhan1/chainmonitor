from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from prometheus_client import Counter, Gauge, Histogram
from src.app.services.pipeline_registry import PipelineComponentRegistry
from src.ingestion.contracts.errors import IngestionFetchError
from src.ingestion.services.chain_ingestion_service import ChainIngestionService
from src.shared.config.chain import get_chain_settings
from src.shared.config.pipeline import get_pipeline_settings
from src.shared.db import PipelineRepository, get_engine
from src.shared.schemas.pipeline import (
    FeatureRowInput,
    MarketTickInput,
    PipelineRunSummary,
    ScoreRowInput,
)

logger = logging.getLogger(__name__)
DEFAULT_PIPELINE_REGISTRY = PipelineComponentRegistry()

PIPELINE_RUNS = Counter(
    "cm_pipeline_runs_total",
    "Pipeline run count",
    ["chain_id", "status", "trigger"],
)
PIPELINE_DURATION = Histogram(
    "cm_pipeline_duration_seconds",
    "Pipeline run duration seconds",
    ["chain_id", "trigger"],
)
PIPELINE_LAST_SUCCESS_UNIX = Gauge(
    "cm_pipeline_last_success_unixtime",
    "Unix timestamp of last successful pipeline run",
    ["chain_id"],
)
PIPELINE_LAST_CANDIDATE_COUNT = Gauge(
    "cm_pipeline_last_candidate_count",
    "Candidate count in last pipeline run",
    ["chain_id"],
)


class ChainPipelineService:
    def __init__(
        self,
        chain_id: str,
        registry: PipelineComponentRegistry | None = None,
    ) -> None:
        chain_settings = get_chain_settings()
        if chain_id not in chain_settings.supported_chains:
            raise ValueError(f"unsupported chain_id: {chain_id}")

        self.settings = get_pipeline_settings()
        self._chain_settings = chain_settings
        self.chain_id = chain_id
        self.source = ChainIngestionService(chain_id=chain_id)
        components = (registry or DEFAULT_PIPELINE_REGISTRY).resolve(chain_id=chain_id)
        self.feature_engine = components.feature_engine
        self.scoring_engine = components.scoring_engine
        self.repo = PipelineRepository(get_engine())

    async def run_once(
        self,
        trigger: str = "manual",
        force: bool = False,
        ts_minute: datetime | None = None,
    ) -> PipelineRunSummary:
        run_ts = self._normalize_ts(ts_minute=ts_minute)
        if force:
            return await self.replay(ts_minute=run_ts)
        claimed = await asyncio.to_thread(
            self._claim_run,
            run_ts,
            trigger,
        )
        if claimed is None:
            return self._build_skipped_summary(trigger=trigger, run_ts=run_ts)
        run_id, strategy_version = claimed
        return await self.run_claimed(
            run_id=run_id,
            strategy_version=strategy_version,
            run_ts=run_ts,
            trigger=trigger,
        )

    def claim_scheduler_window(self, ts_minute: datetime) -> tuple[str, str, datetime] | None:
        run_ts = self._normalize_ts(ts_minute=ts_minute)
        claimed = self._claim_run(run_ts=run_ts, trigger="scheduler")
        if claimed is None:
            return None
        run_id, strategy_version = claimed
        return run_id, strategy_version, run_ts

    async def replay(self, ts_minute: datetime) -> PipelineRunSummary:
        run_ts = self._normalize_ts(ts_minute=ts_minute)
        self._validate_replay_window(run_ts=run_ts)
        replay_limit = max(1, self.settings.replay_max_in_flight_per_chain)
        stale_seconds = int(max(60.0, self.settings.run_timeout_seconds * 2))
        strategy_version = self._chain_settings.get_strategy_version(chain_id=self.chain_id)
        run_id = uuid4().hex[:16]
        with self.repo.replay_lock(chain_id=self.chain_id) as acquired:
            if not acquired:
                raise RuntimeError("replay lock not acquired")
            active_replays = self.repo.count_active_replay_runs(
                chain_id=self.chain_id,
                stale_seconds=stale_seconds,
            )
            if active_replays >= replay_limit:
                raise RuntimeError("too many in-flight replay runs")
            self.repo.insert_pipeline_run_for_replay(
                chain_id=self.chain_id,
                strategy_version=strategy_version,
                ts_minute=run_ts,
                run_id=run_id,
            )
        return await self.run_claimed(
            run_id=run_id,
            strategy_version=strategy_version,
            run_ts=run_ts,
            trigger="replay",
        )

    async def run_claimed(
        self,
        run_id: str,
        strategy_version: str,
        run_ts: datetime,
        trigger: str,
    ) -> PipelineRunSummary:
        started_at = perf_counter()
        deadline = started_at + max(5.0, self.settings.run_timeout_seconds)
        fetch_timeout = max(1.0, self.settings.fetch_timeout_seconds)
        feature_timeout = max(1.0, self.settings.feature_timeout_seconds)
        score_timeout = max(1.0, self.settings.score_timeout_seconds)
        persist_timeout = max(1.0, self.settings.persist_timeout_seconds)

        try:
            ticks = await asyncio.wait_for(
                self.source.fetch_market_ticks(ts_minute=run_ts),
                timeout=self._bounded_timeout(fetch_timeout, deadline),
            )
            ticks = self._apply_gate(ticks=ticks)
            features = await asyncio.wait_for(
                asyncio.to_thread(self.feature_engine.build_features, ticks),
                timeout=self._bounded_timeout(feature_timeout, deadline),
            )
            scores = await asyncio.wait_for(
                asyncio.to_thread(
                    self.scoring_engine.score,
                    ticks,
                    features,
                    strategy_version,
                ),
                timeout=self._bounded_timeout(score_timeout, deadline),
            )
        except asyncio.CancelledError:
            await self._mark_failed(
                strategy_version=strategy_version,
                run_ts=run_ts,
                trigger=trigger,
                run_id=run_id,
                tick_count=0,
                error_message="cancelled",
            )
            PIPELINE_RUNS.labels(chain_id=self.chain_id, status="failed", trigger=trigger).inc()
            raise
        except TimeoutError as exc:
            await self._mark_failed(
                strategy_version=strategy_version,
                run_ts=run_ts,
                trigger=trigger,
                run_id=run_id,
                tick_count=0,
                error_message=f"timeout:{type(exc).__name__}",
            )
            PIPELINE_RUNS.labels(chain_id=self.chain_id, status="failed", trigger=trigger).inc()
            raise
        except IngestionFetchError as exc:
            await self._mark_failed(
                strategy_version=strategy_version,
                run_ts=run_ts,
                trigger=trigger,
                run_id=run_id,
                tick_count=0,
                error_message=f"ingestion:{exc.reason} trace={exc.trace_id}",
            )
            PIPELINE_RUNS.labels(chain_id=self.chain_id, status="failed", trigger=trigger).inc()
            raise
        except Exception as exc:
            await self._mark_failed(
                strategy_version=strategy_version,
                run_ts=run_ts,
                trigger=trigger,
                run_id=run_id,
                tick_count=0,
                error_message=f"prepare:{type(exc).__name__}:{exc}",
            )
            PIPELINE_RUNS.labels(chain_id=self.chain_id, status="failed", trigger=trigger).inc()
            raise

        candidate_count = sum(1 for s in scores if s.tier in {"A", "B", "C"})
        try:
            updated = await asyncio.wait_for(
                asyncio.to_thread(
                    self._persist_success,
                    strategy_version,
                    run_ts,
                    run_id,
                    ticks,
                    features,
                    scores,
                    candidate_count,
                ),
                timeout=self._bounded_timeout(persist_timeout, deadline),
            )
            if not updated:
                logger.warning(
                    "skip stale success status update run_id=%s chain_id=%s trigger=%s",
                    run_id,
                    self.chain_id,
                    trigger,
                )
        except asyncio.CancelledError:
            await self._mark_failed(
                strategy_version=strategy_version,
                run_ts=run_ts,
                trigger=trigger,
                run_id=run_id,
                tick_count=len(ticks),
                error_message="cancelled",
            )
            PIPELINE_RUNS.labels(chain_id=self.chain_id, status="failed", trigger=trigger).inc()
            raise
        except TimeoutError as exc:
            await self._mark_failed(
                strategy_version=strategy_version,
                run_ts=run_ts,
                trigger=trigger,
                run_id=run_id,
                tick_count=len(ticks),
                error_message=f"persist_timeout:{type(exc).__name__}",
            )
            PIPELINE_RUNS.labels(chain_id=self.chain_id, status="failed", trigger=trigger).inc()
            raise
        except Exception as exc:
            await self._mark_failed(
                strategy_version=strategy_version,
                run_ts=run_ts,
                trigger=trigger,
                run_id=run_id,
                tick_count=len(ticks),
                error_message=f"persist:{type(exc).__name__}:{exc}",
            )
            PIPELINE_RUNS.labels(chain_id=self.chain_id, status="failed", trigger=trigger).inc()
            raise

        duration = perf_counter() - started_at
        PIPELINE_DURATION.labels(chain_id=self.chain_id, trigger=trigger).observe(duration)
        PIPELINE_RUNS.labels(chain_id=self.chain_id, status="success", trigger=trigger).inc()
        PIPELINE_LAST_SUCCESS_UNIX.labels(chain_id=self.chain_id).set(run_ts.timestamp())
        PIPELINE_LAST_CANDIDATE_COUNT.labels(chain_id=self.chain_id).set(candidate_count)

        return PipelineRunSummary(
            run_id=run_id,
            chain_id=self.chain_id,
            strategy_version=strategy_version,
            ts_minute=run_ts,
            tick_count=len(ticks),
            candidate_count=candidate_count,
            status="success",
            trigger=trigger,
            skipped=False,
        )

    def _claim_run(self, run_ts: datetime, trigger: str) -> tuple[str, str] | None:
        run_id = uuid4().hex[:16]
        strategy_version = self._chain_settings.get_strategy_version(chain_id=self.chain_id)
        started = self.repo.try_start_pipeline_run(
            chain_id=self.chain_id,
            strategy_version=strategy_version,
            ts_minute=run_ts,
            trigger=trigger,
            run_id=run_id,
        )
        if not started:
            return None
        return run_id, strategy_version

    def get_latest_candidates(self, tier: str | None = None, limit: int = 20) -> list[dict]:
        return self.repo.list_latest_candidates(
            chain_id=self.chain_id,
            tier=tier,
            limit=limit,
        )

    def get_recent_runs(self, limit: int = 50) -> list[dict]:
        return self.repo.list_recent_pipeline_runs(
            chain_id=self.chain_id,
            limit=limit,
        )

    async def aclose(self) -> None:
        await self.source.aclose()

    async def _mark_failed(
        self,
        strategy_version: str,
        run_ts: datetime,
        trigger: str,
        run_id: str,
        tick_count: int,
        error_message: str,
    ) -> None:
        updated = await asyncio.to_thread(
            self.repo.mark_pipeline_run_status,
            self.chain_id,
            strategy_version,
            run_ts,
            "failed",
            tick_count,
            0,
            self._sanitize_error_message(error_message),
            run_id,
        )
        if not updated:
            logger.warning(
                "skip stale failed status update run_id=%s chain_id=%s trigger=%s",
                run_id,
                self.chain_id,
                trigger,
            )

    def _persist_success(
        self,
        strategy_version: str,
        run_ts: datetime,
        run_id: str,
        ticks: list[MarketTickInput],
        features: list[FeatureRowInput],
        scores: list[ScoreRowInput],
        candidate_count: int,
    ) -> bool:
        with self.repo.transaction() as conn:
            self.repo.save_market_ticks(ticks, conn=conn)
            self.repo.save_features(features, conn=conn)
            self.repo.save_scores_and_candidates(scores, conn=conn)
            return self.repo.mark_pipeline_run_status(
                chain_id=self.chain_id,
                strategy_version=strategy_version,
                ts_minute=run_ts,
                status="success",
                tick_count=len(ticks),
                candidate_count=candidate_count,
                run_id=run_id,
                conn=conn,
            )

    def _normalize_ts(self, ts_minute: datetime | None) -> datetime:
        return (ts_minute or datetime.now(tz=UTC)).astimezone(UTC).replace(second=0, microsecond=0)

    def _build_skipped_summary(self, trigger: str, run_ts: datetime) -> PipelineRunSummary:
        run_id = uuid4().hex[:16]
        strategy_version = self._chain_settings.get_strategy_version(chain_id=self.chain_id)
        PIPELINE_RUNS.labels(chain_id=self.chain_id, status="skipped", trigger=trigger).inc()
        return PipelineRunSummary(
            run_id=run_id,
            chain_id=self.chain_id,
            strategy_version=strategy_version,
            ts_minute=run_ts,
            tick_count=0,
            candidate_count=0,
            status="skipped",
            trigger=trigger,
            skipped=True,
        )

    def _bounded_timeout(self, stage_timeout: float, deadline: float) -> float:
        remaining = deadline - perf_counter()
        if remaining <= 0:
            raise TimeoutError("pipeline total timeout exhausted")
        return max(0.5, min(stage_timeout, remaining))

    def _validate_replay_window(self, run_ts: datetime) -> None:
        now_real = datetime.now(tz=UTC)
        now_ts = now_real.replace(second=0, microsecond=0)
        lookback_minutes = max(1, self.settings.replay_max_lookback_minutes)
        if run_ts < now_ts - timedelta(minutes=lookback_minutes):
            raise ValueError("replay ts_minute is out of allowed lookback window")
        future_skew_seconds = max(0, self.settings.replay_max_future_skew_seconds)
        if run_ts > now_real and (run_ts - now_real).total_seconds() > future_skew_seconds:
            raise ValueError("replay ts_minute is too far in the future")

    @staticmethod
    def _sanitize_error_message(error_message: str) -> str:
        compact = re.sub(r"\s+", " ", error_message).strip()
        safe = re.sub(r"[^a-zA-Z0-9 _:\\-.,=/]", "_", compact)
        return safe[:500]

    def _apply_gate(self, ticks: list[MarketTickInput]) -> list[MarketTickInput]:
        return [
            tick
            for tick in ticks
            if tick.liquidity_usd >= self.settings.min_liquidity_usd
            and tick.volume_5m >= self.settings.min_volume_5m_usd
            and tick.tx_count_1m >= self.settings.min_tx_1m
        ]
