"""create scanner_token_results table

Revision ID: 8db09e61f553
Revises: 9b8c7d6e5f40
Create Date: 2026-04-28 22:38:58.925481
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "8db09e61f553"
down_revision = "9b8c7d6e5f40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scanner_token_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("filter_passed", sa.Boolean(), nullable=False),
        sa.Column("filter_reason", sa.String(100), nullable=True),
        sa.Column("score_total", sa.Integer(), nullable=True),
        sa.Column("score_breakdown", JSONB(), nullable=True),
        sa.Column("signal_emitted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("signal_level", sa.String(10), nullable=True),
        sa.Column("cooldown_skipped", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_scan_chain_time", "scanner_token_results", ["chain", "scanned_at"])
    op.create_index("idx_scan_filter", "scanner_token_results", ["filter_passed", "filter_reason"])
    op.create_index("idx_scan_score", "scanner_token_results", ["score_total"])
    op.create_index("idx_scan_signal", "scanner_token_results", ["signal_emitted", "signal_level"])


def downgrade() -> None:
    op.drop_table("scanner_token_results")
