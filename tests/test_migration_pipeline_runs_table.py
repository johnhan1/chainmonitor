from pathlib import Path


def test_pipeline_runs_rename_migration_exists_and_renames_table() -> None:
    migration = Path("alembic/versions/e5f60718293a_rename_pipeline_runs_table.py")
    content = migration.read_text(encoding="utf-8")

    assert '"bsc_pipeline_runs"' in content
    assert '"pipeline_runs"' in content
    assert "uq_pipeline_runs_chain_strategy_ts" in content
