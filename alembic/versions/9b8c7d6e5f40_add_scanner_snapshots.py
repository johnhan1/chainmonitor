"""add scanner_snapshots table

Revision ID: 9b8c7d6e5f40
Revises: f60718293a4b
Create Date: 2026-04-26 21:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "9b8c7d6e5f40"
down_revision = "f60718293a4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scanner_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain", sa.String(length=10), nullable=False),
        sa.Column("interval", sa.String(length=5), nullable=False),
        sa.Column("snapshot_data", JSONB(), nullable=False),
        sa.Column(
            "taken_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_unique_constraint(
        "uq_scanner_snapshots_chain_interval", "scanner_snapshots", ["chain", "interval"]
    )
    op.create_index("ix_scanner_snapshots_taken_at", "scanner_snapshots", ["taken_at"])


def downgrade() -> None:
    op.drop_index("ix_scanner_snapshots_taken_at")
    op.drop_constraint("uq_scanner_snapshots_chain_interval", "scanner_snapshots")
    op.drop_table("scanner_snapshots")
