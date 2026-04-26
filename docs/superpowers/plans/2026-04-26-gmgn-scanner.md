# GMGN 热门榜异动扫描工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) for syntax tracking.

**Goal:** Build a scanner module that polls GMGN trending榜单 across 4 chains (sol/bsc/base/eth), detects anomalies (NEW/SURGE/SPIKE), and sends Telegram alerts.

**Architecture:** New `src/scanner/` package with 6 internal modules (models, gmgn_client, snapshot_store, detector, notifier, orchestrator) that share existing config/DB/logging infrastructure. Runs as independent async loop, lifecycle managed via dev.ps1.

**Tech Stack:** Python 3.11+ asyncio, subprocess (gmgn-cli), SQLAlchemy raw JSONB, httpx (TG API), Prometheus metrics via existing infra.

**Spec:** `docs/superpowers/specs/2026-04-26-gmgn-scanner-design.md`

---

### Task 1: Add config + DB migration

**Files:**
- Modify: `src/shared/config.py` (append to Settings class)
- Create: `alembic/versions/scanner_snapshots.py`
- Modify: `.env.example`

- [ ] **Step 1: Append scanner/GMGN/TG config to Settings**

Add at the end of the `Settings` class in `src/shared/config.py`, before the `model_config` line:

```python
    # GMGN
    cm_gmgn_api_key: str = ""
    cm_gmgn_cli_path: str = "gmgn-cli"
    # Telegram
    cm_telegram_bot_token: str = ""
    cm_telegram_chat_id: str = ""
    # Scanner
    cm_scanner_enabled: bool = False
    cm_scanner_chains: list[str] = ["sol", "bsc", "base", "eth"]
    cm_scanner_surge_threshold: int = 10
    cm_scanner_spike_ratio: float = 2.0
    cm_scanner_interval_1m_seconds: int = 60
    cm_scanner_interval_1h_seconds: int = 300
    cm_scanner_trending_limit: int = 50
```

These will be auto-discovered by pydantic-settings via the `CM_` prefix.

- [ ] **Step 2: Run migration check**

```bash
.\scripts\dev.ps1 -Command check
```
Expected: lint + test pass

- [ ] **Step 3: Create Alembic migration**

```bash
.\scripts\db-revision.ps1 -Message "add_scanner_snapshots"
```

Then edit the generated file to add:

```python
def upgrade() -> None:
    op.create_table(
        "scanner_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain", sa.String(length=10), nullable=False),
        sa.Column("interval", sa.String(length=5), nullable=False),
        sa.Column("snapshot_data", sa.JSONB(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_scanner_snapshots_chain_interval", "scanner_snapshots", ["chain", "interval"])

def downgrade() -> None:
    op.drop_constraint("uq_scanner_snapshots_chain_interval", "scanner_snapshots")
    op.drop_table("scanner_snapshots")
```

- [ ] **Step 4: Update `.env.example`**

Append to `D:\Code\chainmonitor\.env.example`:

```ini
CM_GMGN_API_KEY=
CM_GMGN_CLI_PATH=gmgn-cli
CM_TELEGRAM_BOT_TOKEN=
CM_TELEGRAM_CHAT_ID=
CM_SCANNER_ENABLED=false
CM_SCANNER_CHAINS=sol,bsc,base,eth
CM_SCANNER_SURGE_THRESHOLD=10
CM_SCANNER_SPIKE_RATIO=2.0
CM_SCANNER_INTERVAL_1M_SECONDS=60
CM_SCANNER_INTERVAL_1H_SECONDS=300
CM_SCANNER_TRENDING_LIMIT=50
```

- [ ] **Step 5: Verify lint**

```bash
.\scripts\dev.ps1 -Command check
```
Expected: lint + test pass

- [ ] **Step 6: Commit**

```bash
git add src/shared/config.py .env.example alembic/versions/
git commit -m "feat: add scanner config, .env vars, and DB migration"
```

---

### Task 2: Create scanner models

