from pathlib import Path


def test_batch3_migration_contains_expected_tables() -> None:
    migration = Path("alembic/versions/c3d4e5f60718_batch3_tables.py")
    content = migration.read_text(encoding="utf-8")

    expected_tables = [
        "smart_money_features",
        "narrative_features",
        "backtest_metrics",
        "data_source_health",
    ]

    for table in expected_tables:
        assert f'"{table}"' in content

