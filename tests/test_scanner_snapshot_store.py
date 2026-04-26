from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

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
        taken_at=datetime.now(timezone.utc),  # noqa: UP017
    )

    store.save("sol", "1m", snap)
    assert mock_engine.begin.called


def test_load_none_when_empty() -> None:
    mock_engine = MagicMock()
    mock_conn = mock_engine.begin.return_value.__enter__.return_value
    mock_conn.execute.return_value.fetchone.return_value = None

    store = SnapshotStore(mock_engine)
    result = store.load("sol", "1m")
    assert result is None