**Files:**
- Create: `src/scanner/__init__.py`
- Create: `src/scanner/models.py`
- Create: `tests/test_scanner_models.py`

- [ ] **Step 1: Create package init**

`src/scanner/__init__.py`:
```python
from __future__ import annotations
```

- [ ] **Step 2: Write model tests**

`tests/test_scanner_models.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

from src.scanner.models import AnomalyEvent, AnomalyType, Snapshot, TrendingToken


def test_trending_token_defaults() -> None:
    t = TrendingToken(
        address="0xabc",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        rank=1,
        chain="sol",
    )
    assert t.volume_1m is None
    assert t.smart_degen_count is None
    assert t.market_cap is None


def test_snapshot_roundtrip() -> None:
    t = TrendingToken(
        address="0xabc",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        volume_1m=1000.0,
        rank=1,
        chain="sol",
    )
    snap = Snapshot(
        chain="sol",
        interval="1m",
        tokens=[t],
        taken_at=datetime.now(timezone.utc),
    )
    assert snap.tokens[0].symbol == "TEST"
    assert snap.tokens[0].volume_1m == 1000.0


def test_anomaly_event_defaults() -> None:
    t = TrendingToken(
        address="0xabc",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        rank=1,
        chain="sol",
    )
    e = AnomalyEvent(
        type=AnomalyType.NEW,
        token=t,
        chain="sol",
        previous_rank=None,
        rank_change=None,
        reason="New token appeared",
    )
    assert e.type == AnomalyType.NEW
    assert e.reason == "New token appeared"
```

- [ ] **Step 3: Create models module**

`src/scanner/models.py`:
```python
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class TrendingToken(BaseModel):
    address: str
    symbol: str
    name: str
    price_usd: float
    volume_1m: float | None = None
    volume_1h: float | None = None
    market_cap: float | None = None
    liquidity: float | None = None
    smart_degen_count: int | None = None
    rank: int
    chain: str


class Snapshot(BaseModel):
    chain: str
    interval: str
    tokens: list[TrendingToken]
    taken_at: datetime


class AnomalyType(str, Enum):
    NEW = "new"
    SURGE = "surge"
    SPIKE = "spike"


class AnomalyEvent(BaseModel):
    type: AnomalyType
    token: TrendingToken
    chain: str
    previous_rank: int | None = None
    rank_change: int | None = None
    reason: str
```

- [ ] **Step 4: Run tests**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_models.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/scanner/ tests/test_scanner_models.py
git commit -m "feat: add scanner models (TrendingToken, Snapshot, AnomalyEvent)"
```

---

### Task 3: GMGN CLI wrapper

**Files:**
- Create: `src/scanner/gmgn_client.py`
- Create: `tests/test_scanner_gmgn_client.py`

- [ ] **Step 1: Write failing test**

`tests/test_scanner_gmgn_client.py`:
```python
from __future__ import annotations

import json
import pytest
from src.scanner.gmgn_client import GmgnClient


@pytest.mark.asyncio
async def test_fetch_trending_parses_json() -> None:
    fake_output = json.dumps({
        "data": [
            {
                "address": "0xabc",
                "symbol": "TEST",
                "name": "Test Token",
                "price_usd": "0.123",
                "volume_1m": "45000",
                "volume_1h": "500000",
                "market_cap": "1000000",
                "liquidity": "500000",
                "smart_degen_count": 12,
                "rank": 1,
            }
        ]
    })
    client = GmgnClient(gmgn_cli_path="echo")
    tokens = await client.fetch_trending(chain="sol", interval="1m", limit=50)
    assert len(tokens) == 1
    t = tokens[0]
    assert t.symbol == "TEST"
    assert t.price_usd == 0.123
    assert t.volume_1m == 45000.0
    assert t.rank == 1
    assert t.chain == "sol"


@pytest.mark.asyncio
async def test_fetch_trending_empty_data() -> None:
    fake_output = json.dumps({"data": []})
    client = GmgnClient(gmgn_cli_path="echo")
    tokens = await client.fetch_trending(chain="sol", interval="1m", limit=50)
    assert tokens == []


