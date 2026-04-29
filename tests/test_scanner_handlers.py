from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec

from prometheus_client import CollectorRegistry
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.engine import Engine
from src.scanner.events import (
    ChainScanCompleted,
    TokenProcessed,
    TrendingFetched,
)
from src.scanner.handlers import (
    DatabaseEventHandler,
    FileEventHandler,
    MetricsHandler,
    StructuredLogHandler,
)
from src.scanner.metrics import ScannerMetrics


def test_structured_log_handler_emits_token_processed() -> None:
    logger = logging.getLogger("test_events_handler")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)

    log_handler = StructuredLogHandler(logger_name="test_events_handler")
    now = datetime.now(UTC)
    log_handler(
        TokenProcessed(
            chain="sol",
            interval="1m",
            scanned_at=now,
            address="0xabc",
            symbol="TEST",
            filter_passed=False,
            filter_reason="liquidity",
            score_total=None,
            score_breakdown=None,
            signal_emitted=False,
            signal_level=None,
            cooldown_skipped=False,
        )
    )

    record = json.loads(stream.getvalue())
    assert record["message"] == "TokenProcessed"
    assert record["chain"] == "sol"
    assert record["filter_passed"] is False
    assert record["filter_reason"] == "liquidity"


def test_database_event_handler_inserts_token() -> None:
    mock_conn = MagicMock()
    mock_engine = create_autospec(Engine)
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    handler = DatabaseEventHandler(engine=mock_engine)
    now = datetime.now(UTC)
    handler(
        TokenProcessed(
            chain="sol",
            interval="1m",
            scanned_at=now,
            address="0xabc",
            symbol="TEST",
            filter_passed=True,
            filter_reason="",
            score_total=80,
            score_breakdown={"smart_money": 30},
            signal_emitted=True,
            signal_level="HIGH",
            cooldown_skipped=False,
        )
    )

    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args[0][1]
    assert call_args["chain"] == "sol"
    assert call_args["address"] == "0xabc"
    assert call_args["score_total"] == 80
    assert call_args["signal_emitted"] is True
    assert call_args["signal_level"] == "HIGH"


def test_database_event_handler_none_breakdown() -> None:
    mock_conn = MagicMock()
    mock_engine = create_autospec(Engine)
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    handler = DatabaseEventHandler(engine=mock_engine)
    now = datetime.now(UTC)
    handler(
        TokenProcessed(
            chain="sol",
            interval="1m",
            scanned_at=now,
            address="0xabc",
            symbol="TEST",
            filter_passed=False,
            filter_reason="liquidity",
            score_total=None,
            score_breakdown=None,
            signal_emitted=False,
            signal_level=None,
            cooldown_skipped=False,
        )
    )

    call_args = mock_conn.execute.call_args[0][1]
    assert call_args["score_total"] is None
    assert call_args["score_breakdown"] is None


def test_file_event_handler_writes_json_line() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fh = FileEventHandler(log_dir=tmpdir)
        now = datetime.now(UTC)
        fh(
            TokenProcessed(
                chain="sol",
                interval="1m",
                scanned_at=now,
                address="0xabc",
                symbol="TEST",
                filter_passed=True,
                filter_reason="",
                score_total=80,
                score_breakdown={"smart_money": 30},
                signal_emitted=True,
                signal_level="HIGH",
                cooldown_skipped=False,
            )
        )
        fh.close()

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        filepath = os.path.join(tmpdir, f"scanner-analysis-{today}.jsonl")
        assert os.path.exists(filepath)
        with open(filepath) as f:
            line = json.loads(f.readline())
        assert line["address"] == "0xabc"
        assert line["score_total"] == 80


def test_file_event_handler_rotates_daily() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fh = FileEventHandler(log_dir=tmpdir)
        now = datetime.now(UTC)
        for _ in range(3):
            fh(
                TokenProcessed(
                    chain="sol",
                    interval="1m",
                    scanned_at=now,
                    address="0xabc",
                    symbol="TEST",
                    filter_passed=True,
                    filter_reason="",
                    score_total=80,
                    score_breakdown=None,
                    signal_emitted=False,
                    signal_level=None,
                    cooldown_skipped=False,
                )
            )
        fh.close()

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        filepath = os.path.join(tmpdir, f"scanner-analysis-{today}.jsonl")
        with open(filepath) as f:
            lines = f.readlines()
        assert len(lines) == 3


def test_metrics_handler_trending() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    handler = MetricsHandler(metrics)

    handler(
        TrendingFetched(
            chain="sol",
            interval="1m",
            token_count=50,
            duration_ms=1000.0,
            success=True,
        )
    )

    tokens = registry.get_sample_value("cm_scanner_trending_tokens_total", {"chain": "sol"})
    assert tokens == 50.0


def test_metrics_handler_chain_duration() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    handler = MetricsHandler(metrics)

    handler(
        ChainScanCompleted(
            chain="sol",
            interval="1m",
            total_duration_ms=5000.0,
            token_count=50,
            signal_count=3,
        )
    )

    count = registry.get_sample_value(
        "cm_scanner_chain_duration_seconds_count",
        {"chain": "sol", "interval": "1m"},
    )
    assert count == 1.0


def test_metrics_handler_ignores_token_processed() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    handler = MetricsHandler(metrics)

    now = datetime.now(UTC)
    handler(
        TokenProcessed(
            chain="sol",
            interval="1m",
            scanned_at=now,
            address="0xabc",
            symbol="TEST",
            filter_passed=True,
            filter_reason="",
            score_total=80,
            score_breakdown=None,
            signal_emitted=True,
            signal_level="HIGH",
            cooldown_skipped=False,
        )
    )

    count = registry.get_sample_value(
        "cm_scanner_chain_duration_seconds_count",
        {"chain": "sol", "interval": "1m"},
    )
    assert count is None
