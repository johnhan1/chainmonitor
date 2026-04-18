from pathlib import Path


def test_core_migration_contains_expected_tables() -> None:
    migration = Path("alembic/versions/a1b2c3d4e5f6_create_core_tables.py")
    content = migration.read_text(encoding="utf-8")

    expected_tables = [
        "market_ticks",
        "onchain_flow_features",
        "risk_features",
        "token_scores",
        "candidate_pool_snapshots",
    ]

    for table in expected_tables:
        assert f'"{table}"' in content