@pytest.mark.asyncio
async def test_fetch_trending_timeout_returns_empty() -> None:
    client = GmgnClient(gmgn_cli_path="python", cmd_timeout_seconds=0.001)
    tokens = await client.fetch_trending(chain="sol", interval="1m", limit=50)
    assert tokens == []
```

- [ ] **Step 2: Run to verify failure**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_gmgn_client.py -v
```
Expected: FAIL with import errors (GmgnClient not defined yet)

- [ ] **Step 3: Write implementation**

`src/scanner/gmgn_client.py`:
```python
from __future__ import annotations

import asyncio
import json
import logging

from src.scanner.models import TrendingToken

logger = logging.getLogger(__name__)


class GmgnClient:
    def __init__(
        self,
        gmgn_cli_path: str = "gmgn-cli",
        api_key: str = "",
        cmd_timeout_seconds: float = 30.0,
    ) -> None:
        self._cli_path = gmgn_cli_path
        self._api_key = api_key
        self._timeout = cmd_timeout_seconds

    async def fetch_trending(
        self,
        chain: str,
        interval: str,
        limit: int = 50,
    ) -> list[TrendingToken]:
        cmd = [
            self._cli_path,
            "market",
            "trending",
            "--chain", chain,
            "--interval", interval,
            "--limit", str(limit),
            "--raw",
        ]
        env = {}
        if self._api_key:
            env["GMGN_API_KEY"] = self._api_key

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env or None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
            if proc.returncode != 0:
                logger.error("gmgn-cli failed (exit=%d): %s", proc.returncode, stderr.decode())
                return []
        except (asyncio.TimeoutError, OSError) as e:
            logger.error("gmgn-cli error: %s", e)
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error("gmgn-cli JSON parse error: %s", e)
            return []

        raw_tokens = data.get("data", []) if isinstance(data, dict) else []
        return [
            TrendingToken(
                address=t.get("address", ""),
                symbol=t.get("symbol", ""),
                name=t.get("name", ""),
                price_usd=float(t.get("price_usd", 0) or 0),
                volume_1m=_safe_float(t, "volume_1m"),
                volume_1h=_safe_float(t, "volume_1h"),
                market_cap=_safe_float(t, "market_cap"),
                liquidity=_safe_float(t, "liquidity"),
                smart_degen_count=t.get("smart_degen_count"),
                rank=int(t.get("rank", 0)),
                chain=chain,
            )
            for t in raw_tokens
        ]


def _safe_float(d: dict, key: str) -> float | None:
    val = d.get(key)
    if val is None:
        return None
    return float(val)
```

- [ ] **Step 4: Run tests to pass**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_gmgn_client.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/scanner/gmgn_client.py tests/test_scanner_gmgn_client.py
git commit -m "feat: add GmgnClient subprocess wrapper for gmgn-cli"
```

---

### Task 4: Snapshot store (DB persistence)

**Files:**
- Create: `src/scanner/snapshot_store.py`
- Create: `tests/test_scanner_snapshot_store.py`

- [ ] **Step 1: Write failing test**

`tests/test_scanner_snapshot_store.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from src.scanner.models import Snapshot, TrendingToken
from src.scanner.snapshot_store import SnapshotStore


def test_save_and_load() -> None:
    mock_engine = MagicMock()
    store = SnapshotStore(mock_engine)

    t = TrendingToken(
        address="0xabc",
        symbol="TEST",
        name="Test",
        price_usd=0.1,
        rank=1,
        chain="sol",
    )
    snap = Snapshot(
        chain="sol",
        interval="1m",
        tokens=[t],
        taken_at=datetime.now(timezone.utc),
    )

    store.save("sol", "1m", snap)
    assert mock_engine.begin.called


