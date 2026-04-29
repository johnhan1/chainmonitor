# Scanner Observability Implementation Plan v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Restructure scanner observability to separate system metrics (Prometheus) from strategy data (DB + JSONL), replacing 4 per-token events with a single TokenProcessed event.

**Architecture:** TokenProcessed event captures complete pipeline result per token → DatabaseEventHandler inserts to `scanner_token_results`, FileEventHandler appends JSONL, StructuredLogHandler writes to stdout. System events (TrendingFetched, TokenSecurityChecked, ChainScanCompleted) → MetricsHandler → Prometheus only.

**Tech Stack:** Python 3.11, prometheus-client 0.22.1, python-json-logger 3.3.0, PostgreSQL, SQLAlchemy, Alembic

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/scanner/events.py` | 8→5 events, add TokenProcessed, remove 5 old events |
| Modify | `src/scanner/metrics.py` | 8→5 metrics, remove filter_rejections/signals/score |
| Modify | `src/scanner/handlers.py` | Add DatabaseEventHandler + FileEventHandler, rewrite MetricsHandler/StructuredLogHandler |
| Modify | `src/scanner/orchestrator.py` | Emit TokenProcessed per token, keep system events |
| Modify | `src/scanner/__main__.py` | Wire DatabaseEventHandler + FileEventHandler |
| Create | `src/scanner/migration.py` or Alembic revision | Create scanner_token_results table |
| Modify | `tests/test_scanner_events.py` | Test 5 events, add TokenProcessed test |
| Modify | `tests/test_scanner_metrics.py` | Test 5 metrics |
| Modify | `tests/test_scanner_handlers.py` | Add DB + File handler tests, update existing |
| Modify | `tests/test_scanner_orchestrator.py` | Test TokenProcessed emission |

---

### Task 1: Rewrite events.py — 5 events, add TokenProcessed

**Files:**
- Modify: `src/scanner/events.py`
- Modify: `tests/test_scanner_events.py`

- [ ] **Step 1: Read current events.py**

Read `src/scanner/events.py` to see the current 8 events.

- [ ] **Step 2: Rewrite tests**

Replace `tests/test_scanner_events.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime

from src.scanner.events import (
    EVENT_TYPES,
    ChainScanCompleted,
    EventBus,
    TokenProcessed,
    TokenSecurityChecked,
    TrendingFetched,
)


def test_event_bus_publish() -> None:
    bus = EventBus()
    received: list[object] = []

    def handler(event: object) -> None:
        received.append(event)

    bus.subscribe(TrendingFetched, handler)
    event = TrendingFetched(chain="sol", interval="1m", token_count=50, duration_ms=100.0, success=True)
    bus.publish(event)
    assert received == [event]


def test_event_bus_unrelated_type_not_dispatched() -> None:
    bus = EventBus()
    received: list[object] = []

    def handler(event: object) -> None:
        received.append(event)

    bus.subscribe(TokenProcessed, handler)
    bus.publish(TrendingFetched(chain="sol", interval="1m", token_count=50, duration_ms=100.0, success=True))
    assert received == []


def test_event_bus_handler_exception_isolation() -> None:
    bus = EventBus()
    received: list[object] = []

    def failing_handler(event: object) -> None:
        raise ValueError("oops")

    def good_handler(event: object) -> None:
        received.append(event)

    bus.subscribe(TrendingFetched, failing_handler)
    bus.subscribe(TrendingFetched, good_handler)
    bus.publish(TrendingFetched(chain="sol", interval="1m", token_count=50, duration_ms=100.0, success=True))
    assert len(received) == 1


def test_event_types_are_dataclasses() -> None:
    now = datetime.now(UTC)
    TrendingFetched(chain="sol", interval="1m", token_count=50, duration_ms=100.0, success=True)
    TokenSecurityChecked(chain="sol", address="0x1", symbol="A", duration_ms=50.0, success=True)
    TokenProcessed(
        chain="sol", interval="1m", scanned_at=now,
        address="0x1", symbol="A",
        filter_passed=True, filter_reason="",
        score_total=80, score_breakdown={"smart_money": 30},
        signal_emitted=True, signal_level="HIGH",
        cooldown_skipped=False,
    )
    ChainScanCompleted(chain="sol", interval="1m", total_duration_ms=5000.0, token_count=50, signal_count=3)
    assert EVENT_TYPES


