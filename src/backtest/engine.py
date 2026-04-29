from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from src.backtest.cost_model import TradeCost, TradeCostModel
from src.feature.feature_engine import FeatureEngine
from src.scoring.scoring_engine import ScoringEngine
from src.shared.config.chain import get_chain_settings
from src.shared.config.pipeline import get_pipeline_settings
from src.shared.schemas.backtest import BacktestConfig, BacktestMetrics, BacktestTradeResult
from src.shared.schemas.pipeline import MarketTickInput


class _BacktestSyntheticSource:
    def __init__(self, chain_id: str, symbols: tuple[str, ...]) -> None:
        self._chain_id = chain_id
        self._symbols = symbols

    async def fetch_market_ticks(self, ts_minute: datetime | None = None) -> list[MarketTickInput]:
        target_ts = self._normalize_ts(ts_minute)
        rows: list[MarketTickInput] = []
        for symbol in self._symbols:
            seed = self._seed(symbol=symbol, ts=target_ts)
            price = 1 + (seed % 50_000) / 1_000
            volume_1m = 5_000 + (seed % 80_000)
            volume_5m = volume_1m * (1.1 + (seed % 30) / 100)
            liquidity = 100_000 + (seed % 900_000)
            buys = 20 + seed % 80
            sells = 10 + seed % 60
            rows.append(
                MarketTickInput(
                    chain_id=self._chain_id,
                    token_id=f"{self._chain_id}_{symbol.lower()}",
                    ts_minute=target_ts,
                    price_usd=round(price, 6),
                    volume_1m=float(volume_1m),
                    volume_5m=float(volume_5m),
                    liquidity_usd=float(liquidity),
                    buys_1m=buys,
                    sells_1m=sells,
                    tx_count_1m=buys + sells + seed % 20,
                )
            )
        return rows

    @staticmethod
    def _normalize_ts(ts_minute: datetime | None) -> datetime:
        if ts_minute is None:
            return datetime.now(tz=UTC).replace(second=0, microsecond=0)
        return ts_minute.astimezone(UTC).replace(second=0, microsecond=0)

    @staticmethod
    def _seed(symbol: str, ts: datetime) -> int:
        digest = sha256(f"{symbol}:{ts.isoformat()}".encode()).hexdigest()
        return int(digest[:12], 16)


