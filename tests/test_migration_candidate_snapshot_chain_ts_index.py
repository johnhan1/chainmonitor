from pathlib import Path


def test_candidate_snapshot_chain_ts_index_migration_exists() -> None:
    migration = Path("alembic/versions/9a7c1d2e3f40_add_candidate_snapshot_chain_ts_index.py")
    content = migration.read_text(encoding="utf-8")
    assert '"candidate_pool_snapshots"' in content
    assert '"ix_candidate_pool_snapshots_chain_ts"' in content
    assert '["chain_id", "ts_minute"]' in content
