"""allow replay history rows in pipeline_runs

Revision ID: a9c1f4e7b2d8
Revises: f60718293a4b
Create Date: 2026-04-19 14:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a9c1f4e7b2d8"
down_revision = "f60718293a4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_pipeline_runs_chain_strategy_ts",
        "pipeline_runs",
        type_="unique",
    )
    op.create_index(
        "ux_pipeline_runs_chain_strategy_ts_non_replay",
        "pipeline_runs",
        ["chain_id", "strategy_version", "ts_minute"],
        unique=True,
        postgresql_where=sa.text("trigger <> 'replay'"),
    )


def downgrade() -> None:
    op.drop_index("ux_pipeline_runs_chain_strategy_ts_non_replay", table_name="pipeline_runs")
    op.create_unique_constraint(
        "uq_pipeline_runs_chain_strategy_ts",
        "pipeline_runs",
        ["chain_id", "strategy_version", "ts_minute"],
    )
