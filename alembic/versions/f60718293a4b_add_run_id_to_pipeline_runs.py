"""add run_id to pipeline_runs

Revision ID: f60718293a4b
Revises: e5f60718293a
Create Date: 2026-04-19 11:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f60718293a4b"
down_revision = "e5f60718293a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("run_id", sa.String(length=32), nullable=True))
    op.execute("UPDATE pipeline_runs SET run_id = CONCAT('legacy-', id::text) WHERE run_id IS NULL")
    op.alter_column("pipeline_runs", "run_id", existing_type=sa.String(length=32), nullable=False)
    op.create_unique_constraint(
        "uq_pipeline_runs_run_id",
        "pipeline_runs",
        ["run_id"],
    )
    op.create_index("ix_pipeline_runs_run_id", "pipeline_runs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_run_id", table_name="pipeline_runs")
    op.drop_constraint("uq_pipeline_runs_run_id", "pipeline_runs", type_="unique")
    op.drop_column("pipeline_runs", "run_id")
