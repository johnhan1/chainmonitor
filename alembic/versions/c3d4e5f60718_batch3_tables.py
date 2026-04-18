"""create batch3 tables

Revision ID: c3d4e5f60718
Revises: b2c3d4e5f607
Create Date: 2026-04-18 17:20:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d4e5f60718"
down_revision = "b2c3d4e5f607"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smart_money_features",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sm_buy_wallets_30m", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sm_netflow_usd_30m", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "sm_winrate_weighted_score",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.UniqueConstraint(
            "chain_id",
            "token_id",
            "ts_minute",
            name="uq_smart_money_features_chain_token_ts",
        ),
    )
    op.create_index(
        "ix_smart_money_features_chain_token_ts",
        "smart_money_features",
        ["chain_id", "token_id", "ts_minute"],
    )

    op.create_table(
        "narrative_features",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mention_count_30m", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "mention_growth_2h",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("dev_activity_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "cross_chain_narrative_score",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.UniqueConstraint(
            "chain_id",
            "token_id",
            "ts_minute",
            name="uq_narrative_features_chain_token_ts",
        ),
    )
    op.create_index(
        "ix_narrative_features_chain_token_ts",
        "narrative_features",
        ["chain_id", "token_id", "ts_minute"],
    )

    op.create_table(
        "backtest_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("net_pnl_usd", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("pf", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("win_rate", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("expectancy", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("max_dd_pct", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("sharpe_like", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("calmar_like", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("turnover", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("capacity_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.run_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", name="uq_backtest_metrics_run_id"),
    )
    op.create_index("ix_backtest_metrics_run_id", "backtest_metrics", ["run_id"])

    op.create_table(
        "data_source_health",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("ts_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_rate", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("missing_rate", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("fallback_level", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint(
            "source_name",
            "chain_id",
            "ts_minute",
            name="uq_data_source_health_source_chain_ts",
        ),
        sa.CheckConstraint(
            "fallback_level >= 1 and fallback_level <= 3",
            name="ck_data_source_health_fallback_level",
        ),
    )
    op.create_index(
        "ix_data_source_health_chain_ts",
        "data_source_health",
        ["chain_id", "ts_minute"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_source_health_chain_ts", table_name="data_source_health")
    op.drop_table("data_source_health")

    op.drop_index("ix_backtest_metrics_run_id", table_name="backtest_metrics")
    op.drop_table("backtest_metrics")

    op.drop_index("ix_narrative_features_chain_token_ts", table_name="narrative_features")
    op.drop_table("narrative_features")

    op.drop_index("ix_smart_money_features_chain_token_ts", table_name="smart_money_features")
    op.drop_table("smart_money_features")
