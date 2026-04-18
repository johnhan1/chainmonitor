"""create core tables

Revision ID: a1b2c3d4e5f6
Revises: 30f4e21d3d32
Create Date: 2026-04-18 16:30:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "30f4e21d3d32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_ticks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_usd", sa.Numeric(24, 10), nullable=False),
        sa.Column("volume_1m", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("volume_5m", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("liquidity_usd", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("buys_1m", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sells_1m", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tx_count_1m", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        "ix_market_ticks_chain_token_ts",
        "market_ticks",
        ["chain_id", "token_id", "ts_minute"],
    )

    op.create_table(
        "onchain_flow_features",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("netflow_usd_5m", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("netflow_usd_30m", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("large_buy_count_30m", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_holder_30m", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("holder_churn_24h", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        "ix_onchain_flow_features_chain_token_ts",
        "onchain_flow_features",
        ["chain_id", "token_id", "ts_minute"],
    )

    op.create_table(
        "risk_features",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contract_risk_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("lp_concentration", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "holder_concentration_top10",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("wash_trade_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("honeypot_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_risk_features_chain_token_ts",
        "risk_features",
        ["chain_id", "token_id", "ts_minute"],
    )

    op.create_table(
        "token_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alpha_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("momentum_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("smart_money_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("narrative_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("risk_penalty", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("final_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("conviction", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        "ix_token_scores_chain_token_ts",
        "token_scores",
        ["chain_id", "token_id", "ts_minute"],
    )
    op.create_index(
        "ix_token_scores_ts_final_score",
        "token_scores",
        ["ts_minute", "final_score"],
    )

    op.create_table(
        "candidate_pool_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("tier", sa.String(length=1), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.create_index(
        "ix_candidate_pool_snapshots_ts_tier_rank",
        "candidate_pool_snapshots",
        ["ts_minute", "tier", "rank"],
    )
    op.create_index(
        "ix_candidate_pool_snapshots_chain_token_ts",
        "candidate_pool_snapshots",
        ["chain_id", "token_id", "ts_minute"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_pool_snapshots_chain_token_ts",
        table_name="candidate_pool_snapshots",
    )
    op.drop_index(
        "ix_candidate_pool_snapshots_ts_tier_rank",
        table_name="candidate_pool_snapshots",
    )
    op.drop_table("candidate_pool_snapshots")

    op.drop_index("ix_token_scores_ts_final_score", table_name="token_scores")
    op.drop_index("ix_token_scores_chain_token_ts", table_name="token_scores")
    op.drop_table("token_scores")

    op.drop_index("ix_risk_features_chain_token_ts", table_name="risk_features")
    op.drop_table("risk_features")

    op.drop_index(
        "ix_onchain_flow_features_chain_token_ts",
        table_name="onchain_flow_features",
    )
    op.drop_table("onchain_flow_features")

    op.drop_index("ix_market_ticks_chain_token_ts", table_name="market_ticks")
    op.drop_table("market_ticks")
