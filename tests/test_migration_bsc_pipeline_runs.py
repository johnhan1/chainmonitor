from pathlib import Path


def test_bsc_pipeline_runs_migration_exists_and_contains_core_constraints() -> None:
    migration = Path("alembic/versions/d4e5f6071829_bsc_pipeline_runs.py")
    content = migration.read_text(encoding="utf-8")

    assert '"bsc_pipeline_runs"' in content
    assert '"uq_bsc_pipeline_runs_chain_strategy_ts"' in content
    assert '"ck_bsc_pipeline_runs_status"' in content
