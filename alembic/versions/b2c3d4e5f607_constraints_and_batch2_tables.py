"""add constraints and batch2 tables

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
Create Date: 2026-04-18 16:50:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f607"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _add_core_constraints() -> None:
    if _is_sqlite():
        with op.batch_alter_table("market_ticks", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_market_ticks_chain_token_ts",
                ["chain_id", "token_id", "ts_minute"],
            )
        with op.batch_alter_table("onchain_flow_features", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_onchain_flow_features_chain_token_ts",
                ["chain_id", "token_id", "ts_minute"],
            )
        with op.batch_alter_table("risk_features", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_risk_features_chain_token_ts",
                ["chain_id", "token_id", "ts_minute"],
            )
        with op.batch_alter_table("token_scores", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_token_scores_strategy_chain_token_ts",
                ["strategy_version", "chain_id", "token_id", "ts_minute"],
            )
        with op.batch_alter_table("candidate_pool_snapshots", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_candidate_pool_snapshots_strategy_chain_token_ts",
                ["strategy_version", "chain_id", "token_id", "ts_minute"],
            )
            batch_op.create_check_constraint(
                "ck_candidate_pool_snapshots_tier",
                "tier in ('A','B','C')",
            )
            batch_op.create_check_constraint(
                "ck_candidate_pool_snapshots_rank_non_negative",
                "rank >= 0",
            )
        return

    op.create_unique_constraint(
        "uq_market_ticks_chain_token_ts",
        "market_ticks",
        ["chain_id", "token_id", "ts_minute"],
    )
    op.create_unique_constraint(
        "uq_onchain_flow_features_chain_token_ts",
        "onchain_flow_features",
        ["chain_id", "token_id", "ts_minute"],
    )
    op.create_unique_constraint(
        "uq_risk_features_chain_token_ts",
        "risk_features",
        ["chain_id", "token_id", "ts_minute"],
    )
    op.create_unique_constraint(
        "uq_token_scores_strategy_chain_token_ts",
        "token_scores",
        ["strategy_version", "chain_id", "token_id", "ts_minute"],
    )
    op.create_unique_constraint(
        "uq_candidate_pool_snapshots_strategy_chain_token_ts",
        "candidate_pool_snapshots",
        ["strategy_version", "chain_id", "token_id", "ts_minute"],
    )
    op.create_check_constraint(
        "ck_candidate_pool_snapshots_tier",
        "candidate_pool_snapshots",
        "tier in ('A','B','C')",
    )
    op.create_check_constraint(
        "ck_candidate_pool_snapshots_rank_non_negative",
        "candidate_pool_snapshots",
        "rank >= 0",
    )


def _drop_core_constraints() -> None:
    if _is_sqlite():
        with op.batch_alter_table("candidate_pool_snapshots", recreate="always") as batch_op:
            batch_op.drop_constraint("ck_candidate_pool_snapshots_rank_non_negative", type_="check")
            batch_op.drop_constraint("ck_candidate_pool_snapshots_tier", type_="check")
            batch_op.drop_constraint(
                "uq_candidate_pool_snapshots_strategy_chain_token_ts",
                type_="unique",
            )
        with op.batch_alter_table("token_scores", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_token_scores_strategy_chain_token_ts", type_="unique")
        with op.batch_alter_table("risk_features", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_risk_features_chain_token_ts", type_="unique")
        with op.batch_alter_table("onchain_flow_features", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_onchain_flow_features_chain_token_ts", type_="unique")
        with op.batch_alter_table("market_ticks", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_market_ticks_chain_token_ts", type_="unique")
        return

    op.drop_constraint(
        "ck_candidate_pool_snapshots_rank_non_negative",
        "candidate_pool_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_candidate_pool_snapshots_tier",
        "candidate_pool_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "uq_candidate_pool_snapshots_strategy_chain_token_ts",
        "candidate_pool_snapshots",
        type_="unique",
    )
    op.drop_constraint(
        "uq_token_scores_strategy_chain_token_ts",
        "token_scores",
        type_="unique",
    )
    op.drop_constraint(
        "uq_risk_features_chain_token_ts",
        "risk_features",
        type_="unique",
    )
    op.drop_constraint(
        "uq_onchain_flow_features_chain_token_ts",
        "onchain_flow_features",
        type_="unique",
    )
    op.drop_constraint(
        "uq_market_ticks_chain_token_ts",
        "market_ticks",
        type_="unique",
    )


def upgrade() -> None:
    # Core table constraints
    _add_core_constraints()

    # Batch-2 tables
    op.create_table(
        "trade_signals",
        sa.Column("signal_id", sa.String(length=64), primary_key=True),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("entry_rule_id", sa.String(length=64), nullable=False),
        sa.Column("exit_rule_id", sa.String(length=64), nullable=False),
        sa.Column("signal_score", sa.Numeric(10, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint("side in ('BUY','SELL')", name="ck_trade_signals_side"),
    )
    op.create_index(
        "ix_trade_signals_chain_token_time",
        "trade_signals",
        ["chain_id", "token_id", "signal_time"],
    )
    op.create_index(
        "ix_trade_signals_strategy_status",
        "trade_signals",
        ["strategy_version", "status"],
    )

    op.create_table(
        "paper_orders",
        sa.Column("order_id", sa.String(length=64), primary_key=True),
        sa.Column("signal_id", sa.String(length=64), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_px", sa.Numeric(24, 10), nullable=False),
        sa.Column("filled_px", sa.Numeric(24, 10), nullable=True),
        sa.Column("qty", sa.Numeric(24, 10), nullable=False),
        sa.Column("notional_usd", sa.Numeric(24, 10), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("gas_usd", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("fee_usd", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column("fill_status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["trade_signals.signal_id"], ondelete="CASCADE"),
        sa.CheckConstraint("qty > 0", name="ck_paper_orders_qty_positive"),
    )
    op.create_index("ix_paper_orders_signal_id", "paper_orders", ["signal_id"])
    op.create_index(
        "ix_paper_orders_placed_at_status",
        "paper_orders",
        ["placed_at", "fill_status"],
    )

    op.create_table(
        "paper_positions",
        sa.Column("position_id", sa.String(length=64), primary_key=True),
        sa.Column("chain_id", sa.String(length=32), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_px", sa.Numeric(24, 10), nullable=False),
        sa.Column("exit_px", sa.Numeric(24, 10), nullable=True),
        sa.Column("qty", sa.Numeric(24, 10), nullable=False),
        sa.Column("pnl_usd", sa.Numeric(24, 10), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "max_drawdown_pct",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("close_reason", sa.String(length=64), nullable=True),
        sa.CheckConstraint("qty > 0", name="ck_paper_positions_qty_positive"),
    )
    op.create_index(
        "ix_paper_positions_chain_token_opened",
        "paper_positions",
        ["chain_id", "token_id", "opened_at"],
    )

    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("period_end >= period_start", name="ck_backtest_runs_period_valid"),
    )
    op.create_index(
        "ix_backtest_runs_strategy_created",
        "backtest_runs",
        ["strategy_version", "created_at"],
    )

    op.create_table(
        "strategy_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("parent_version", sa.String(length=64), nullable=True),
        sa.Column("weights_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("thresholds_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("risk_rules_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("regime_rules_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_version"], ["strategy_versions.version_id"]),
    )
    op.create_index("ix_strategy_versions_status", "strategy_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_strategy_versions_status", table_name="strategy_versions")
    op.drop_table("strategy_versions")

    op.drop_index("ix_backtest_runs_strategy_created", table_name="backtest_runs")
    op.drop_table("backtest_runs")

    op.drop_index("ix_paper_positions_chain_token_opened", table_name="paper_positions")
    op.drop_table("paper_positions")

    op.drop_index("ix_paper_orders_placed_at_status", table_name="paper_orders")
    op.drop_index("ix_paper_orders_signal_id", table_name="paper_orders")
    op.drop_table("paper_orders")

    op.drop_index("ix_trade_signals_strategy_status", table_name="trade_signals")
    op.drop_index("ix_trade_signals_chain_token_time", table_name="trade_signals")
    op.drop_table("trade_signals")

    _drop_core_constraints()
