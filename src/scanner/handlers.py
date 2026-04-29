from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, TextIO

from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.scanner.events import (
    ChainScanCompleted,
    TokenProcessed,
    TokenSecurityChecked,
    TrendingFetched,
)
from src.scanner.metrics import ScannerMetrics

logger = logging.getLogger(__name__)


class StructuredLogHandler:
    def __init__(self, logger_name: str = "src.scanner.events") -> None:
        self._logger = logging.getLogger(logger_name)

    def __call__(self, event: TokenProcessed) -> None:
        extra = asdict(event)
        for k, v in extra.items():
            if isinstance(v, datetime):
                extra[k] = v.isoformat()
        self._logger.info(type(event).__name__, extra=extra)


class DatabaseEventHandler:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __call__(self, event: TokenProcessed) -> None:
        data = asdict(event)
        breakdown = data.pop("score_breakdown")
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO scanner_token_results
                        (chain, interval, scanned_at, address, symbol,
                         filter_passed, filter_reason,
                         score_total, score_breakdown,
                         signal_emitted, signal_level, cooldown_skipped)
                    VALUES
                        (:chain, :interval, :scanned_at, :address, :symbol,
                         :filter_passed, :filter_reason,
                         :score_total, CAST(:score_breakdown AS JSONB),
                         :signal_emitted, :signal_level, :cooldown_skipped)
                """),
                {
                    "chain": data["chain"],
                    "interval": data["interval"],
                    "scanned_at": data["scanned_at"],
                    "address": data["address"],
                    "symbol": data["symbol"],
                    "filter_passed": data["filter_passed"],
                    "filter_reason": data["filter_reason"],
                    "score_total": data["score_total"],
                    "score_breakdown": json.dumps(breakdown) if breakdown else None,
                    "signal_emitted": data["signal_emitted"],
                    "signal_level": data["signal_level"],
                    "cooldown_skipped": data["cooldown_skipped"],
                },
            )


class FileEventHandler:
    def __init__(self, log_dir: str = "logs") -> None:
        self._log_dir = log_dir
        self._file: TextIO | None = None
        self._date: str | None = None

    def __call__(self, event: TokenProcessed) -> None:
        self._ensure_file()
        self._file.write(json.dumps(asdict(event), default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
            self._date = None

    def _ensure_file(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._date:
            if self._file:
                self._file.close()
            os.makedirs(self._log_dir, exist_ok=True)
            path = os.path.join(self._log_dir, f"scanner-analysis-{today}.jsonl")
            self._file = open(path, "a", encoding="utf-8")
            self._date = today


class MetricsHandler:
    def __init__(self, metrics: ScannerMetrics) -> None:
        self._metrics = metrics

    def __call__(self, event: Any) -> None:
        if isinstance(event, TrendingFetched):
            self._metrics.trending_duration.labels(event.chain, event.interval).observe(
                event.duration_ms / 1000.0
            )
            self._metrics.trending_tokens.labels(event.chain).inc(event.token_count)
        elif isinstance(event, TokenSecurityChecked):
            self._metrics.security_duration.labels(event.chain).observe(event.duration_ms / 1000.0)
            self._metrics.security_checks.labels(
                event.chain, "ok" if event.success else "fail"
            ).inc()
        elif isinstance(event, ChainScanCompleted):
            self._metrics.chain_duration.labels(event.chain, event.interval).observe(
                event.total_duration_ms / 1000.0
            )
