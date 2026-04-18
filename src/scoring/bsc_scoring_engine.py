from __future__ import annotations

from src.shared.config import get_settings
from src.shared.schemas.pipeline import FeatureRowInput, MarketTickInput, ScoreRowInput


class BscScoringEngine:
    def __init__(self, strategy_version: str = "bsc-mvp-v1") -> None:
        self.settings = get_settings()
        self.strategy_version = strategy_version

    def score(
        self,
        ticks: list[MarketTickInput],
        features: list[FeatureRowInput],
    ) -> list[ScoreRowInput]:
        feature_by_token = {f.token_id: f for f in features}
        rows: list[ScoreRowInput] = []
        for tick in ticks:
            feature = feature_by_token[tick.token_id]
            alpha = min(100.0, 35 + tick.volume_5m / 2000 + tick.liquidity_usd / 50_000)
            momentum = min(100.0, 20 + (tick.buys_1m - tick.sells_1m) * 1.5)
            smart_money = min(100.0, 15 + feature.large_buy_count_30m * 2.2)
            narrative = min(100.0, 10 + tick.tx_count_1m * 0.8)
            risk_penalty = (
                feature.contract_risk_score * 20
                + feature.lp_concentration * 12
                + feature.holder_concentration_top10 * 12
                + feature.wash_trade_score * 8
                + (40 if feature.honeypot_flag else 0)
            )
            final_score = (
                0.55 * alpha
                + 0.20 * momentum
                + 0.15 * smart_money
                + 0.10 * narrative
                - risk_penalty
            )
            confidence = max(0.5, min(0.98, 0.85 - feature.wash_trade_score * 0.2))
            conviction = max(0.0, min(100.0, final_score * confidence))
            tier = self._tier(conviction)
            reason_codes = self._reason_codes(tick=tick, feature=feature, conviction=conviction)
            rows.append(
                ScoreRowInput(
                    strategy_version=self.strategy_version,
                    chain_id=tick.chain_id,
                    token_id=tick.token_id,
                    ts_minute=tick.ts_minute,
                    alpha_score=round(alpha, 6),
                    momentum_score=round(momentum, 6),
                    smart_money_score=round(smart_money, 6),
                    narrative_score=round(narrative, 6),
                    risk_penalty=round(risk_penalty, 6),
                    final_score=round(final_score, 6),
                    conviction=round(conviction, 6),
                    confidence=round(confidence, 6),
                    tier=tier,
                    reason_codes=reason_codes,
                )
            )
        return rows

    def _tier(self, conviction: float) -> str:
        if conviction >= self.settings.candidate_tier_a_threshold:
            return "A"
        if conviction >= self.settings.candidate_tier_b_threshold:
            return "B"
        if conviction >= self.settings.candidate_tier_c_threshold:
            return "C"
        return "C"

    @staticmethod
    def _reason_codes(
        tick: MarketTickInput,
        feature: FeatureRowInput,
        conviction: float,
    ) -> list[str]:
        reasons: list[str] = []
        if tick.liquidity_usd >= 250_000:
            reasons.append("liquidity_ok")
        if feature.netflow_usd_30m > 0:
            reasons.append("positive_netflow")
        if tick.buys_1m > tick.sells_1m:
            reasons.append("buy_pressure")
        if conviction < 55:
            reasons.append("low_conviction")
        return reasons or ["insufficient_signal"]