def test_load_none_when_empty() -> None:
    mock_engine = MagicMock()
    # simulate no rows returned
    mock_conn = mock_engine.begin.return_value.__enter__.return_value
    mock_conn.execute.return_value.fetchone.return_value = None

    store = SnapshotStore(mock_engine)
    result = store.load("sol", "1m")
    assert result is None
```

- [ ] **Step 2: Verify test fails**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_snapshot_store.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

`src/scanner/snapshot_store.py`:
```python
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.scanner.models import Snapshot, TrendingToken

logger = logging.getLogger(__name__)


class SnapshotStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._table = "scanner_snapshots"

    def save(self, chain: str, interval: str, snapshot: Snapshot) -> None:
        raw = [t.model_dump() for t in snapshot.tokens]
        for t in raw:
            t.pop("chain", None)
        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {self._table} (chain, interval, snapshot_data, taken_at)
                    VALUES (:chain, :interval, :data::jsonb, :taken_at)
                    ON CONFLICT (chain, interval)
                    DO UPDATE SET snapshot_data = EXCLUDED.snapshot_data,
                                  taken_at = EXCLUDED.taken_at
                """),
                {
                    "chain": chain,
                    "interval": interval,
                    "data": json.dumps(raw),
                    "taken_at": snapshot.taken_at,
                },
            )

    def load(self, chain: str, interval: str) -> Snapshot | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT snapshot_data, taken_at
                    FROM {self._table}
                    WHERE chain = :chain AND interval = :interval
                """),
                {"chain": chain, "interval": interval},
            ).fetchone()
        if row is None:
            return None
        raw_data: list[dict[str, Any]] = row[0]
        taken_at: datetime = row[1]
        tokens = [TrendingToken(**{**t, "chain": chain}) for t in raw_data]
        return Snapshot(chain=chain, interval=interval, tokens=tokens, taken_at=taken_at)

    def clear(self, chain: str, interval: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {self._table} WHERE chain = :chain AND interval = :interval"),
                {"chain": chain, "interval": interval},
            )
```

- [ ] **Step 4: Run tests to pass**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_snapshot_store.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/scanner/snapshot_store.py tests/test_scanner_snapshot_store.py
git commit -m "feat: add SnapshotStore with DB-backed JSONB persistence"
```

---

### Task 5: Anomaly detector

**Files:**
- Create: `src/scanner/detector.py`
- Create: `tests/test_scanner_detector.py`

- [ ] **Step 1: Write failing tests**

`tests/test_scanner_detector.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

from src.scanner.detector import Detector
from src.scanner.models import AnomalyType, Snapshot, TrendingToken


def _token(address: str, symbol: str, rank: int, volume_1m: float | None = None,
           smart_degen: int | None = None) -> TrendingToken:
    return TrendingToken(
        address=address, symbol=symbol, name=symbol,
        price_usd=0.1, rank=rank, chain="sol",
        volume_1m=volume_1m, smart_degen_count=smart_degen,
    )


def _snapshot(tokens: list[TrendingToken]) -> Snapshot:
    return Snapshot(chain="sol", interval="1m", tokens=tokens,
                    taken_at=datetime.now(timezone.utc))


def test_detect_new_token() -> None:
    prev = _snapshot([_token("0xold", "OLD", 1)])
    curr = _snapshot([_token("0xold", "OLD", 1), _token("0xnew", "NEW", 2)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    assert len(events) == 1
    assert events[0].type == AnomalyType.NEW
    assert events[0].token.address == "0xnew"


def test_detect_surge() -> None:
    prev = _snapshot([_token("0xa", "A", 15), _token("0xb", "B", 1)])
    curr = _snapshot([_token("0xa", "A", 1), _token("0xb", "B", 15)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    # A rose from #15 to #1 = +14, >= 10 => SURGE
    # B dropped, no event
    assert len(events) == 1
    assert events[0].type == AnomalyType.SURGE
    assert events[0].token.address == "0xa"
    assert events[0].rank_change == 14


def test_detect_spike_volume() -> None:
    prev = _snapshot([_token("0xa", "A", 1, volume_1m=1000.0)])
    curr = _snapshot([_token("0xa", "A", 1, volume_1m=5000.0)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    assert len(events) == 1
    assert events[0].type == AnomalyType.SPIKE
    assert "volume" in events[0].reason.lower()


def test_detect_no_change() -> None:
    prev = _snapshot([_token("0xa", "A", 1)])
    curr = _snapshot([_token("0xa", "A", 1)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(prev, curr)
    assert events == []


def test_detect_first_snapshot_no_events() -> None:
    curr = _snapshot([_token("0xa", "A", 1)])
    detector = Detector(surge_threshold=10, spike_ratio=2.0)
    events = detector.detect(None, curr)
    assert events == []
```

