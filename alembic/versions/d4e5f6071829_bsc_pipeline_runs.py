"""add bsc pipeline runs table

Revision ID: d4e5f6071829
Revises: c3d4e5f60718
Create Date: 2026-04-18 20:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6071829"
down_revision = "c3d4e5f60718"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bsc_pipeline_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tick_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.String(length=512), nullable=True),
    )
    op.create_unique_constraint(
        "uq_bsc_pipeline_runs_chain_strategy_ts",
        "bsc_pipeline_runs",
        ["chain_id", "strategy_version", "ts_minute"],
    )
    op.create_check_constraint(
        "ck_bsc_pipeline_runs_status",
        "bsc_pipeline_runs",
        "status in ('running','success','failed','skipped')",
    )
    op.create_check_constraint(
        "ck_bsc_pipeline_runs_trigger",
        "bsc_pipeline_runs",
        "trigger in ('manual','scheduler','replay')",
    )
    op.create_index(
        "ix_bsc_pipeline_runs_status_started",
        "bsc_pipeline_runs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_bsc_pipeline_runs_chain_ts",
        "bsc_pipeline_runs",
        ["chain_id", "ts_minute"],
    )


def downgrade() -> None:
    op.drop_index("ix_bsc_pipeline_runs_chain_ts", table_name="bsc_pipeline_runs")
    op.drop_index("ix_bsc_pipeline_runs_status_started", table_name="bsc_pipeline_runs")
    op.drop_constraint("ck_bsc_pipeline_runs_trigger", "bsc_pipeline_runs", type_="check")
    op.drop_constraint("ck_bsc_pipeline_runs_status", "bsc_pipeline_runs", type_="check")
    op.drop_constraint(
        "uq_bsc_pipeline_runs_chain_strategy_ts",
        "bsc_pipeline_runs",
        type_="unique",
    )
    op.drop_table("bsc_pipeline_runs")