class BacktestEngine:
    def __init__(self, chain_id: str) -> None:
        chain_settings = get_chain_settings()
        pipeline_settings = get_pipeline_settings()
        if chain_id not in chain_settings.supported_chains:
            raise ValueError(f"unsupported chain_id: {chain_id}")
        self.pipeline_settings = pipeline_settings
        self.chain_id = chain_id
        symbols = tuple(
            symbol.strip().upper()
            for symbol in chain_settings.get_chain_symbols(chain_id).split(",")
            if symbol.strip()
        )
        self.source = _BacktestSyntheticSource(chain_id=chain_id, symbols=symbols)
        self.feature_engine = FeatureEngine()
        self.scoring_engine = ScoringEngine(
            strategy_version=chain_settings.get_strategy_version(chain_id=chain_id)
        )

    async def run(
        self, config: BacktestConfig
    ) -> tuple[list[BacktestTradeResult], BacktestMetrics]:
        if config.period_end < config.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")

        trade_cost_model = TradeCostModel(config=config)
        trades: list[BacktestTradeResult] = []
        costs: list[TradeCost] = []
        for ts_minute in self._iter_minutes(config.period_start, config.period_end):
            ticks = self._apply_gate(await self.source.fetch_market_ticks(ts_minute=ts_minute))
            if not ticks:
                continue
            features = self.feature_engine.build_features(ticks)
            score_rows = self.scoring_engine.score(ticks=ticks, features=features)
            for score in score_rows:
                if score.conviction < config.conviction_threshold:
                    continue
                expected_return = self._expected_return_pct(
                    token_id=score.token_id,
                    ts_minute=score.ts_minute,
                    strategy_version=config.strategy_version,
                    stop_loss_pct=config.stop_loss_pct,
                    take_profit_pct=config.take_profit_pct,
                )
                failed = self._is_failed_trade(
                    token_id=score.token_id,
                    ts_minute=score.ts_minute,
                    fail_probability=config.fail_probability,
                )
                gross_pnl = 0.0 if failed else config.trade_size_usd * expected_return
                cost = trade_cost_model.estimate(notional_usd=config.trade_size_usd)
                net_pnl = gross_pnl - cost.total
                trades.append(
                    BacktestTradeResult(
                        chain_id=self.chain_id,
                        token_id=score.token_id,
                        ts_minute=score.ts_minute,
                        conviction=score.conviction,
                        expected_return_pct=round(expected_return, 8),
                        gross_pnl_usd=round(gross_pnl, 8),
                        cost_usd=round(cost.total, 8),
                        net_pnl_usd=round(net_pnl, 8),
                        failed=failed,
                    )
                )
                costs.append(cost)
        metrics = self._build_metrics(
            trades=trades, costs=costs, trade_size_usd=config.trade_size_usd
        )
        return trades, metrics

    @staticmethod
    def _iter_minutes(start: datetime, end: datetime) -> list[datetime]:
        cursor = start.astimezone(UTC).replace(second=0, microsecond=0)
        stop = end.astimezone(UTC).replace(second=0, microsecond=0)
        points: list[datetime] = []
        while cursor <= stop:
            points.append(cursor)
            cursor += timedelta(minutes=1)
        return points

    def _apply_gate(self, ticks: list[MarketTickInput]) -> list[MarketTickInput]:
        return [
            tick
            for tick in ticks
            if tick.liquidity_usd >= self.pipeline_settings.min_liquidity_usd
            and tick.volume_5m >= self.pipeline_settings.min_volume_5m_usd
            and tick.tx_count_1m >= self.pipeline_settings.min_tx_1m
        ]

    @staticmethod
    def _expected_return_pct(
        token_id: str,
        ts_minute: datetime,
        strategy_version: str,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> float:
        seed = BacktestEngine._stable_unit_value(
            f"{strategy_version}:{token_id}:{ts_minute.isoformat()}"
        )
        raw = (seed * 0.20) - 0.08  # [-8%, +12%]
        return max(-stop_loss_pct, min(take_profit_pct, raw))

    @staticmethod
    def _is_failed_trade(token_id: str, ts_minute: datetime, fail_probability: float) -> bool:
        if fail_probability <= 0:
            return False
        unit = BacktestEngine._stable_unit_value(f"fail:{token_id}:{ts_minute.isoformat()}")
        return unit < fail_probability

    @staticmethod
    def _stable_unit_value(payload: str) -> float:
        digest = sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:12], 16) / float(16**12 - 1)

    @staticmethod
    def _build_metrics(
        trades: list[BacktestTradeResult],
        costs: list[TradeCost],
        trade_size_usd: float,
    ) -> BacktestMetrics:
        if not trades:
            return BacktestMetrics(
                trade_count=0,
                win_count=0,
                lose_count=0,
                win_rate=0.0,
                net_pnl_usd=0.0,
                gross_profit_usd=0.0,
                gross_loss_usd=0.0,
                pf=0.0,
                expectancy=0.0,
                max_dd_pct=0.0,
                cost_breakdown=TradeCostModel.summarize(costs),
            )

        net_values = [row.net_pnl_usd for row in trades]
        wins = [v for v in net_values if v > 0]
        losses = [v for v in net_values if v <= 0]
        gross_profit = sum(wins)
        gross_loss_abs = abs(sum(losses))
        pf = gross_profit / gross_loss_abs if gross_loss_abs > 0 else 99.0
        win_rate = len(wins) / len(trades)
        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss_abs / len(losses) if losses else 0.0
        lose_rate = 1.0 - win_rate
        expectancy = (win_rate * avg_win) - (lose_rate * avg_loss)
        max_dd_pct = BacktestEngine._max_drawdown_pct(net_values, trade_size_usd=trade_size_usd)

        return BacktestMetrics(
            trade_count=len(trades),
            win_count=len(wins),
            lose_count=len(losses),
            win_rate=round(win_rate, 8),
            net_pnl_usd=round(sum(net_values), 8),
            gross_profit_usd=round(gross_profit, 8),
            gross_loss_usd=round(gross_loss_abs, 8),
            pf=round(pf, 8),
            expectancy=round(expectancy, 8),
            max_dd_pct=round(max_dd_pct, 8),
            cost_breakdown=TradeCostModel.summarize(costs),
        )

    @staticmethod
    def _max_drawdown_pct(net_values: list[float], trade_size_usd: float) -> float:
        equity = trade_size_usd * 10.0
        peak = equity
        max_dd = 0.0
        for pnl in net_values:
            equity += pnl
            if equity > peak:
                peak = equity
            if peak <= 0:
                continue
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd
