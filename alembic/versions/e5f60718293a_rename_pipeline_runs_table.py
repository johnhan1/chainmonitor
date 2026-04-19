"""rename bsc pipeline runs table to generic pipeline runs

Revision ID: e5f60718293a
Revises: d4e5f6071829
Create Date: 2026-04-19 10:30:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f60718293a"
down_revision = "d4e5f6071829"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("bsc_pipeline_runs", "pipeline_runs")
    op.execute(
        "ALTER TABLE pipeline_runs "
        "RENAME CONSTRAINT uq_bsc_pipeline_runs_chain_strategy_ts "
        "TO uq_pipeline_runs_chain_strategy_ts"
    )
    op.execute(
        "ALTER TABLE pipeline_runs "
        "RENAME CONSTRAINT ck_bsc_pipeline_runs_status "
        "TO ck_pipeline_runs_status"
    )
    op.execute(
        "ALTER TABLE pipeline_runs "
        "RENAME CONSTRAINT ck_bsc_pipeline_runs_trigger "
        "TO ck_pipeline_runs_trigger"
    )
    op.execute(
        "ALTER INDEX ix_bsc_pipeline_runs_status_started RENAME TO ix_pipeline_runs_status_started"
    )
    op.execute("ALTER INDEX ix_bsc_pipeline_runs_chain_ts RENAME TO ix_pipeline_runs_chain_ts")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_pipeline_runs_chain_ts RENAME TO ix_bsc_pipeline_runs_chain_ts")
    op.execute(
        "ALTER INDEX ix_pipeline_runs_status_started RENAME TO ix_bsc_pipeline_runs_status_started"
    )
    op.execute(
        "ALTER TABLE pipeline_runs "
        "RENAME CONSTRAINT ck_pipeline_runs_trigger "
        "TO ck_bsc_pipeline_runs_trigger"
    )
    op.execute(
        "ALTER TABLE pipeline_runs "
        "RENAME CONSTRAINT ck_pipeline_runs_status "
        "TO ck_bsc_pipeline_runs_status"
    )
    op.execute(
        "ALTER TABLE pipeline_runs "
        "RENAME CONSTRAINT uq_pipeline_runs_chain_strategy_ts "
        "TO uq_bsc_pipeline_runs_chain_strategy_ts"
    )
    op.rename_table("pipeline_runs", "bsc_pipeline_runs")
