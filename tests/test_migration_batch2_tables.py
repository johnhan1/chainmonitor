from pathlib import Path


def test_batch2_migration_contains_expected_tables_and_constraints() -> None:
    migration = Path("alembic/versions/b2c3d4e5f607_constraints_and_batch2_tables.py")
    content = migration.read_text(encoding="utf-8")

    expected_tables = [
        "trade_signals",
        "paper_orders",
        "paper_positions",
        "backtest_runs",
        "strategy_versions",
    ]
    expected_constraints = [
        "ck_candidate_pool_snapshots_tier",
        "uq_market_ticks_chain_token_ts",
    ]

    for table in expected_tables:
        assert f'"{table}"' in content

    for constraint in expected_constraints:
        assert f'"{constraint}"' in content