def test_token_processed_all_fields_defaults() -> None:
    now = datetime.now(UTC)
    tp = TokenProcessed(
        chain="sol", interval="1m", scanned_at=now,
        address="0x1", symbol="A",
        filter_passed=False, filter_reason="liquidity",
        score_total=None, score_breakdown=None,
        signal_emitted=False, signal_level=None,
        cooldown_skipped=False,
    )
    assert tp.filter_passed is False
    assert tp.score_total is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_events.py -v`
Expected: ImportError / AttributeError for removed event types

- [ ] **Step 4: Rewrite events.py**

Replace the content of `src/scanner/events.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class TrendingFetched:
    chain: str
    interval: str
    token_count: int
    duration_ms: float
    success: bool


@dataclass
class TokenSecurityChecked:
    chain: str
    address: str
    symbol: str
    duration_ms: float
    success: bool


@dataclass
class TokenProcessed:
    chain: str
    interval: str
    scanned_at: datetime
    address: str
    symbol: str
    filter_passed: bool
    filter_reason: str
    score_total: int | None
    score_breakdown: dict[str, int] | None
    signal_emitted: bool
    signal_level: str | None
    cooldown_skipped: bool


@dataclass
class ChainScanCompleted:
    chain: str
    interval: str
    total_duration_ms: float
    token_count: int
    signal_count: int


EventHandler = Callable[[Any], None]

SYSTEM_EVENT_TYPES: list[type] = [
    TrendingFetched,
    TokenSecurityChecked,
    ChainScanCompleted,
]

STRATEGY_EVENT_TYPES: list[type] = [
    TokenProcessed,
]

ALL_EVENT_TYPES: list[type] = SYSTEM_EVENT_TYPES + STRATEGY_EVENT_TYPES


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = {}

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), []):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "EventBus handler failed for %s", type(event).__name__
                )
```

Note: Split EVENT_TYPES into SYSTEM_EVENT_TYPES and STRATEGY_EVENT_TYPES so __main__.py can subscribe handlers to only the events they need.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_events.py -v`
Expected: 5 passed

---

### Task 2: Rewrite metrics.py — remove 3 strategy metrics

**Files:**
- Modify: `src/scanner/metrics.py`
- Modify: `tests/test_scanner_metrics.py`

- [ ] **Step 1: Read current metrics.py**

Read `src/scanner/metrics.py` to see current 8 metrics.

- [ ] **Step 2: Rewrite tests**

Replace `tests/test_scanner_metrics.py`:

```python
from __future__ import annotations

from prometheus_client import CollectorRegistry

from src.scanner.metrics import REGISTRY, ScannerMetrics, start_metrics_server


def test_metrics_created_in_registry() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    metrics.trending_tokens.labels(chain="sol").inc(5)
    val = registry.get_sample_value(
        "cm_scanner_trending_tokens_total", {"chain": "sol"}
    )
    assert val == 5.0


def test_chain_duration_histogram() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    metrics.chain_duration.labels(chain="sol", interval="1m").observe(10.5)
    count = registry.get_sample_value(
        "cm_scanner_chain_duration_seconds_count",
        {"chain": "sol", "interval": "1m"},
    )
    assert count == 1.0


def test_removed_metrics_not_in_registry() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    # These metrics should no longer exist on ScannerMetrics
    assert not hasattr(metrics, "filter_rejections")
    assert not hasattr(metrics, "signals")
    assert not hasattr(metrics, "score")


def test_start_metrics_server_runs() -> None:
    start_metrics_server(0)
    assert REGISTRY is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_metrics.py -v`
Expected: Test failures or attribute errors

- [ ] **Step 4: Rewrite metrics.py**

Replace `src/scanner/metrics.py`:

