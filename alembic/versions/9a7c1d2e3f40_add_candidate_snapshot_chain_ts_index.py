"""add chain+ts index for latest candidate snapshot query

Revision ID: 9a7c1d2e3f40
Revises: f60718293a4b
Create Date: 2026-04-19 14:30:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "9a7c1d2e3f40"
down_revision = "f60718293a4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_candidate_pool_snapshots_chain_ts",
        "candidate_pool_snapshots",
        ["chain_id", "ts_minute"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_pool_snapshots_chain_ts",
        table_name="candidate_pool_snapshots",
    )