- [ ] **Step 2: Verify test fails**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_detector.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

`src/scanner/detector.py`:
```python
from __future__ import annotations

from src.scanner.models import AnomalyEvent, AnomalyType, Snapshot, TrendingToken


class Detector:
    def __init__(self, surge_threshold: int = 10, spike_ratio: float = 2.0) -> None:
        self._surge_threshold = surge_threshold
        self._spike_ratio = spike_ratio

    def detect(self, prev: Snapshot | None, curr: Snapshot) -> list[AnomalyEvent]:
        if prev is None:
            return []

        prev_map: dict[str, TrendingToken] = {t.address: t for t in prev.tokens}
        events: list[AnomalyEvent] = []

        for token in curr.tokens:
            prev_token = prev_map.get(token.address)

            if prev_token is None:
                events.append(AnomalyEvent(
                    type=AnomalyType.NEW,
                    token=token,
                    chain=curr.chain,
                    reason=f"New token on {curr.interval} trending",
                ))
                continue

            rank_change = prev_token.rank - token.rank
            if rank_change >= self._surge_threshold:
                events.append(AnomalyEvent(
                    type=AnomalyType.SURGE,
                    token=token,
                    chain=curr.chain,
                    previous_rank=prev_token.rank,
                    rank_change=rank_change,
                    reason=f"Rank surged #{prev_token.rank} → #{token.rank} (+{rank_change})",
                ))

            reasons = []
            if (prev_token.volume_1m and token.volume_1m
                    and prev_token.volume_1m > 0
                    and token.volume_1m / prev_token.volume_1m >= self._spike_ratio):
                ratio = token.volume_1m / prev_token.volume_1m
                reasons.append(f"volume {ratio:.1f}x")
            if (prev_token.smart_degen_count is not None
                    and token.smart_degen_count is not None
                    and prev_token.smart_degen_count > 0
                    and token.smart_degen_count / prev_token.smart_degen_count >= self._spike_ratio):
                ratio = token.smart_degen_count / prev_token.smart_degen_count
                reasons.append(f"smart_degen {ratio:.1f}x")

            if reasons:
                events.append(AnomalyEvent(
                    type=AnomalyType.SPIKE,
                    token=token,
                    chain=curr.chain,
                    reason=", ".join(reasons),
                ))

        return events
```

- [ ] **Step 4: Run tests to pass**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_detector.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/scanner/detector.py tests/test_scanner_detector.py
git commit -m "feat: add Detector with NEW/SURGE/SPIKE anomaly detection"
```

---

### Task 6: Telegram notifier

**Files:**
- Create: `src/scanner/notifier.py`
- Create: `tests/test_scanner_notifier.py`

- [ ] **Step 1: Write failing test**

`tests/test_scanner_notifier.py`:
```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.scanner.models import AnomalyEvent, AnomalyType, TrendingToken
from src.scanner.notifier import TelegramNotifier


@pytest.mark.asyncio
async def test_send_anomalies_success() -> None:
    token = TrendingToken(
        address="0xabc123",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        volume_1m=45000.0,
        smart_degen_count=12,
        market_cap=1_000_000.0,
        rank=1,
        chain="sol",
    )
    event = AnomalyEvent(
        type=AnomalyType.NEW,
        token=token,
        chain="sol",
        reason="New token on 1m trending",
    )

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        notifier = TelegramNotifier(bot_token="fake:token", chat_id="123")
        await notifier.send_anomalies("sol", "1m", [event])

    assert mock_client.post.called
    call_kwargs = mock_client.post.call_args[1]
    assert "chat_id" in call_kwargs["json"]


