from __future__ import annotations

import logging

from src.scanner.models import (
    AlphaSignal,
    FilterResult,
    ScoredToken,
    Snapshot,
    TokenRisk,
    TrendingToken,
)

logger = logging.getLogger(__name__)


class AlphaScorer:
    def __init__(
        self,
        min_liquidity: float = 50_000.0,
        max_rug_risk: float = 0.8,
        max_bundler_rat_ratio: float = 0.7,
        surge_threshold: int = 10,
        spike_ratio: float = 2.0,
    ) -> None:
        self._min_liquidity = min_liquidity
        self._max_rug_risk = max_rug_risk
        self._max_bundler_rat_ratio = max_bundler_rat_ratio
        self._surge_threshold = surge_threshold
        self._spike_ratio = spike_ratio

    def hard_filter(self, token: TrendingToken, risk: TokenRisk | None) -> FilterResult:
        if token.liquidity is not None and token.liquidity < self._min_liquidity:
            return FilterResult(
                passed=False,
                reason=f"liquidity={token.liquidity} < {self._min_liquidity}",
            )
        if risk:
            if risk.is_honeypot:
                return FilterResult(passed=False, reason="honeypot")
            if risk.rug_risk > self._max_rug_risk:
                return FilterResult(passed=False, reason=f"rug_risk={risk.rug_risk:.2f}")
            if (risk.bundler_ratio + risk.rat_ratio) > self._max_bundler_rat_ratio:
                return FilterResult(
                    passed=False,
                    reason=f"bundler+rat={risk.bundler_ratio + risk.rat_ratio:.2f}",
                )
        if token.smart_degen_count is not None and token.smart_degen_count == 0:
            vol = token.volume_1m or 0
            if vol > 100_000:
                return FilterResult(passed=False, reason="high_volume_no_smart_degen")
        return FilterResult(passed=True)

    def score(
        self,
        token: TrendingToken,
        prev: TrendingToken | None,
        risk: TokenRisk | None,
    ) -> ScoredToken:
        breakdown: dict[str, int] = {}

        # 聪明钱领先 (max 30)
        smart_score = 0
        if token.smart_degen_count is not None:
            if prev and prev.smart_degen_count is not None:
                delta = token.smart_degen_count - prev.smart_degen_count
                if delta >= 5:
                    smart_score = 30
                elif delta >= 3:
                    smart_score = 25
                elif delta >= 1:
                    smart_score = 20
                elif token.smart_degen_count >= 10:
                    smart_score = 15
            elif token.smart_degen_count >= 5:
                smart_score = 15
            if token.smart_degen_count >= 3:
                smart_score = max(smart_score, 10)
        breakdown["smart_money"] = smart_score

        # 排名加速度 (max 20)
        rank_score = 0
        if prev and prev.rank != token.rank:
            change = prev.rank - token.rank
            if change >= 20:
                rank_score = 20
            elif change >= 10:
                rank_score = 15
            elif change >= 5:
                rank_score = 10
            elif change > 0:
                rank_score = 5
        elif prev is None:
            rank_score = 10
        breakdown["rank_momentum"] = rank_score

        # 成交量质量 (max 15)
        vol_score = 0
        if token.volume_1m and token.liquidity and token.liquidity > 0:
            ratio = token.volume_1m / token.liquidity
            if 0.5 <= ratio <= 5.0:
                vol_score = 15
            elif 0.1 <= ratio <= 10.0:
                vol_score = 10
            else:
                vol_score = 5
        if vol_score == 0 and token.volume_1m and token.volume_1m > 0:
            vol_score = 5
        breakdown["volume_quality"] = vol_score

        # 结构健康度 (max 15)
        struct_score = 10
        if risk:
            struct_score = 10
            if risk.bundler_ratio < 0.2:
                struct_score += 3
            if risk.rat_ratio < 0.2:
                struct_score += 2
            if risk.top10_holder_pct < 0.5:
                struct_score += 3
            if risk.sniper_count < 5:
                struct_score += 2
            struct_score = min(struct_score, 15)
        breakdown["structure"] = struct_score

        # 多时间帧确认 (max 10)
        tf_score = 0
        breakdown["timeframe"] = tf_score

        # 风险折价 (max -10)
        risk_penalty = 0
        if risk:
            if risk.rug_risk > 0.7:
                risk_penalty = -10
            elif risk.rug_risk > 0.5:
                risk_penalty = -5
            if risk.is_honeypot:
                risk_penalty = -10
        breakdown["risk_penalty"] = risk_penalty

        total = sum(breakdown.values())
        total = max(0, min(100, total))

        return ScoredToken(
            token=token,
            score=total,
            breakdown=breakdown,
            risk=risk,
        )

    def detect(
        self,
        prev: Snapshot | None,
        curr: Snapshot,
        risks: dict[str, TokenRisk] | None = None,
    ) -> list[AlphaSignal]:
        if prev is None:
            return []

        prev_map: dict[str, TrendingToken] = {t.address: t for t in prev.tokens}
        signals: list[AlphaSignal] = []

        for token in curr.tokens:
            risk = (risks or {}).get(token.address)
            fr = self.hard_filter(token, risk)
            if not fr.passed:
                continue

            prev_token = prev_map.get(token.address)
            scored = self.score(token, prev_token, risk)

            if scored.score >= 75:
                level = "HIGH"
            elif scored.score >= 65:
                level = "MEDIUM"
            elif scored.score >= 55:
                level = "OBSERVE"
            else:
                continue

            signals.append(
                AlphaSignal(
                    token=scored,
                    level=level,
                    chain=curr.chain,
                    interval=curr.interval,
                    detected_at=curr.taken_at,
                )
            )

        return signals
