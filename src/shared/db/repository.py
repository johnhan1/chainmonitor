from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.shared.schemas.pipeline import FeatureRowInput, MarketTickInput, ScoreRowInput


class PipelineRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save_market_ticks(self, rows: Sequence[MarketTickInput]) -> None:
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
        with self.engine.begin() as conn:
            conn.execute(sql, payload)

    def save_features(self, rows: Sequence[FeatureRowInput]) -> None:
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
        with self.engine.begin() as conn:
            conn.execute(onchain_sql, payload)
            conn.execute(risk_sql, payload)

    def save_scores_and_candidates(self, rows: Sequence[ScoreRowInput]) -> None:
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
        with self.engine.begin() as conn:
            conn.execute(score_sql, score_payload)
            if candidate_payload:
                conn.execute(candidate_sql, candidate_payload)

    def list_latest_candidates(self, chain_id: str, tier: str | None, limit: int) -> list[dict]:
        query = """
            SELECT c.ts_minute, c.strategy_version, c.chain_id, c.token_id, c.tier, c.rank,
                   c.reason_codes, s.conviction, s.final_score, s.confidence
            FROM candidate_pool_snapshots c
            JOIN token_scores s
              ON s.strategy_version = c.strategy_version
             AND s.chain_id = c.chain_id
             AND s.token_id = c.token_id
             AND s.ts_minute = c.ts_minute
            WHERE c.chain_id = :chain_id
              AND c.ts_minute = (
                    SELECT MAX(ts_minute)
                    FROM candidate_pool_snapshots
                    WHERE chain_id = :chain_id
              )
        """
        params: dict[str, object] = {"chain_id": chain_id, "limit": limit}
        if tier:
            query += " AND c.tier = :tier"
            params["tier"] = tier
        query += " ORDER BY c.rank ASC LIMIT :limit"
        sql = text(query)
        with self.engine.begin() as conn:
            rows = conn.execute(sql, params).mappings().all()
        return [dict(row) for row in rows]

    def try_start_pipeline_run(
        self,
        chain_id: str,
        strategy_version: str,
        ts_minute: datetime,
        trigger: str,
    ) -> bool:
        sql = text(
            """
            INSERT INTO bsc_pipeline_runs (
                chain_id, strategy_version, ts_minute, status, trigger, started_at
            )
            VALUES (
                :chain_id, :strategy_version, :ts_minute, 'running', :trigger, :started_at
            )
            ON CONFLICT (chain_id, strategy_version, ts_minute) DO NOTHING
            """
        )
        params = {
            "chain_id": chain_id,
            "strategy_version": strategy_version,
            "ts_minute": ts_minute,
            "trigger": trigger,
            "started_at": datetime.now(tz=UTC),
        }
        with self.engine.begin() as conn:
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
    ) -> None:
        sql = text(
            """
            UPDATE bsc_pipeline_runs
               SET status = :status,
                   ended_at = :ended_at,
                   tick_count = :tick_count,
                   candidate_count = :candidate_count,
                   error_message = :error_message
             WHERE chain_id = :chain_id
               AND strategy_version = :strategy_version
               AND ts_minute = :ts_minute
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
        }
        with self.engine.begin() as conn:
            conn.execute(sql, params)

    def upsert_pipeline_run_for_replay(
        self,
        chain_id: str,
        strategy_version: str,
        ts_minute: datetime,
    ) -> None:
        sql = text(
            """
            INSERT INTO bsc_pipeline_runs (
                chain_id, strategy_version, ts_minute, status, trigger, started_at
            )
            VALUES (
                :chain_id, :strategy_version, :ts_minute, 'running', 'replay', :started_at
            )
            ON CONFLICT (chain_id, strategy_version, ts_minute)
            DO UPDATE SET
                status = 'running',
                trigger = 'replay',
                started_at = EXCLUDED.started_at,
                ended_at = NULL,
                error_message = NULL
            """
        )
        with self.engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "chain_id": chain_id,
                    "strategy_version": strategy_version,
                    "ts_minute": ts_minute,
                    "started_at": datetime.now(tz=UTC),
                },
            )

    def list_recent_pipeline_runs(self, chain_id: str, limit: int) -> list[dict]:
        sql = text(
            """
            SELECT chain_id, strategy_version, ts_minute, status, trigger,
                   started_at, ended_at, tick_count, candidate_count, error_message
              FROM bsc_pipeline_runs
             WHERE chain_id = :chain_id
             ORDER BY ts_minute DESC
             LIMIT :limit
            """
        )
        with self.engine.begin() as conn:
            rows = conn.execute(sql, {"chain_id": chain_id, "limit": limit}).mappings().all()
        return [dict(row) for row in rows]