@pytest.mark.asyncio
async def test_send_anomalies_empty_does_nothing() -> None:
    notifier = TelegramNotifier(bot_token="fake", chat_id="123")
    await notifier.send_anomalies("sol", "1m", [])
    # Should not raise
```

- [ ] **Step 2: Verify fails**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_notifier.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

`src/scanner/notifier.py`:
```python
from __future__ import annotations

import logging

import httpx

from src.scanner.models import AnomalyEvent, AnomalyType

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, api_base: str = "https://api.telegram.org") -> None:
        self._base_url = f"{api_base}/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    async def send_anomalies(self, chain: str, interval: str, events: list[AnomalyEvent]) -> None:
        if not events:
            return
        text = self._format_message(chain, interval, events)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    self._base_url,
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "MarkdownV2"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("TG send failed: %s", e)

    def _format_message(self, chain: str, interval: str, events: list[AnomalyEvent]) -> str:
        lines: list[str] = [
            f"🔥 *{chain.upper()} {interval} 异动*",
            "",
        ]
        for e in events:
            t = e.token
            sym = _escape(t.symbol)
            addr = _escape(f"{t.address[:6]}…{t.address[-4:]}")
            price = _escape(f"${t.price_usd:.4f}" if t.price_usd < 1 else f"${t.price_usd:.2f}")
            vol = _escape(_fmt_usd(t.volume_1m)) if t.volume_1m else "N/A"
            mc = _escape(_fmt_usd(t.market_cap)) if t.market_cap else "N/A"
            smart = str(t.smart_degen_count) if t.smart_degen_count is not None else "N/A"

            if e.type == AnomalyType.NEW:
                lines.append(f"🆕 *NEW* \\-\\- `{sym}`")
                lines.append(f"  地址: `{addr}`")
                lines.append(f"  价格: {price}")
                lines.append(f"  成交额({interval}): {vol}")
                lines.append(f"  聪明钱: {smart}")
                lines.append(f"  市值: {mc}")
            el            if e.type == AnomalyType.SURGE:
                old = str(e.previous_rank) if e.previous_rank is not None else "?"
                chg = str(e.rank_change) if e.rank_change is not None else "?"
                lines.append(f"⬆️ *SURGE* \\-\\- `{sym}` \\(#{old} → #{t.rank}, +{chg}\\)")
                lines.append(f"  成交额({interval}): {vol}")
            elif e.type == AnomalyType.SPIKE:
                lines.append(f"🔥 *SPIKE* \\-\\- `{sym}` \\({e.reason}\\)")
                lines.append(f"  成交额({interval}): {vol}")
            lines.append("")

        return "\n".join(lines).strip()


def _escape(text: str) -> str:
    chars = "_*[]()~`>#+-=|{}.!"
    for c in chars:
        text = text.replace(c, f"\\{c}")
    return text


def _fmt_usd(val: float | None) -> str:
    if val is None:
        return "N/A"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.2f}"
```

- [ ] **Step 4: Run tests to pass**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_notifier.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/scanner/notifier.py tests/test_scanner_notifier.py
git commit -m "feat: add TelegramNotifier with MarkdownV2 message formatting"
```

---

### Task 7: Orchestrator (main loop)

**Files:**
- Create: `src/scanner/orchestrator.py`
- Create: `tests/test_scanner_orchestrator.py`

- [ ] **Step 1: Write failing test**

