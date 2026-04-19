from pathlib import Path


def test_pipeline_runs_run_id_migration_exists_and_contains_constraints() -> None:
    migration = Path("alembic/versions/f60718293a4b_add_run_id_to_pipeline_runs.py")
    content = migration.read_text(encoding="utf-8")

    assert '"pipeline_runs"' in content
    assert '"run_id"' in content
    assert "uq_pipeline_runs_run_id" in content
