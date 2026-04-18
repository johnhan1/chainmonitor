from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from src.shared.config import get_settings


def test_alembic_upgrade_head_on_temp_sqlite_db(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "migration_test.db"
    sqlite_dsn = f"sqlite+pysqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("CM_POSTGRES_DSN", sqlite_dsn)
    get_settings.cache_clear()

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_dsn)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    expected_tables = {
        "market_ticks",
        "onchain_flow_features",
        "risk_features",
        "token_scores",
        "candidate_pool_snapshots",
        "trade_signals",
        "paper_orders",
        "paper_positions",
        "backtest_runs",
        "strategy_versions",
        "smart_money_features",
        "narrative_features",
        "backtest_metrics",
        "data_source_health",
    }
    assert expected_tables.issubset(table_names)

    with engine.connect() as conn:
        version_rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    assert len(version_rows) == 1

    get_settings.cache_clear()