```python
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server

REGISTRY = CollectorRegistry(auto_describe=True)


class ScannerMetrics:
    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.chain_duration = Histogram(
            "cm_scanner_chain_duration_seconds",
            "Duration per chain scan",
            ["chain", "interval"],
            buckets=(1, 5, 10, 15, 20, 30, 45, 60, 90, 120),
            registry=registry,
        )
        self.trending_duration = Histogram(
            "cm_scanner_trending_duration_seconds",
            "Duration of trending API call",
            ["chain", "interval"],
            buckets=(0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30),
            registry=registry,
        )
        self.trending_tokens = Counter(
            "cm_scanner_trending_tokens_total",
            "Number of tokens fetched from trending",
            ["chain"],
            registry=registry,
        )
        self.security_duration = Histogram(
            "cm_scanner_security_check_duration_seconds",
            "Duration of token security check",
            ["chain"],
            buckets=(0.1, 0.3, 0.5, 1, 2, 3, 5),
            registry=registry,
        )
        self.security_checks = Counter(
            "cm_scanner_security_checks_total",
            "Token security check results",
            ["chain", "status"],
            registry=registry,
        )


def start_metrics_server(port: int = 9101) -> None:
    start_http_server(port, registry=REGISTRY)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_metrics.py -v`
Expected: 4 passed

---

### Task 3: Rewrite handlers.py — add DB + File handlers

**Files:**
- Modify: `src/scanner/handlers.py`
- Modify: `tests/test_scanner_handlers.py`

- [ ] **Step 1: Read current handlers.py**

Read `src/scanner/handlers.py` to understand current structure.

- [ ] **Step 2: Write tests**

Replace `tests/test_scanner_handlers.py`:

```python
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
    TokenSecurityChecked,
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
    handler.setFormatter(
        JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)

    log_handler = StructuredLogHandler(logger_name="test_events_handler")
    now = datetime.now(UTC)
    log_handler(
        TokenProcessed(
            chain="sol", interval="1m", scanned_at=now,
            address="0xabc", symbol="TEST",
            filter_passed=False, filter_reason="liquidity",
            score_total=None, score_breakdown=None,
            signal_emitted=False, signal_level=None,
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
            chain="sol", interval="1m", scanned_at=now,
            address="0xabc", symbol="TEST",
            filter_passed=True, filter_reason="",
            score_total=80, score_breakdown={"smart_money": 30},
            signal_emitted=True, signal_level="HIGH",
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


def test_file_event_handler_writes_json_line() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fh = FileEventHandler(log_dir=tmpdir)
        now = datetime.now(UTC)
        fh(
            TokenProcessed(
                chain="sol", interval="1m", scanned_at=now,
                address="0xabc", symbol="TEST",
                filter_passed=True, filter_reason="",
                score_total=80, score_breakdown={"smart_money": 30},
                signal_emitted=True, signal_level="HIGH",
                cooldown_skipped=False,
            )
        )

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
                    chain="sol", interval="1m", scanned_at=now,
                    address="0xabc", symbol="TEST",
                    filter_passed=True, filter_reason="",
                    score_total=80, score_breakdown=None,
                    signal_emitted=False, signal_level=None,
                    cooldown_skipped=False,
                )
            )

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
        TrendingFetched(chain="sol", interval="1m", token_count=50, duration_ms=1000.0, success=True)
    )

    tokens = registry.get_sample_value(
        "cm_scanner_trending_tokens_total", {"chain": "sol"}
    )
    assert tokens == 50.0


def test_metrics_handler_chain_duration() -> None:
    registry = CollectorRegistry()
    metrics = ScannerMetrics(registry=registry)
    handler = MetricsHandler(metrics)

    handler(
        ChainScanCompleted(chain="sol", interval="1m", total_duration_ms=5000.0, token_count=50, signal_count=3)
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
            chain="sol", interval="1m", scanned_at=now,
            address="0xabc", symbol="TEST",
            filter_passed=True, filter_reason="",
            score_total=80, score_breakdown=None,
            signal_emitted=True, signal_level="HIGH",
            cooldown_skipped=False,
        )
    )

    # No metrics should have been updated
    count = registry.get_sample_value(
        "cm_scanner_chain_duration_seconds_count",
        {"chain": "sol", "interval": "1m"},
    )
    assert count is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_handlers.py -v`
