from __future__ import annotations

import json
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from src.shared.config import get_settings
from src.shared.schemas.backtest import BacktestConfig, BacktestMetrics
from src.shared.schemas.pipeline import FeatureRowInput, MarketTickInput, ScoreRowInput


class PipelineRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.settings = get_settings()
        self.pipeline_runs_table = "pipeline_runs"
        self._statement_timeout_ms = max(1000, self.settings.postgres_statement_timeout_ms)
        self._batch_size = max(1, self.settings.postgres_write_batch_size)
        self._candidate_cache_ttl_seconds = max(
            0.0,
            self.settings.pipeline_candidate_query_cache_ttl_seconds,
        )
        self._latest_candidates_cache: dict[
            tuple[str, str | None, int],
            tuple[float, list[dict]],
        ] = {}
        self._cache_lock = Lock()

    @contextmanager
    def transaction(self):
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            yield conn

    @contextmanager
    def _advisory_lock(self, namespace: str, chain_id: str):
        with self.engine.connect() as conn:
            acquired = bool(
                conn.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:namespace), hashtext(:chain_id))"),
                    {"namespace": namespace, "chain_id": chain_id},
                ).scalar()
            )
            try:
                yield acquired
            finally:
                if acquired:
                    conn.execute(
                        text(
                            "SELECT pg_advisory_unlock(hashtext(:namespace), hashtext(:chain_id))"
                        ),
                        {"namespace": namespace, "chain_id": chain_id},
                    )

    @contextmanager
    def scheduler_lock(self, chain_id: str):
        with self._advisory_lock(namespace="pipeline-scheduler", chain_id=chain_id) as acquired:
            yield acquired

    @contextmanager
    def replay_lock(self, chain_id: str):
        with self._advisory_lock(namespace="pipeline-replay", chain_id=chain_id) as acquired:
            yield acquired

    @staticmethod
    def _iter_batches(rows: Sequence, batch_size: int) -> list[Sequence]:
        return [rows[idx : idx + batch_size] for idx in range(0, len(rows), batch_size)]

    def _apply_statement_timeout(self, conn: Connection) -> None:
        conn.execute(
            text("SET LOCAL statement_timeout = :timeout_ms"),
            {"timeout_ms": self._statement_timeout_ms},
        )

    def save_market_ticks(
        self, rows: Sequence[MarketTickInput], conn: Connection | None = None
    ) -> None:
        if not rows:
            return
        sql = text(
            """
            INSERT INTO market_ticks (
                chain_id, token_id, ts_minute, price_usd, volume_1m, volume_5m,
                liquidity_usd, buys_1m, sells_1m, tx_count_1m
            )
            VALUES (
                :chain_id, :token_id, :ts_minute, :price_usd, :volume_1m, :volume_5m,
                :liquidity_usd, :buys_1m, :sells_1m, :tx_count_1m
            )
            ON CONFLICT (chain_id, token_id, ts_minute) DO UPDATE SET
                price_usd = EXCLUDED.price_usd,
                volume_1m = EXCLUDED.volume_1m,
                volume_5m = EXCLUDED.volume_5m,
                liquidity_usd = EXCLUDED.liquidity_usd,
                buys_1m = EXCLUDED.buys_1m,
                sells_1m = EXCLUDED.sells_1m,
                tx_count_1m = EXCLUDED.tx_count_1m
            """
        )
        payload = [row.model_dump() for row in rows]
        if conn is not None:
            for batch in self._iter_batches(payload, self._batch_size):
                conn.execute(sql, list(batch))
            return
        with self.engine.begin() as tx:
            self._apply_statement_timeout(tx)
            for batch in self._iter_batches(payload, self._batch_size):
                tx.execute(sql, list(batch))

    def save_features(
        self, rows: Sequence[FeatureRowInput], conn: Connection | None = None
    ) -> None:
        if not rows:
            return
        onchain_sql = text(
            """
            INSERT INTO onchain_flow_features (
                chain_id, token_id, ts_minute, netflow_usd_5m, netflow_usd_30m,
                large_buy_count_30m, new_holder_30m, holder_churn_24h
            )
            VALUES (
                :chain_id, :token_id, :ts_minute, :netflow_usd_5m, :netflow_usd_30m,
                :large_buy_count_30m, :new_holder_30m, :holder_churn_24h
            )
            ON CONFLICT (chain_id, token_id, ts_minute) DO UPDATE SET
                netflow_usd_5m = EXCLUDED.netflow_usd_5m,
                netflow_usd_30m = EXCLUDED.netflow_usd_30m,
                large_buy_count_30m = EXCLUDED.large_buy_count_30m,
                new_holder_30m = EXCLUDED.new_holder_30m,
                holder_churn_24h = EXCLUDED.holder_churn_24h
            """
        )
        risk_sql = text(
            """
            INSERT INTO risk_features (
                chain_id, token_id, ts_minute, contract_risk_score, lp_concentration,
                holder_concentration_top10, wash_trade_score, honeypot_flag
            )
            VALUES (
                :chain_id, :token_id, :ts_minute, :contract_risk_score, :lp_concentration,
                :holder_concentration_top10, :wash_trade_score, :honeypot_flag
            )
            ON CONFLICT (chain_id, token_id, ts_minute) DO UPDATE SET
                contract_risk_score = EXCLUDED.contract_risk_score,
                lp_concentration = EXCLUDED.lp_concentration,
                holder_concentration_top10 = EXCLUDED.holder_concentration_top10,
                wash_trade_score = EXCLUDED.wash_trade_score,
                honeypot_flag = EXCLUDED.honeypot_flag
            """
        )
        payload = [row.model_dump() for row in rows]
        if conn is not None:
            for batch in self._iter_batches(payload, self._batch_size):
                batch_payload = list(batch)
                conn.execute(onchain_sql, batch_payload)
                conn.execute(risk_sql, batch_payload)
            return
        with self.engine.begin() as tx:
            self._apply_statement_timeout(tx)
            for batch in self._iter_batches(payload, self._batch_size):
                batch_payload = list(batch)
                tx.execute(onchain_sql, batch_payload)
                tx.execute(risk_sql, batch_payload)

    def save_scores_and_candidates(
        self, rows: Sequence[ScoreRowInput], conn: Connection | None = None
    ) -> None:
        if not rows:
            return
        score_sql = text(
            """
            INSERT INTO token_scores (
                strategy_version, chain_id, token_id, ts_minute, alpha_score, momentum_score,
                smart_money_score, narrative_score, risk_penalty, final_score, conviction,
                confidence
            )
            VALUES (
                :strategy_version, :chain_id, :token_id, :ts_minute, :alpha_score, :momentum_score,
                :smart_money_score, :narrative_score, :risk_penalty, :final_score, :conviction,
                :confidence
            )
            ON CONFLICT (strategy_version, chain_id, token_id, ts_minute) DO UPDATE SET
                alpha_score = EXCLUDED.alpha_score,
                momentum_score = EXCLUDED.momentum_score,
                smart_money_score = EXCLUDED.smart_money_score,
                narrative_score = EXCLUDED.narrative_score,
                risk_penalty = EXCLUDED.risk_penalty,
                final_score = EXCLUDED.final_score,
                conviction = EXCLUDED.conviction,
                confidence = EXCLUDED.confidence
            """
        )
        candidate_sql = text(
            """
            INSERT INTO candidate_pool_snapshots (
                ts_minute, strategy_version, chain_id, token_id, tier, rank, reason_codes
            )
            VALUES (
                :ts_minute, :strategy_version, :chain_id, :token_id, :tier, :rank,
                CAST(:reason_codes AS JSON)
            )
            ON CONFLICT (strategy_version, chain_id, token_id, ts_minute) DO UPDATE SET
                tier = EXCLUDED.tier,
                rank = EXCLUDED.rank,
                reason_codes = EXCLUDED.reason_codes
            """
        )

        ranking = sorted(rows, key=lambda x: x.conviction, reverse=True)
        score_payload = [row.model_dump(exclude={"tier", "reason_codes"}) for row in rows]
        candidate_payload = [
            {
                "ts_minute": row.ts_minute,
                "strategy_version": row.strategy_version,
                "chain_id": row.chain_id,
                "token_id": row.token_id,
                "tier": row.tier,
                "rank": index + 1,
                "reason_codes": json.dumps(row.reason_codes),
            }
            for index, row in enumerate(ranking)
            if row.tier in {"A", "B", "C"}
        ]
        chain_id_for_invalidate = rows[0].chain_id
        if conn is not None:
            for batch in self._iter_batches(score_payload, self._batch_size):
                conn.execute(score_sql, list(batch))
            if candidate_payload:
                for batch in self._iter_batches(candidate_payload, self._batch_size):
                    conn.execute(candidate_sql, list(batch))
            self._invalidate_latest_candidates_cache(chain_id=chain_id_for_invalidate)
            return
        with self.engine.begin() as tx:
            self._apply_statement_timeout(tx)
            for batch in self._iter_batches(score_payload, self._batch_size):
                tx.execute(score_sql, list(batch))
            if candidate_payload:
                for batch in self._iter_batches(candidate_payload, self._batch_size):
                    tx.execute(candidate_sql, list(batch))
        self._invalidate_latest_candidates_cache(chain_id=chain_id_for_invalidate)

    def list_latest_candidates(self, chain_id: str, tier: str | None, limit: int) -> list[dict]:
        cache_key = (chain_id, tier, limit)
        if self._candidate_cache_ttl_seconds > 0:
            now = monotonic()
            with self._cache_lock:
                cached = self._latest_candidates_cache.get(cache_key)
                if cached is not None and cached[0] > now:
                    return [dict(row) for row in cached[1]]
        query = """
            WITH latest_snapshot AS (
                SELECT ts_minute
                FROM candidate_pool_snapshots
                WHERE chain_id = :chain_id
                ORDER BY ts_minute DESC
                LIMIT 1
            )
            SELECT c.ts_minute, c.strategy_version, c.chain_id, c.token_id, c.tier, c.rank,
                   c.reason_codes, s.conviction, s.final_score, s.confidence
            FROM candidate_pool_snapshots c
            JOIN token_scores s
              ON s.strategy_version = c.strategy_version
             AND s.chain_id = c.chain_id
             AND s.token_id = c.token_id
             AND s.ts_minute = c.ts_minute
            JOIN latest_snapshot latest
              ON latest.ts_minute = c.ts_minute
            WHERE c.chain_id = :chain_id
        """
        params: dict[str, object] = {"chain_id": chain_id, "limit": limit}
        if tier:
            query += " AND c.tier = :tier"
            params["tier"] = tier
        query += " ORDER BY c.rank ASC LIMIT :limit"
        sql = text(query)
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            rows = conn.execute(sql, params).mappings().all()
        result = [dict(row) for row in rows]
        if self._candidate_cache_ttl_seconds > 0:
            with self._cache_lock:
                self._latest_candidates_cache[cache_key] = (
                    monotonic() + self._candidate_cache_ttl_seconds,
                    result,
                )
        return [dict(row) for row in result]

    def try_start_pipeline_run(
        self,
        chain_id: str,
        strategy_version: str,
        ts_minute: datetime,
        trigger: str,
        run_id: str,
    ) -> bool:
        sql = text(
            f"""
            INSERT INTO {self.pipeline_runs_table} (
                run_id, chain_id, strategy_version, ts_minute, status, trigger, started_at
            )
            VALUES (
                :run_id, :chain_id, :strategy_version, :ts_minute, 'running', :trigger, :started_at
            )
            ON CONFLICT (chain_id, strategy_version, ts_minute)
            WHERE trigger <> 'replay'
            DO NOTHING
            """
        )
        params = {
            "run_id": run_id,
            "chain_id": chain_id,
            "strategy_version": strategy_version,
            "ts_minute": ts_minute,
            "trigger": trigger,
            "started_at": datetime.now(tz=UTC),
        }
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            result = conn.execute(sql, params)
        return result.rowcount > 0

    def mark_pipeline_run_status(
        self,
        chain_id: str,
        strategy_version: str,
        ts_minute: datetime,
        status: str,
        tick_count: int,
        candidate_count: int,
        error_message: str | None = None,
        run_id: str | None = None,
        conn: Connection | None = None,
    ) -> bool:
        sql = text(
            f"""
            UPDATE {self.pipeline_runs_table}
               SET status = :status,
                   ended_at = :ended_at,
                   tick_count = :tick_count,
                   candidate_count = :candidate_count,
                   error_message = :error_message
             WHERE chain_id = :chain_id
               AND strategy_version = :strategy_version
               AND ts_minute = :ts_minute
               AND (:run_id IS NULL OR run_id = :run_id)
            """
        )
        params = {
            "status": status,
            "ended_at": datetime.now(tz=UTC),
            "tick_count": tick_count,
            "candidate_count": candidate_count,
            "error_message": error_message,
            "chain_id": chain_id,
            "strategy_version": strategy_version,
            "ts_minute": ts_minute,
            "run_id": run_id,
        }
        if conn is not None:
            result = conn.execute(sql, params)
            return result.rowcount > 0
        with self.engine.begin() as tx:
            self._apply_statement_timeout(tx)
            result = tx.execute(sql, params)
        return result.rowcount > 0

    def insert_pipeline_run_for_replay(
        self,
        chain_id: str,
        strategy_version: str,
        ts_minute: datetime,
        run_id: str,
    ) -> None:
        sql = text(
            f"""
            INSERT INTO {self.pipeline_runs_table} (
                run_id, chain_id, strategy_version, ts_minute, status, trigger, started_at
            )
            VALUES (
                :run_id, :chain_id, :strategy_version, :ts_minute, 'running', 'replay', :started_at
            )
            """
        )
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            conn.execute(
                sql,
                {
                    "run_id": run_id,
                    "chain_id": chain_id,
                    "strategy_version": strategy_version,
                    "ts_minute": ts_minute,
                    "started_at": datetime.now(tz=UTC),
                },
            )

    def count_active_replay_runs(self, chain_id: str, stale_seconds: int) -> int:
        stale_after = datetime.now(tz=UTC) - timedelta(seconds=max(1, stale_seconds))
        sql = text(
            f"""
            SELECT COUNT(1)
              FROM {self.pipeline_runs_table}
             WHERE chain_id = :chain_id
               AND trigger = 'replay'
               AND status = 'running'
               AND started_at >= :stale_after
            """
        )
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            return int(
                conn.execute(
                    sql,
                    {
                        "chain_id": chain_id,
                        "stale_after": stale_after,
                    },
                ).scalar()
                or 0
            )

    def list_recent_pipeline_runs(self, chain_id: str, limit: int) -> list[dict]:
        sql = text(
            f"""
            SELECT run_id, chain_id, strategy_version, ts_minute, status, trigger,
                   started_at, ended_at, tick_count, candidate_count, error_message
              FROM {self.pipeline_runs_table}
             WHERE chain_id = :chain_id
             ORDER BY started_at DESC, run_id DESC
             LIMIT :limit
            """
        )
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            rows = conn.execute(sql, {"chain_id": chain_id, "limit": limit}).mappings().all()
        return [dict(row) for row in rows]

    def save_backtest_run(
        self,
        run_id: str,
        config: BacktestConfig,
        status: str,
        metrics: BacktestMetrics,
    ) -> None:
        run_sql = text(
            """
            INSERT INTO backtest_runs (
                run_id, strategy_version, period_start, period_end, config_json, status, created_at,
                finished_at
            )
            VALUES (
                :run_id, :strategy_version, :period_start, :period_end, CAST(:config_json AS JSON),
                :status, :created_at, :finished_at
            )
            ON CONFLICT (run_id) DO UPDATE SET
                status = EXCLUDED.status,
                config_json = EXCLUDED.config_json,
                finished_at = EXCLUDED.finished_at
            """
        )
        metrics_sql = text(
            """
            INSERT INTO backtest_metrics (
                run_id, net_pnl_usd, pf, win_rate, expectancy, max_dd_pct, sharpe_like, calmar_like,
                turnover, capacity_score
            )
            VALUES (
                :run_id, :net_pnl_usd, :pf, :win_rate, :expectancy, :max_dd_pct, :sharpe_like,
                :calmar_like, :turnover, :capacity_score
            )
            ON CONFLICT (run_id) DO UPDATE SET
                net_pnl_usd = EXCLUDED.net_pnl_usd,
                pf = EXCLUDED.pf,
                win_rate = EXCLUDED.win_rate,
                expectancy = EXCLUDED.expectancy,
                max_dd_pct = EXCLUDED.max_dd_pct,
                sharpe_like = EXCLUDED.sharpe_like,
                calmar_like = EXCLUDED.calmar_like,
                turnover = EXCLUDED.turnover,
                capacity_score = EXCLUDED.capacity_score
            """
        )
        now = datetime.now(tz=UTC)
        trade_count = max(1, metrics.trade_count)
        payload_run = {
            "run_id": run_id,
            "strategy_version": config.strategy_version,
            "period_start": config.period_start,
            "period_end": config.period_end,
            "config_json": json.dumps(config.model_dump(mode="json")),
            "status": status,
            "created_at": now,
            "finished_at": now,
        }
        payload_metrics = {
            "run_id": run_id,
            "net_pnl_usd": metrics.net_pnl_usd,
            "pf": metrics.pf,
            "win_rate": metrics.win_rate,
            "expectancy": metrics.expectancy,
            "max_dd_pct": metrics.max_dd_pct,
            "sharpe_like": metrics.expectancy / 100 if trade_count else 0.0,
            "calmar_like": (metrics.net_pnl_usd / metrics.max_dd_pct)
            if metrics.max_dd_pct > 0
            else metrics.net_pnl_usd,
            "turnover": trade_count,
            "capacity_score": max(0.0, min(1.0, 1 - metrics.max_dd_pct)),
        }
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            conn.execute(run_sql, payload_run)
            conn.execute(metrics_sql, payload_metrics)

    def save_gate2_check_result(self, run_id: str, gate2_payload: dict) -> None:
        sql = text(
            """
            UPDATE backtest_runs
               SET config_json = (
                    COALESCE(config_json::jsonb, '{}'::jsonb) || CAST(:patch AS jsonb)
               )::json,
                   finished_at = :finished_at
             WHERE run_id = :run_id
            """
        )
        patch = {"gate2_check": gate2_payload}
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            conn.execute(
                sql,
                {
                    "run_id": run_id,
                    "patch": json.dumps(patch),
                    "finished_at": datetime.now(tz=UTC),
                },
            )

    def list_recent_backtest_runs(self, chain_id: str, limit: int) -> list[dict]:
        sql = text(
            """
            SELECT br.run_id, br.strategy_version, br.period_start, br.period_end, br.status,
                   br.created_at, br.finished_at, br.config_json,
                   bm.net_pnl_usd, bm.pf, bm.win_rate, bm.expectancy, bm.max_dd_pct
              FROM backtest_runs br
              LEFT JOIN backtest_metrics bm ON bm.run_id = br.run_id
             WHERE br.config_json ->> 'chain_id' = :chain_id
             ORDER BY br.created_at DESC
             LIMIT :limit
            """
        )
        with self.engine.begin() as conn:
            self._apply_statement_timeout(conn)
            rows = conn.execute(sql, {"chain_id": chain_id, "limit": limit}).mappings().all()
        return [dict(row) for row in rows]

    def _invalidate_latest_candidates_cache(self, chain_id: str) -> None:
        if self._candidate_cache_ttl_seconds <= 0:
            return
        with self._cache_lock:
            stale_keys = [key for key in self._latest_candidates_cache if key[0] == chain_id]
            for key in stale_keys:
                self._latest_candidates_cache.pop(key, None)