`tests/test_scanner_orchestrator.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.scanner.models import AnomalyEvent, AnomalyType, Snapshot, TrendingToken
from src.scanner.orchestrator import ScannerOrchestrator


@pytest.mark.asyncio
async def test_run_cycle_happy_path() -> None:
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [
        TrendingToken(address="0xa", symbol="A", name="A", price_usd=0.1, rank=1, chain="sol"),
    ]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_detector = MagicMock()
    mock_detector.detect.return_value = []

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"],
        client=mock_client,
        store=mock_store,
        detector=mock_detector,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_client.fetch_trending.assert_called_once_with(chain="sol", interval="1m", limit=50)
    mock_store.save.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_with_anomaly() -> None:
    token = TrendingToken(address="0xa", symbol="A", name="A", price_usd=0.1, rank=1, chain="sol")
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_detector = MagicMock()
    mock_detector.detect.return_value = [
        AnomalyEvent(type=AnomalyType.NEW, token=token, chain="sol", reason="new"),
    ]

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"],
        client=mock_client,
        store=mock_store,
        detector=mock_detector,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_notifier.send_anomalies.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_fetch_failure_skips_chain() -> None:
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = []

    mock_store = MagicMock()
    mock_detector = MagicMock()
    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol", "bsc"],
        client=mock_client,
        store=mock_store,
        detector=mock_detector,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    assert mock_client.fetch_trending.call_count == 2
    # should not crash
```

- [ ] **Step 2: Verify fails**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_orchestrator.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

`src/scanner/orchestrator.py`:
```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from src.scanner.detector import Detector
from src.scanner.gmgn_client import GmgnClient
from src.scanner.models import Snapshot
from src.scanner.notifier import TelegramNotifier
from src.scanner.snapshot_store import SnapshotStore

logger = logging.getLogger(__name__)


class ScannerOrchestrator:
    def __init__(
        self,
        chains: list[str],
        client: GmgnClient | None = None,
        store: SnapshotStore | None = None,
        detector: Detector | None = None,
        notifier: TelegramNotifier | None = None,
        surge_threshold: int = 10,
        spike_ratio: float = 2.0,
        trending_limit: int = 50,
        interval_1h_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._chains = chains
        self._client = client
        self._store = store
        self._detector = detector
        self._notifier = notifier
        self._trending_limit = trending_limit
        self._interval_1h_seconds = interval_1h_seconds
        self._last_1h_run: float = 0.0
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def run_cycle(self) -> None:
        for chain in self._chains:
            try:
                await self._run_chain(chain, "1m")
            except Exception:
                logger.exception("Scanner 1m cycle failed for chain=%s", chain)

        now = self._clock().timestamp()
        if now - self._last_1h_run >= self._interval_1h_seconds:
            self._last_1h_run = now
            for chain in self._chains:
                try:
                    await self._run_chain(chain, "1h")
                except Exception:
                    logger.exception("Scanner 1h cycle failed for chain=%s", chain)

    async def _run_chain(self, chain: str, interval: str) -> None:
        logger.info("Scanner polling chain=%s interval=%s", chain, interval)
        tokens = await self._client.fetch_trending(chain=chain, interval=interval, limit=self._trending_limit)
        if not tokens:
            logger.warning("Scanner empty result chain=%s interval=%s", chain, interval)
            return

        curr = Snapshot(chain=chain, interval=interval, tokens=tokens, taken_at=self._clock())
        prev = self._store.load(chain, interval)

        events = self._detector.detect(prev, curr)
        if events:
            logger.info("Scanner anomalies chain=%s interval=%s count=%d", chain, interval, len(events))
            await self._notifier.send_anomalies(chain, interval, events)

        self._store.save(chain, interval, curr)

    async def run_forever(self, interval_seconds: int = 60) -> None:
        logger.info("Scanner starting, interval=%ds chains=%s", interval_seconds, self._chains)
        while True:
            await self.run_cycle()
            await asyncio.sleep(interval_seconds)
```

- [ ] **Step 4: Run tests to pass**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_orchestrator.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/scanner/orchestrator.py tests/test_scanner_orchestrator.py
git commit -m "feat: add ScannerOrchestrator with async main loop"
```

---

### Task 8: Scanner entrypoint + dev.ps1 integration

**Files:**
- Create: `scripts/run-scanner.ps1`
- Create: `src/scanner/__main__.py`
- Modify: `scripts/dev.ps1`

- [ ] **Step 1: Create scanner __main__ entrypoint**

`src/scanner/__main__.py`:
```python
from __future__ import annotations