Expected: Various test failures

- [ ] **Step 4: Rewrite handlers.py**

Replace `src/scanner/handlers.py`:

```python
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
        data["scanned_at"] = data.pop("scanned_at")
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
            self._metrics.trending_duration.labels(
                event.chain, event.interval
            ).observe(event.duration_ms / 1000.0)
            self._metrics.trending_tokens.labels(event.chain).inc(
                event.token_count
            )
        elif isinstance(event, TokenSecurityChecked):
            self._metrics.security_duration.labels(event.chain).observe(
                event.duration_ms / 1000.0
            )
            self._metrics.security_checks.labels(
                event.chain, "ok" if event.success else "fail"
            ).inc()
        elif isinstance(event, ChainScanCompleted):
            self._metrics.chain_duration.labels(
                event.chain, event.interval
            ).observe(event.total_duration_ms / 1000.0)
```

Note: Remove unused imports from events (CooldownSkipped, SignalEmitted, TokenFiltered, TokenScored).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_handlers.py -v`
Expected: 9 passed

---

### Task 4: Update orchestrator.py — emit TokenProcessed per token

**Files:**
- Modify: `src/scanner/orchestrator.py`
- Modify: `tests/test_scanner_orchestrator.py`

- [ ] **Step 1: Read current orchestrator.py**

Read `src/scanner/orchestrator.py`.

- [ ] **Step 2: Update imports**

In `src/scanner/orchestrator.py`, change events imports from:

```python
from src.scanner.events import (
    ChainScanCompleted,
    ChainScanStarted,
    CooldownSkipped,
    EventBus,
    SignalEmitted,
    TokenFiltered,
    TokenScored,
    TokenSecurityChecked,
    TrendingFetched,
)
```

To:

```python
from src.scanner.events import (
    ChainScanCompleted,
    EventBus,
    TokenProcessed,
    TokenSecurityChecked,
    TrendingFetched,
)
```

- [ ] **Step 3: Rewrite `_run_chain` token processing loop**

Replace the token processing loop in `_run_chain` (from `signals = self._scorer.detect(prev, curr, risks)` to the end of the method) with:

```python
        signals = self._scorer.detect(prev, curr, risks)
        signal_map: dict[str, AlphaSignal] = {s.token.token.address: s for s in signals}

        prev_map: dict[str, TrendingToken] = {}
        if prev:
            prev_map = {t.address: t for t in prev.tokens}

        for token in curr.tokens:
            risk = risks.get(token.address)
            fr = self._scorer.hard_filter(token, risk)

            score_total: int | None = None
            score_breakdown: dict[str, int] | None = None
            if fr.passed:
                prev_token = prev_map.get(token.address)
                scored = self._scorer.score(token, prev_token, risk)
                score_total = scored.score
                score_breakdown = scored.breakdown

            signal_emitted = False
            signal_level: str | None = None
            cooldown_skipped = False

            sig = signal_map.get(token.address)
            if sig:
                if self._cooldown.is_cooling(token.address):
                    cooldown_skipped = True
                    logger.debug("Cooldown skip %s (%s)", token.symbol, token.address)
                else:
                    signal_emitted = True
                    signal_level = sig.level
                    logger.info(
                        "AlphaSignal level=%s score=%d chain=%s symbol=%s",
                        sig.level, score_total or 0, chain, token.symbol,
                    )
                    await self._notifier.send_alpha(sig)
                    self._cooldown.mark(token.address, sig.level)

            self._event_bus.publish(TokenProcessed(
                chain=chain,
                interval=interval,
                scanned_at=t0,
                address=token.address,
                symbol=token.symbol,
                filter_passed=fr.passed,
                filter_reason=fr.reason,
                score_total=score_total,
                score_breakdown=score_breakdown,
                signal_emitted=signal_emitted,
                signal_level=signal_level,
                cooldown_skipped=cooldown_skipped,
            ))

        self._store.save(chain, interval, curr)

        total_dur = (self._clock() - t0).total_seconds() * 1000
        self._event_bus.publish(
            ChainScanCompleted(
                chain=chain,
                interval=interval,
                total_duration_ms=total_dur,
                token_count=len(tokens),
                signal_count=len(signals),
            )
        )
