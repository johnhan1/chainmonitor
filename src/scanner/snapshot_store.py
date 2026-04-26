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
