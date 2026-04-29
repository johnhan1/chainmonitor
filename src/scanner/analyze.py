from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine, Row

logger = logging.getLogger(__name__)

DOW_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


class ScannerAnalyzer:
    def __init__(self, engine: Engine, days: int = 7) -> None:
        self._engine = engine
        self._since = datetime.now(UTC) - timedelta(days=days)

    def _query(self, sql: str, params: dict[str, Any] | None = None) -> list[Row]:
        with self._engine.connect() as conn:
            return list(conn.execute(text(sql), params or {}))

    # ------------------------------------------------------------------
    # 1. Overview
    # ------------------------------------------------------------------
    def _overview(self) -> dict[str, Any]:
        sql = """\
SELECT
    COUNT(*)::int AS total_records,
    COUNT(DISTINCT chain)::int AS chain_count,
    COUNT(DISTINCT address)::int AS unique_tokens,
    COUNT(DISTINCT scanned_at::date)::int AS days_with_data,
    COUNT(*) FILTER (WHERE filter_passed)::int AS passed_count,
    COUNT(*) FILTER (WHERE NOT filter_passed)::int AS filtered_count,
    COUNT(*) FILTER (WHERE signal_emitted)::int AS signal_count,
    COUNT(*) FILTER (WHERE cooldown_skipped)::int AS cooldown_count,
    ROUND(AVG(score_total) FILTER (WHERE filter_passed)::numeric, 1) AS avg_score_passed,
    ROUND(AVG(score_total)::numeric, 1) AS avg_score_all
FROM scanner_token_results
WHERE scanned_at >= :since
"""
        row = self._query(sql, {"since": self._since})[0]
        total = row.total_records
        return {
            "total_records": total,
            "chain_count": row.chain_count,
            "unique_tokens": row.unique_tokens,
            "days_with_data": row.days_with_data,
            "pass_rate": round(row.passed_count / total * 100, 1) if total else 0.0,
            "filter_rate": round(row.filtered_count / total * 100, 1) if total else 0.0,
            "signal_rate": round(row.signal_count / total * 100, 1) if total else 0.0,
            "cooldown_rate": round(row.cooldown_count / total * 100, 1) if total else 0.0,
            "avg_score_passed": float(row.avg_score_passed) if row.avg_score_passed else 0.0,
            "avg_score_all": float(row.avg_score_all) if row.avg_score_all else 0.0,
        }

    # ------------------------------------------------------------------
    # 2. Filter Analysis
    # ------------------------------------------------------------------
    def _filter_analysis(self) -> dict[str, Any]:
        # 2a - rejection reason distribution
        sql1 = """\
SELECT COALESCE(filter_reason, '(passed)') AS reason,
       COUNT(*)::int AS count
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY reason
ORDER BY count DESC
"""
        rows1 = self._query(sql1, {"since": self._since})
        total = sum(r.count for r in rows1) or 1
        rejection_reasons = [
            {"reason": r.reason, "count": r.count, "pct": round(r.count / total * 100, 1)}
            for r in rows1
        ]

        # 2b - per-chain pass rate
        sql2 = """\
SELECT chain,
       COUNT(*)::int AS total,
       COUNT(*) FILTER (WHERE filter_passed)::int AS passed,
       ROUND(
           COUNT(*) FILTER (WHERE filter_passed)::numeric
           / NULLIF(COUNT(*), 0) * 100, 1
       ) AS pass_rate
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY chain
ORDER BY chain
"""
        rows2 = self._query(sql2, {"since": self._since})
        by_chain = [
            {
                "chain": r.chain,
                "total": r.total,
                "passed": r.passed,
                "pass_rate": float(r.pass_rate) if r.pass_rate else 0.0,
            }
            for r in rows2
        ]

        # 2c - daily reject rate trend
        sql3 = """\
SELECT scanned_at::date AS day,
       COUNT(*)::int AS total,
       ROUND(
           COUNT(*) FILTER (WHERE NOT filter_passed)::numeric
           / NULLIF(COUNT(*), 0) * 100, 1
       ) AS reject_rate
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY day
ORDER BY day
"""
        rows3 = self._query(sql3, {"since": self._since})
        daily_trend = [
            {"day": str(r.day), "total": r.total, "reject_rate": float(r.reject_rate)}
            for r in rows3
        ]

        return {
            "rejection_reasons": rejection_reasons,
            "by_chain": by_chain,
            "daily_trend": daily_trend,
        }

    # ------------------------------------------------------------------
    # 3. Score Distribution
    # ------------------------------------------------------------------
    def _score_distribution(self) -> dict[str, Any]:
        # histogram
        sql1 = """\
SELECT WIDTH_BUCKET(score_total, 0, 100, 10) AS bucket,
       (WIDTH_BUCKET(score_total, 0, 100, 10) - 1) * 10 AS range_start,
       COUNT(*)::int AS count
FROM scanner_token_results
WHERE scanned_at >= :since AND score_total IS NOT NULL
GROUP BY bucket, range_start
ORDER BY range_start
"""
        rows1 = self._query(sql1, {"since": self._since})
        histogram = [
            {"range_start": r.range_start, "range_end": r.range_start + 10, "count": r.count}
            for r in rows1
        ]

        # per-chain stats
        sql2 = """\
SELECT chain,
       COUNT(*)::int AS count,
       ROUND(AVG(score_total)::numeric, 1) AS avg_score,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY score_total)::numeric, 1) AS median,
       ROUND(STDDEV(score_total)::numeric, 1) AS stddev
FROM scanner_token_results
WHERE scanned_at >= :since AND score_total IS NOT NULL
GROUP BY chain
ORDER BY chain
"""
        rows2 = self._query(sql2, {"since": self._since})
        per_chain = [
            {
                "chain": r.chain,
                "count": r.count,
                "avg_score": float(r.avg_score) if r.avg_score else 0.0,
                "median": float(r.median) if r.median else 0.0,
                "stddev": float(r.stddev) if r.stddev else 0.0,
            }
            for r in rows2
        ]

        return {"histogram": histogram, "per_chain": per_chain}

    # ------------------------------------------------------------------
    # 4. Signal Analysis
    # ------------------------------------------------------------------
    def _signal_analysis(self) -> dict[str, Any]:
        # by level
        sql1 = """\
SELECT signal_level AS level,
       COUNT(*)::int AS count,
       ROUND(AVG(score_total)::numeric, 1) AS avg_score
FROM scanner_token_results
WHERE scanned_at >= :since AND signal_emitted
GROUP BY signal_level
ORDER BY signal_level
"""
        rows1 = self._query(sql1, {"since": self._since})
        by_level = [
            {
                "level": r.level,
                "count": r.count,
                "avg_score": float(r.avg_score) if r.avg_score else 0.0,
            }
            for r in rows1
        ]

        # by chain
        sql2 = """\
SELECT chain,
       COUNT(*)::int AS total,
       COUNT(*) FILTER (WHERE signal_emitted)::int AS signals,
       ROUND(
           COUNT(*) FILTER (WHERE signal_emitted)::numeric
           / NULLIF(COUNT(*), 0) * 100, 1
       ) AS signal_rate
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY chain
ORDER BY chain
"""
        rows2 = self._query(sql2, {"since": self._since})
        by_chain = [
            {
                "chain": r.chain,
                "total": r.total,
                "signals": r.signals,
                "signal_rate": float(r.signal_rate) if r.signal_rate else 0.0,
            }
            for r in rows2
        ]

        return {"by_level": by_level, "by_chain": by_chain}

    # ------------------------------------------------------------------
    # 5. Factor Breakdown
    # ------------------------------------------------------------------
    def _factor_breakdown(self) -> dict[str, Any]:
        # overall averages for filter_passed tokens with score_breakdown
        sql1 = """\
SELECT
    ROUND(AVG((score_breakdown->>'smart_money')::int)::numeric, 1) AS smart_money,
    ROUND(AVG((score_breakdown->>'rank_momentum')::int)::numeric, 1) AS rank_momentum,
    ROUND(AVG((score_breakdown->>'volume_quality')::int)::numeric, 1) AS volume_quality,
    ROUND(AVG((score_breakdown->>'structure')::int)::numeric, 1) AS structure,
    ROUND(AVG((score_breakdown->>'volume_acceleration')::int)::numeric, 1) AS volume_acceleration,
    ROUND(AVG((score_breakdown->>'timeframe')::int)::numeric, 1) AS timeframe,
    ROUND(AVG((score_breakdown->>'risk_penalty')::int)::numeric, 1) AS risk_penalty,
    COUNT(*)::int AS sample_count
FROM scanner_token_results
WHERE scanned_at >= :since
  AND filter_passed
  AND score_breakdown IS NOT NULL
  AND score_breakdown::text != 'null'
"""
        rows1 = self._query(sql1, {"since": self._since})
        overall = rows1[0]
        factor_keys = [
            "smart_money",
            "rank_momentum",
            "volume_quality",
            "structure",
            "volume_acceleration",
            "timeframe",
            "risk_penalty",
        ]
        overall_averages = {
            k: float(getattr(overall, k)) if getattr(overall, k) else 0.0 for k in factor_keys
        }
        overall_sample_count = overall.sample_count

        # factor/total_score ratios for filter_passed tokens
        # SAFE: factor_keys is hardcoded above — no user input enters this f-string
        ratio_extracts = ", ".join(
            f"ROUND(AVG(((score_breakdown->>'{k}')::int)"
            f" / NULLIF(score_total, 0))::numeric, 3) AS {k}"
            for k in factor_keys
        )
        sql_ratios = f"""\
SELECT {ratio_extracts}
FROM scanner_token_results
WHERE scanned_at >= :since
  AND filter_passed
  AND score_total > 0
  AND score_breakdown IS NOT NULL
  AND score_breakdown::text != 'null'
"""
        ratio_rows = self._query(sql_ratios, {"since": self._since})
        overall_ratios = (
            {k: float(getattr(ratio_rows[0], k)) for k in factor_keys}
            if ratio_rows
            else {k: 0.0 for k in factor_keys}
        )

        # per signal_level factor averages
        sql2 = """\
SELECT signal_level AS level,
    ROUND(AVG((score_breakdown->>'smart_money')::int)::numeric, 1) AS smart_money,
    ROUND(AVG((score_breakdown->>'rank_momentum')::int)::numeric, 1) AS rank_momentum,
    ROUND(AVG((score_breakdown->>'volume_quality')::int)::numeric, 1) AS volume_quality,
    ROUND(AVG((score_breakdown->>'structure')::int)::numeric, 1) AS structure,
    ROUND(AVG((score_breakdown->>'volume_acceleration')::int)::numeric, 1) AS volume_acceleration,
    ROUND(AVG((score_breakdown->>'timeframe')::int)::numeric, 1) AS timeframe,
    ROUND(AVG((score_breakdown->>'risk_penalty')::int)::numeric, 1) AS risk_penalty,
    COUNT(*)::int AS sample_count
FROM scanner_token_results
WHERE scanned_at >= :since
  AND filter_passed
  AND signal_emitted
  AND score_breakdown IS NOT NULL
  AND score_breakdown::text != 'null'
GROUP BY signal_level
ORDER BY signal_level
"""
        rows2 = self._query(sql2, {"since": self._since})
        by_signal_level = [
            {
                "level": r.level,
                "avg_factors": {
                    k: float(getattr(r, k)) if getattr(r, k) else 0.0 for k in factor_keys
                },
                "sample_count": r.sample_count,
            }
            for r in rows2
        ]

        return {
            "overall_averages": overall_averages,
            "overall_ratios": overall_ratios,
            "sample_count": overall_sample_count,
            "by_signal_level": by_signal_level,
        }

    # ------------------------------------------------------------------
    # 6. Chain Comparison
    # ------------------------------------------------------------------
    def _chain_comparison(self) -> list[dict[str, Any]]:
        sql = """\
SELECT chain,
       COUNT(*)::int AS total_scans,
       COUNT(DISTINCT address)::int AS unique_tokens,
       COUNT(*) FILTER (WHERE filter_passed)::int AS passed,
       ROUND(
           COUNT(*) FILTER (WHERE filter_passed)::numeric
           / NULLIF(COUNT(*), 0) * 100, 1
       ) AS pass_rate,
       ROUND(AVG(score_total) FILTER (WHERE filter_passed)::numeric, 1) AS avg_score,
       COUNT(*) FILTER (WHERE signal_emitted)::int AS signals,
       ROUND(
           COUNT(*) FILTER (WHERE signal_emitted)::numeric
           / NULLIF(COUNT(*) FILTER (WHERE filter_passed), 0) * 100, 1
       ) AS signal_rate_of_passed,
       COUNT(*) FILTER (WHERE cooldown_skipped)::int AS cooldowns
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY chain
ORDER BY chain
"""
        rows = self._query(sql, {"since": self._since})
        return [
            {
                "chain": r.chain,
                "total_scans": r.total_scans,
                "unique_tokens": r.unique_tokens,
                "passed": r.passed,
                "pass_rate": float(r.pass_rate) if r.pass_rate else 0.0,
                "avg_score": float(r.avg_score) if r.avg_score else 0.0,
                "signals": r.signals,
                "signal_rate_of_passed": (
                    float(r.signal_rate_of_passed) if r.signal_rate_of_passed else 0.0
                ),
                "cooldowns": r.cooldowns,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 7. Temporal Patterns
    # ------------------------------------------------------------------
    def _temporal_patterns(self) -> dict[str, Any]:
        # by hour
        sql1 = """\
SELECT EXTRACT(HOUR FROM scanned_at)::int AS hour,
       COUNT(*)::int AS count,
       COUNT(*) FILTER (WHERE signal_emitted)::int AS signals,
       ROUND(AVG(score_total)::numeric, 1) AS avg_score
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY hour
ORDER BY hour
"""
        rows1 = self._query(sql1, {"since": self._since})
        by_hour = [
            {
                "hour": r.hour,
                "count": r.count,
                "signals": r.signals,
                "avg_score": float(r.avg_score),
            }
            for r in rows1
        ]

        # by day of week
        sql2 = """\
SELECT EXTRACT(DOW FROM scanned_at)::int AS dow,
       COUNT(*)::int AS count,
       COUNT(*) FILTER (WHERE signal_emitted)::int AS signals,
       ROUND(AVG(score_total)::numeric, 1) AS avg_score
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY dow
ORDER BY dow
"""
        rows2 = self._query(sql2, {"since": self._since})
        by_dow = [
            {
                "dow": r.dow,
                "dow_name": DOW_NAMES[r.dow],
                "count": r.count,
                "signals": r.signals,
                "avg_score": float(r.avg_score),
            }
            for r in rows2
        ]

        # daily trend
        sql3 = """\
SELECT scanned_at::date AS day,
       COUNT(*)::int AS count,
       COUNT(*) FILTER (WHERE signal_emitted)::int AS signals,
       ROUND(AVG(score_total)::numeric, 1) AS avg_score
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY day
ORDER BY day
"""
        rows3 = self._query(sql3, {"since": self._since})
        daily_trend = [
            {
                "day": str(r.day),
                "count": r.count,
                "signals": r.signals,
                "avg_score": float(r.avg_score),
            }
            for r in rows3
        ]

        return {"by_hour": by_hour, "by_dow": by_dow, "daily_trend": daily_trend}

    # ------------------------------------------------------------------
    # 8. Token Spotlight
    # ------------------------------------------------------------------
    def _token_spotlight(self) -> dict[str, Any]:
        # most scanned
        sql1 = """\
SELECT symbol, address, chain, COUNT(*)::int AS count
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY symbol, address, chain
ORDER BY count DESC
LIMIT 20
"""
        rows1 = self._query(sql1, {"since": self._since})
        most_scanned = [
            {"symbol": r.symbol, "address": r.address, "chain": r.chain, "count": r.count}
            for r in rows1
        ]

        # most signals
        sql2 = """\
SELECT symbol, address, chain,
       COUNT(*)::int AS total,
       COUNT(*) FILTER (WHERE signal_emitted)::int AS signal_count
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY symbol, address, chain
HAVING COUNT(*) FILTER (WHERE signal_emitted) > 0
ORDER BY signal_count DESC
LIMIT 20
"""
        rows2 = self._query(sql2, {"since": self._since})
        most_signals = [
            {
                "symbol": r.symbol,
                "address": r.address,
                "chain": r.chain,
                "total": r.total,
                "signal_count": r.signal_count,
            }
            for r in rows2
        ]

        # top avg score
        sql3 = """\
SELECT symbol, address, chain,
       COUNT(*)::int AS count,
       ROUND(AVG(score_total)::numeric, 1) AS avg_score
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY symbol, address, chain
HAVING COUNT(*) >= 3
ORDER BY avg_score DESC
LIMIT 20
"""
        rows3 = self._query(sql3, {"since": self._since})
        top_avg_score = [
            {
                "symbol": r.symbol,
                "address": r.address,
                "chain": r.chain,
                "count": r.count,
                "avg_score": float(r.avg_score) if r.avg_score else 0.0,
            }
            for r in rows3
        ]

        return {
            "most_scanned": most_scanned,
            "most_signals": most_signals,
            "top_avg_score": top_avg_score,
        }

    # ------------------------------------------------------------------
    # 9. Cooldown Analysis
    # ------------------------------------------------------------------
    def _cooldown_analysis(self) -> dict[str, Any]:
        # overall
        sql1 = """\
SELECT COUNT(*) FILTER (WHERE cooldown_skipped)::int AS total_skipped,
       COUNT(*)::int AS total,
       ROUND(AVG(score_total) FILTER (WHERE cooldown_skipped)::numeric, 1) AS avg_score_skipped
FROM scanner_token_results
WHERE scanned_at >= :since
"""
        row = self._query(sql1, {"since": self._since})[0]
        total = row.total or 1

        # per chain
        sql2 = """\
SELECT chain,
       COUNT(*) FILTER (WHERE cooldown_skipped)::int AS skipped,
       COUNT(*)::int AS total,
       ROUND(AVG(score_total) FILTER (WHERE cooldown_skipped)::numeric, 1) AS avg_score_skipped
FROM scanner_token_results
WHERE scanned_at >= :since
GROUP BY chain
ORDER BY chain
"""
        rows2 = self._query(sql2, {"since": self._since})
        by_chain = [
            {
                "chain": r.chain,
                "skipped": r.skipped,
                "skip_rate": round(r.skipped / r.total * 100, 1) if r.total else 0.0,
                "avg_score_skipped": float(r.avg_score_skipped) if r.avg_score_skipped else 0.0,
            }
            for r in rows2
        ]

        return {
            "total_skipped": row.total_skipped,
            "skip_rate": round(row.total_skipped / total * 100, 1),
            "avg_score_skipped": float(row.avg_score_skipped) if row.avg_score_skipped else 0.0,
            "by_chain": by_chain,
        }

    # ------------------------------------------------------------------
    # 10. Threshold Sensitivity
    # ------------------------------------------------------------------
    def _threshold_sensitivity(self) -> dict[str, Any]:
        # current bands
        sql1 = """\
SELECT
    CASE
        WHEN score_total >= 75 THEN '75-100'
        WHEN score_total >= 65 THEN '65-74'
        WHEN score_total >= 55 THEN '55-64'
        ELSE '0-54'
    END AS band,
    COUNT(*)::int AS count,
    COUNT(*) FILTER (WHERE signal_emitted)::int AS signals
FROM scanner_token_results
WHERE scanned_at >= :since AND filter_passed
GROUP BY band
ORDER BY band
"""
        rows1 = self._query(sql1, {"since": self._since})
        current_bands = [{"band": r.band, "count": r.count, "signals": r.signals} for r in rows1]

        # sensitivity: how many filter_passed tokens at shifted thresholds per band
        sensitivity_queries = [
            # HIGH: 75 (current), -5→70, +5→80
            ("high_current", "COUNT(*) FILTER (WHERE score_total >= 75)::int"),
            ("high_minus", "COUNT(*) FILTER (WHERE score_total >= 70)::int"),
            ("high_plus", "COUNT(*) FILTER (WHERE score_total >= 80)::int"),
            # MEDIUM: 65 (current), -5→60, +5→70
            ("medium_current", "COUNT(*) FILTER (WHERE score_total >= 65)::int"),
            ("medium_minus", "COUNT(*) FILTER (WHERE score_total >= 60)::int"),
            ("medium_plus", "COUNT(*) FILTER (WHERE score_total >= 70)::int"),
            # OBSERVE: 55 (current), -5→50, +5→60
            ("observe_current", "COUNT(*) FILTER (WHERE score_total >= 55)::int"),
            ("observe_minus", "COUNT(*) FILTER (WHERE score_total >= 50)::int"),
            ("observe_plus", "COUNT(*) FILTER (WHERE score_total >= 60)::int"),
        ]

        select_parts = [f'{part} AS "{k}"' for k, part in sensitivity_queries]
        sql2 = f"""\
SELECT {", ".join(select_parts)}
FROM scanner_token_results
WHERE scanned_at >= :since AND filter_passed
"""
        row2 = self._query(sql2, {"since": self._since})[0]
        r = row2
        sensitivity = {
            "high": {"current": r.high_current, "minus": r.high_minus, "plus": r.high_plus},
            "medium": {"current": r.medium_current, "minus": r.medium_minus, "plus": r.medium_plus},
            "observe": {
                "current": r.observe_current,
                "minus": r.observe_minus,
                "plus": r.observe_plus,
            },
        }

        return {"current_bands": current_bands, "sensitivity": sensitivity}

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def analyze(self) -> dict[str, Any]:
        return {
            "overview": self._overview(),
            "filter_analysis": self._filter_analysis(),
            "score_distribution": self._score_distribution(),
            "signal_analysis": self._signal_analysis(),
            "factor_breakdown": self._factor_breakdown(),
            "chain_comparison": self._chain_comparison(),
            "temporal_patterns": self._temporal_patterns(),
            "token_spotlight": self._token_spotlight(),
            "cooldown_analysis": self._cooldown_analysis(),
            "threshold_sensitivity": self._threshold_sensitivity(),
        }


# ═══════════════════════════════════════════════════════════════════
# ReportGenerator
# ═══════════════════════════════════════════════════════════════════


class ReportGenerator:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def to_markdown(self) -> str:
        buf = io.StringIO()
        d = self._data
        overview = d.get("overview", {})

        # Title + Meta
        buf.write("# Scanner 分析报告\n\n")
        records = overview.get("total_records", 0)
        tokens = overview.get("unique_tokens", 0)
        chains = overview.get("chain_count", 0)
        days = overview.get("days_with_data", 0)
        buf.write(f"**分析周期**: 最近 {days} 天 | ")
        buf.write(f"**总记录**: {records} | ")
        buf.write(f"**唯一代币**: {tokens} | ")
        buf.write(f"**链数**: {chains}\n\n")
        buf.write("---\n\n")

        # 1. Overview
        buf.write("## 1. 全局概览\n\n")
        buf.write("| 指标 | 值 |\n|---|---|\n")
        buf.write(f"| 总记录数 | {records} |\n")
        buf.write(f"| 链数 | {chains} |\n")
        buf.write(f"| 唯一代币数 | {tokens} |\n")
        buf.write(f"| 有数据天数 | {days} |\n")
        buf.write(f"| 通过率 | {overview.get('pass_rate', 0)}% |\n")
        buf.write(f"| 过滤率 | {overview.get('filter_rate', 0)}% |\n")
        buf.write(f"| 信号率 | {overview.get('signal_rate', 0)}% |\n")
        buf.write(f"| 冷却跳过率 | {overview.get('cooldown_rate', 0)}% |\n")
        buf.write(f"| 平均分(全部) | {overview.get('avg_score_all', 0)} |\n")
        buf.write(f"| 平均分(通过) | {overview.get('avg_score_passed', 0)} |\n")
        buf.write("\n---\n\n")

        # 2. Filter Analysis
        buf.write("## 2. 过滤管道分析\n\n")
        fa = d.get("filter_analysis", {})

        # rejection reasons
        buf.write("### 拒绝原因分布\n\n")
        buf.write("| 原因 | 数量 | 占比 |\n|---|---|---|\n")
        for rr in fa.get("rejection_reasons", []):
            buf.write(f"| {rr['reason']} | {rr['count']} | {rr['pct']}% |\n")
        buf.write("\n")

        # per-chain pass rate
        buf.write("### 各链通过率\n\n")
        buf.write("| 链 | 总数 | 通过 | 通过率 |\n|---|---|---|---|\n")
        for bc in fa.get("by_chain", []):
            buf.write(f"| {bc['chain']} | {bc['total']} | {bc['passed']} | {bc['pass_rate']}% |\n")
        buf.write("\n")

        # daily reject trend
        buf.write("### 每日拒绝率趋势\n\n")
        buf.write("| 日期 | 总数 | 拒绝率 |\n|---|---|---|\n")
        for dt in fa.get("daily_trend", []):
            buf.write(f"| {dt['day']} | {dt['total']} | {dt['reject_rate']}% |\n")
        buf.write("\n---\n\n")

        # 3. Score Distribution
        buf.write("## 3. 分数分布\n\n")
        sd = d.get("score_distribution", {})

        # histogram
        buf.write("### 分数直方图\n\n")
        buf.write("```\n")
        hist = sd.get("histogram", [])
        max_count = max((b["count"] for b in hist), default=1)
        for b in hist:
            bar_len = int(b["count"] / max_count * 30)
            bar = "█" * bar_len
            buf.write(f"  {b['range_start']:>3}-{b['range_end']:<3} | {bar} {b['count']}\n")
        buf.write("```\n\n")

        # per-chain stats
        buf.write("### 各链分数统计\n\n")
        buf.write("| 链 | 数量 | 平均分 | 中位数 | 标准差 |\n|---|---|---|---|---|\n")
        for pc in sd.get("per_chain", []):
            buf.write(
                f"| {pc['chain']} | {pc['count']} | {pc['avg_score']} | "
                f"{pc['median']} | {pc['stddev']} |\n"
            )
        buf.write("\n---\n\n")

        # 4. Signal Analysis
        buf.write("## 4. 信号分析\n\n")
        sa = d.get("signal_analysis", {})

        buf.write("### 信号等级分布\n\n")
        buf.write("| 等级 | 数量 | 平均分 |\n|---|---|---|\n")
        for bl in sa.get("by_level", []):
            buf.write(f"| {bl['level']} | {bl['count']} | {bl['avg_score']} |\n")
        buf.write("\n")

        buf.write("### 各链信号率\n\n")
        buf.write("| 链 | 总数 | 信号数 | 信号率 |\n|---|---|---|---|\n")
        for bc in sa.get("by_chain", []):
            buf.write(
                f"| {bc['chain']} | {bc['total']} | {bc['signals']} | {bc['signal_rate']}% |\n"
            )
        buf.write("\n---\n\n")

        # 5. Factor Breakdown
        buf.write("## 5. 因子拆解\n\n")
        fb = d.get("factor_breakdown", {})

        factor_names = [
            ("smart_money", "聪明钱"),
            ("rank_momentum", "排名动量"),
            ("volume_quality", "成交量质量"),
            ("structure", "结构"),
            ("volume_acceleration", "成交量加速"),
            ("timeframe", "时间框架"),
            ("risk_penalty", "风险惩罚"),
        ]

        buf.write("### 整体因子平均值\n\n")
        buf.write(f"样本数: {fb.get('sample_count', 0)}\n\n")
        oa = fb.get("overall_averages", {})
        or_ = fb.get("overall_ratios", {})
        buf.write("| 因子 | 平均值 | 占分比 |\n|---|---|---|\n")
        for key, label in factor_names:
            avg_val = oa.get(key, 0)
            ratio_val = or_.get(key, 0)
            buf.write(f"| {label} | {avg_val} | {ratio_val} |\n")
        buf.write("\n")
        # per-level comparison
        buf.write("### 各信号等级因子对比\n\n")
        levels = fb.get("by_signal_level", [])
        if levels:
            header = "| 等级 | " + " | ".join(label for _, label in factor_names) + " | 样本数 |\n"
            buf.write(header)
            sep = "|---|" + "---|" * len(factor_names) + "---|\n"
            buf.write(sep)
            for lv in levels:
                row = f"| {lv['level']} "
                for key, _ in factor_names:
                    row += f"| {lv['avg_factors'].get(key, 0)} "
                row += f"| {lv['sample_count']} |\n"
                buf.write(row)
        buf.write("\n---\n\n")

        # 6. Chain Comparison
        buf.write("## 6. 链对比\n\n")
        cc = d.get("chain_comparison", [])
        buf.write(
            "| 链 | 扫描数 | 唯一代币 | 通过 | 通过率 | 均分(通过) | 信号 | 信号率(通过) | 冷却 |\n"
        )
        buf.write("|---|---|---|---|---|---|---|---|---|\n")
        for c in cc:
            buf.write(
                f"| {c['chain']} | {c['total_scans']} | {c['unique_tokens']} | "
                f"{c['passed']} | {c['pass_rate']}% | {c['avg_score']} | "
                f"{c['signals']} | {c['signal_rate_of_passed']}% | {c['cooldowns']} |\n"
            )
        buf.write("\n---\n\n")

        # 7. Temporal Patterns
        buf.write("## 7. 时间模式\n\n")
        tp = d.get("temporal_patterns", {})

        buf.write("### 按小时\n\n")
        buf.write("| 小时 | 数量 | 信号 | 平均分 |\n|---|---|---|---|\n")
        for h in tp.get("by_hour", []):
            buf.write(f"| {h['hour']:>2}:00 | {h['count']} | {h['signals']} | {h['avg_score']} |\n")
        buf.write("\n")

        buf.write("### 按星期\n\n")
        buf.write("| 星期 | 数量 | 信号 | 平均分 |\n|---|---|---|---|\n")
        for d_ in tp.get("by_dow", []):
            buf.write(
                f"| {d_['dow_name']} | {d_['count']} | {d_['signals']} | {d_['avg_score']} |\n"
            )
        buf.write("\n")

        buf.write("### 每日趋势\n\n")
        buf.write("| 日期 | 数量 | 信号 | 平均分 |\n|---|---|---|---|\n")
        for d_ in tp.get("daily_trend", []):
            buf.write(f"| {d_['day']} | {d_['count']} | {d_['signals']} | {d_['avg_score']} |\n")
        buf.write("\n---\n\n")

        # 8. Token Spotlight
        buf.write("## 8. 代币聚焦\n\n")

        buf.write("### 最高扫描频次\n\n")
        buf.write("| 排名 | 代币 | 地址 | 链 | 次数 |\n|---|---|---|---|---|\n")
        for idx, t in enumerate(d.get("token_spotlight", {}).get("most_scanned", [])[:10], 1):
            addr_short = t["address"][:10] + "..." if len(t["address"]) > 10 else t["address"]
            buf.write(f"| {idx} | {t['symbol']} | `{addr_short}` | {t['chain']} | {t['count']} |\n")
        buf.write("\n")

        buf.write("### 最高信号频次\n\n")
        buf.write("| 排名 | 代币 | 地址 | 链 | 信号数 | 总次数 |\n|---|---|---|---|---|---|\n")
        for idx, t in enumerate(d.get("token_spotlight", {}).get("most_signals", [])[:10], 1):
            addr_short = t["address"][:10] + "..." if len(t["address"]) > 10 else t["address"]
            buf.write(
                f"| {idx} | {t['symbol']} | `{addr_short}` | {t['chain']} | "
                f"{t['signal_count']} | {t['total']} |\n"
            )
        buf.write("\n---\n\n")

        # 9. Cooldown Analysis
        buf.write("## 9. 冷却分析\n\n")
        ca = d.get("cooldown_analysis", {})
        buf.write(f"- **总冷却跳过**: {ca.get('total_skipped', 0)}\n")
        buf.write(f"- **冷却跳过率**: {ca.get('skip_rate', 0)}%\n")
        buf.write(f"- **跳过时平均分**: {ca.get('avg_score_skipped', 0)}\n\n")

        buf.write("### 各链冷却统计\n\n")
        buf.write("| 链 | 跳过数 | 跳过率 | 跳过均分 |\n|---|---|---|---|\n")
        for c in ca.get("by_chain", []):
            buf.write(
                f"| {c['chain']} | {c['skipped']} | {c['skip_rate']}% | "
                f"{c['avg_score_skipped']} |\n"
            )
        buf.write("\n---\n\n")

        # 10. Threshold Sensitivity
        buf.write("## 10. 阈值敏感性\n\n")
        ts = d.get("threshold_sensitivity", {})

        buf.write("### 当前分数段\n\n")
        buf.write("| 分数段 | 数量 | 信号数 |\n|---|---|---|\n")
        for b in ts.get("current_bands", []):
            buf.write(f"| {b['band']} | {b['count']} | {b['signals']} |\n")
        buf.write("\n")

        buf.write("### 阈值调整影响\n\n")
        buf.write("| 等级 | 当前阈值 | 当前通过数 | -5 分 | +5 分 |\n")
        buf.write("|---|---|---|---|---|\n")
        sens = ts.get("sensitivity", {})
        bands = [
            ("HIGH", sens.get("high", {}), 75),
            ("MEDIUM", sens.get("medium", {}), 65),
            ("OBSERVE", sens.get("observe", {}), 55),
        ]
        for label, s, base in bands:
            curr = s.get("current", 0)
            minus = s.get("minus", 0)
            plus = s.get("plus", 0)
            buf.write(
                f"| {label} | ≥{base} | {curr} | ≥{base - 5}: {minus} | ≥{base + 5}: {plus} |\n"
            )
        buf.write("\n")

        return buf.getvalue()

    def to_json(self) -> str:
        metadata = self._data.get("overview", {})
        payload = {
            "metadata": {
                "generated_at": datetime.now(UTC).isoformat(),
                "total_records": metadata.get("total_records", 0),
                "date_range": f"last {metadata.get('days_with_data', 0)} days",
            },
            **self._data,
        }
        return json.dumps(payload, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════


def _positive_int(v: str) -> int:
    i = int(v)
    if i <= 0:
        raise argparse.ArgumentTypeError(f"must be positive, got {i}")
    return i


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="scanner_token_results 分析报告")
    p.add_argument("--days", type=_positive_int, default=7, help="分析最近 N 天 (default: 7)")
    p.add_argument(
        "--output",
        type=str,
        default="",
        help="报告输出路径 (default: scanner-report-YYYY-MM-DD.md)",
    )
    p.add_argument("--json", action="store_true", help="额外输出 JSON 数据供 LLM 分析")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    output_path = args.output or f"scanner-report-{today_str}.md"

    try:
        from src.shared.db.session import get_engine

        engine = get_engine()
    except Exception as e:
        print(f"ERROR: 无法连接数据库: {e}", file=sys.stderr)
        return 1

    analyzer = ScannerAnalyzer(engine, days=args.days)
    try:
        data = analyzer.analyze()
    except Exception as e:
        print(f"ERROR: 分析失败: {e}", file=sys.stderr)
        return 1

    gen = ReportGenerator(data)
    report = gen.to_markdown()
    Path(output_path).write_text(report, encoding="utf-8")
    print(f"报告已生成: {output_path}")

    if args.json:
        json_path = output_path.rsplit(".", 1)[0] + ".json"
        Path(json_path).write_text(gen.to_json(), encoding="utf-8")
        print(f"JSON 数据已生成: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