```

Also update the imports at the top of the file to replace:

```python
from src.scanner.models import AlphaSignal, ScoredToken, Snapshot, TokenRisk
```

(Remove ScoredToken if no longer used elsewhere, keep TokenRisk, Snapshot, AlphaSignal)

- [ ] **Step 4: Update orchestrator tests**

Replace `tests/test_scanner_orchestrator.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.scanner.models import (
    AlphaSignal,
    FilterResult,
    ScoredToken,
    TrendingToken,
)
from src.scanner.orchestrator import ScannerOrchestrator


def _make_token(address: str = "0xa") -> TrendingToken:
    return TrendingToken(
        address=address, symbol="A", name="A",
        price_usd=0.1, rank=1, chain="sol",
    )


def _make_signal(token: TrendingToken, level: str = "HIGH") -> AlphaSignal:
    scored = ScoredToken(token=token, score=80, breakdown={"smart_money": 30})
    return AlphaSignal(
        token=scored, level=level,
        chain=token.chain, interval="1m",
        detected_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_run_cycle_happy_path() -> None:
    token = _make_token()
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_scorer = MagicMock()
    mock_scorer.detect.return_value = []
    mock_scorer.hard_filter.return_value = FilterResult(passed=True)
    mock_scorer.score.return_value = ScoredToken(
        token=token, score=50, breakdown={}
    )

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"], client=mock_client, store=mock_store,
        scorer=mock_scorer, notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_client.fetch_trending.assert_called_once_with(
        chain="sol", interval="1m", limit=50
    )
    mock_store.save.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_with_alpha_signal() -> None:
    token = _make_token()
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_scorer = MagicMock()
    mock_scorer.detect.return_value = [_make_signal(token)]
    mock_scorer.hard_filter.return_value = FilterResult(passed=True)
    mock_scorer.score.return_value = ScoredToken(
        token=token, score=80, breakdown={"smart_money": 30}
    )

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"], client=mock_client, store=mock_store,
        scorer=mock_scorer, notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_notifier.send_alpha.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_fetch_failure_skips_chain() -> None:
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = []

    mock_store = MagicMock()
    mock_scorer = MagicMock()
    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol", "bsc"], client=mock_client, store=mock_store,
        scorer=mock_scorer, notifier=mock_notifier,
    )
    await orch.run_cycle()

    assert mock_client.fetch_trending.call_count == 2


@pytest.mark.asyncio
async def test_run_cycle_emits_token_processed() -> None:
    token = _make_token()
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_scorer = MagicMock()
    mock_scorer.detect.return_value = [_make_signal(token)]
    mock_scorer.hard_filter.return_value = FilterResult(passed=True)
    mock_scorer.score.return_value = ScoredToken(
        token=token, score=80, breakdown={"smart_money": 30}
    )

    mock_notifier = AsyncMock()

    from src.scanner.events import (
        ChainScanCompleted, EventBus, TokenProcessed, TrendingFetched,
    )

    received: list[object] = []
    bus = EventBus()
    bus.subscribe(TokenProcessed, received.append)
    bus.subscribe(TrendingFetched, received.append)
    bus.subscribe(ChainScanCompleted, received.append)

    orch = ScannerOrchestrator(
        chains=["sol"], client=mock_client, store=mock_store,
        scorer=mock_scorer, notifier=mock_notifier, event_bus=bus,
    )
    await orch.run_cycle()

    event_types = [type(e).__name__ for e in received]
    assert "TokenProcessed" in event_types
    assert "TrendingFetched" in event_types
    assert "ChainScanCompleted" in event_types
    # Verify TokenProcessed has correct data
    tp = next(e for e in received if isinstance(e, TokenProcessed))
    assert tp.address == "0xa"
    assert tp.filter_passed is True
    assert tp.signal_emitted is True
```

- [ ] **Step 5: Run all scanner tests**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_orchestrator.py tests\test_scanner_events.py tests\test_scanner_handlers.py tests\test_scanner_metrics.py tests\test_scanner_cooldown.py -v`
Expected: All tests pass