import asyncio
import logging
import signal

from src.scanner.detector import Detector
from src.scanner.gmgn_client import GmgnClient
from src.scanner.notifier import TelegramNotifier
from src.scanner.orchestrator import ScannerOrchestrator
from src.scanner.snapshot_store import SnapshotStore
from src.shared.config import get_settings
from src.shared.db.session import get_engine
from src.shared.logging import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.app_log_level)
    logger = logging.getLogger(__name__)

    if not settings.cm_scanner_enabled:
        logger.info("Scanner disabled (CM_SCANNER_ENABLED=false)")
        return

    bot_token = settings.cm_telegram_bot_token
    chat_id = settings.cm_telegram_chat_id
    if not bot_token or not chat_id:
        logger.warning("Scanner enabled but TELEGRAM_BOT_TOKEN or CHAT_ID missing")
        return

    client = GmgnClient(
        gmgn_cli_path=settings.cm_gmgn_cli_path,
        api_key=settings.cm_gmgn_api_key,
    )
    store = SnapshotStore(get_engine())
    detector = Detector(
        surge_threshold=settings.cm_scanner_surge_threshold,
        spike_ratio=settings.cm_scanner_spike_ratio,
    )
    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
    orch = ScannerOrchestrator(
        chains=settings.cm_scanner_chains,
        client=client,
        store=store,
        detector=detector,
        notifier=notifier,
        trending_limit=settings.cm_scanner_trending_limit,
        interval_1h_seconds=settings.cm_scanner_interval_1h_seconds,
    )

    logger.info(
        "Scanner started chains=%s interval_1m=%ds chains=%s",
        settings.cm_scanner_chains,
        settings.cm_scanner_interval_1m_seconds,
        settings.cm_scanner_chains,
    )

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    def _shutdown() -> None:
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    task = asyncio.create_task(orch.run_forever(interval_seconds=settings.cm_scanner_interval_1m_seconds))
    await stop
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Scanner stopped")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Create PowerShell wrapper**

`scripts/run-scanner.ps1`:
```powershell
$ErrorActionPreference = "Stop"
.\.venv\Scripts\python -m src.scanner
if ($LASTEXITCODE -ne 0) {
    throw "Scanner exited with code $LASTEXITCODE"
}
```

- [ ] **Step 3: Add `scanner` command to dev.ps1**

Edit `scripts/dev.ps1` to add "scanner" to the ValidateSet:

```powershell
[ValidateSet("init", "up", "up-lite", "down", "reset", "migrate", "check", "smoke", "scanner", "bsc-run-once", "backup", "restore", "status", "phase2-full-check", "all")]
```

Add the case:

```powershell
  "scanner" {
    Invoke-Checked ".\scripts\run-scanner.ps1"
  }
```

- [ ] **Step 4: Run lint check**

```bash
.\.venv\Scripts\python -m pytest tests/test_scanner_*.py -v
```
Expected: All ~13 scanner tests pass

- [ ] **Step 5: Run full check**

```bash
.\scripts\dev.ps1 -Command check
```
Expected: lint + test pass

- [ ] **Step 6: Commit**

```bash
git add src/scanner/__main__.py scripts/run-scanner.ps1 scripts/dev.ps1
git commit -m "feat: add scanner entrypoint and dev.ps1 integration"
```

---

### Task 9: Final integration test + verify

- [ ] **Step 1: Full check**

```bash
.\scripts\dev.ps1 -Command check
```
Expected: all tests pass, ruff clean

- [ ] **Step 2: Verify scanner imports cleanly**

```bash
.\.venv\Scripts\python -c "from src.scanner import models, gmgn_client, snapshot_store, detector, notifier, orchestrator; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore: finalize scanner module integration"
```