---

### Task 5: Update __main__.py — wire DB + File handlers

**Files:**
- Modify: `src/scanner/__main__.py`

- [ ] **Step 1: Read current __main__.py**

Read `src/scanner/__main__.py`.

- [ ] **Step 2: Update the observable setup section**

Replace the observability wiring section in `main()` (from `# Observability` to where handlers are subscribed):

```python
    # Observability
    from src.scanner.events import EventBus, SYSTEM_EVENT_TYPES, STRATEGY_EVENT_TYPES
    from src.scanner.handlers import (
        DatabaseEventHandler,
        FileEventHandler,
        MetricsHandler,
        StructuredLogHandler,
    )
    from src.scanner.metrics import ScannerMetrics, start_metrics_server

    event_bus = EventBus()
    metrics = ScannerMetrics()
    metrics_handler = MetricsHandler(metrics)

    for et in SYSTEM_EVENT_TYPES:
        event_bus.subscribe(et, metrics_handler)

    log_handler = StructuredLogHandler()
    db_handler = DatabaseEventHandler(engine=get_engine())
    file_handler = FileEventHandler()

    for et in STRATEGY_EVENT_TYPES:
        event_bus.subscribe(et, log_handler)
        event_bus.subscribe(et, db_handler)
        event_bus.subscribe(et, file_handler)

    start_metrics_server(settings.scanner_metrics_port)
    logger.info(
        "Scanner metrics server started on port %d", settings.scanner_metrics_port
    )
```

- [ ] **Step 3: Verify imports**

Run: `.\.venv\Scripts\python -c "from src.scanner.__main__ import main"`
Expected: No import errors

---

### Task 6: Alembic migration — scanner_token_results table

**Files:**
- Create: `src/alembic/versions/xxxx_scanner_token_results.py`

Instead of using Alembic directly, create the migration by running the project's db-revision script.

- [ ] **Step 1: Create migration**

Run: `.\scripts\db-revision.ps1 -Message "create scanner_token_results table"`

If db-revision.ps1 is not available, create the migration file manually:

Create a new file in `src/alembic/versions/` with this content:

```python
"""create scanner_token_results table

Revision ID: xxxx
Revises: [previous revision]
Create Date: 2026-04-28
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "xxxx"
down_revision: str | None = "[previous revision]"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "scanner_token_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("filter_passed", sa.Boolean(), nullable=False),
        sa.Column("filter_reason", sa.String(100), nullable=True),
        sa.Column("score_total", sa.Integer(), nullable=True),
        sa.Column("score_breakdown", JSONB(), nullable=True),
        sa.Column("signal_emitted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("signal_level", sa.String(10), nullable=True),
        sa.Column("cooldown_skipped", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_scan_chain_time", "scanner_token_results", ["chain", "scanned_at"])
    op.create_index("idx_scan_filter", "scanner_token_results", ["filter_passed", "filter_reason"])
    op.create_index("idx_scan_score", "scanner_token_results", ["score_total"])
    op.create_index("idx_scan_signal", "scanner_token_results", ["signal_emitted", "signal_level"])


def downgrade() -> None:
    op.drop_table("scanner_token_results")
```

- [ ] **Step 2: Verify migration**

Run: `.\.venv\Scripts\alembic upgrade head`
Expected: Migration applies successfully

---

### Task 7: Final verification

- [ ] **Step 1: Run ruff check**

Run: `.\.venv\Scripts\ruff check src\scanner\ tests\test_scanner_*.py`
Expected: No errors

- [ ] **Step 2: Run all scanner tests**

Run: `.\.venv\Scripts\python -m pytest tests\test_scanner_cooldown.py tests\test_scanner_events.py tests\test_scanner_metrics.py tests\test_scanner_handlers.py tests\test_scanner_orchestrator.py tests\test_scanner_detector.py tests\test_scanner_notifier.py tests\test_scanner_models.py tests\test_scanner_snapshot_store.py tests\test_scanner_gmgn_client.py -v`
Expected: All tests pass
