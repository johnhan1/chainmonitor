from __future__ import annotations

from datetime import UTC, datetime

from src.scanner.detector import AlphaScorer
from src.scanner.models import AlphaSignal, Snapshot, TokenRisk, TrendingToken


def _token(
    address: str,
    symbol: str,
    rank: int,
    volume_1m: float | None = None,
    smart_degen: int | None = None,
    liquidity: float | None = None,
) -> TrendingToken:
    return TrendingToken(
        address=address,
        symbol=symbol,
        name=symbol,
        price_usd=0.1,
        rank=rank,
        chain="sol",
        volume_1m=volume_1m,
        smart_degen_count=smart_degen,
        liquidity=liquidity,
    )


def _snapshot(tokens: list[TrendingToken]) -> Snapshot:
    return Snapshot(chain="sol", interval="1m", tokens=tokens, taken_at=datetime.now(UTC))


def test_hard_filter_pass_with_risk() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, liquidity=100_000, volume_1m=1000, smart_degen=5)
    risk = TokenRisk(rug_risk=0.1, bundler_ratio=0.1, rat_ratio=0.1)
    result = scorer.hard_filter(token, risk)
    assert result.passed


def test_hard_filter_fail_low_liquidity() -> None:
    scorer = AlphaScorer(min_liquidity=50_000.0)
    token = _token("0xa", "A", 1, liquidity=1000.0)
    result = scorer.hard_filter(token, None)
    assert not result.passed
    assert "liquidity" in result.reason


def test_hard_filter_fail_honeypot() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, liquidity=100_000)
    risk = TokenRisk(is_honeypot=True)
    result = scorer.hard_filter(token, risk)
    assert not result.passed
    assert result.reason == "honeypot"


def test_hard_filter_fail_high_rug_risk() -> None:
    scorer = AlphaScorer(max_rug_risk=0.8)
    token = _token("0xa", "A", 1, liquidity=100_000)
    risk = TokenRisk(rug_risk=0.9)
    result = scorer.hard_filter(token, risk)
    assert not result.passed
    assert "rug_risk" in result.reason


def test_hard_filter_fail_bundler_rat() -> None:
    scorer = AlphaScorer(max_bundler_rat_ratio=0.7)
    token = _token("0xa", "A", 1, liquidity=100_000)
    risk = TokenRisk(bundler_ratio=0.5, rat_ratio=0.3)
    result = scorer.hard_filter(token, risk)
    assert not result.passed
    assert "bundler+rat" in result.reason


def test_hard_filter_pass_high_volume_no_smart_degen() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, liquidity=100_000, volume_1m=200_000, smart_degen=0)
    result = scorer.hard_filter(token, None)
    assert result.passed  # no longer rejected, becomes a penalty in score()


def test_score_penalty_high_volume_no_smart_degen() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, volume_1m=200_000, smart_degen=0, liquidity=100_000)
    scored = scorer.score(token, None, None)
    assert scored.breakdown["risk_penalty"] == -10


def test_no_penalty_when_volume_below_threshold() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, volume_1m=50_000, smart_degen=0, liquidity=100_000)
    scored = scorer.score(token, None, None)
    assert scored.breakdown["risk_penalty"] == 0


def test_no_penalty_when_smart_degen_is_none() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, volume_1m=200_000, smart_degen=None, liquidity=100_000)
    scored = scorer.score(token, None, None)
    assert scored.breakdown["risk_penalty"] == 0


def test_no_penalty_when_smart_degen_above_zero() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, volume_1m=200_000, smart_degen=3, liquidity=100_000)
    scored = scorer.score(token, None, None)
    assert scored.breakdown["risk_penalty"] == 0


def test_score_penalty_propagates_to_total() -> None:
    scorer = AlphaScorer(min_liquidity=0)
    token = _token("0xa", "A", 1, volume_1m=200_000, smart_degen=0, liquidity=100_000)
    scored = scorer.score(token, None, None)
    # rank_momentum(10) + volume_quality(15) + structure(10) + risk_penalty(-10) = 25
    assert scored.score == 25


def test_score_new_token() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, volume_1m=5000, smart_degen=5, liquidity=100_000)
    scored = scorer.score(token, None, None)
    assert scored.score > 0
    assert "smart_money" in scored.breakdown
    assert "rank_momentum" in scored.breakdown
    assert scored.breakdown["rank_momentum"] == 10  # new entry bonus


def test_score_rank_surge() -> None:
    scorer = AlphaScorer()
    prev = _token("0xa", "A", 30, volume_1m=5000, smart_degen=5, liquidity=100_000)
    curr = _token("0xa", "A", 1, volume_1m=5000, smart_degen=5, liquidity=100_000)
    scored = scorer.score(curr, prev, None)
    assert scored.breakdown["rank_momentum"] == 20


def test_score_risk_penalty() -> None:
    scorer = AlphaScorer()
    token = _token("0xa", "A", 1, volume_1m=5000, smart_degen=5, liquidity=100_000)
    risk = TokenRisk(rug_risk=0.75)
    scored = scorer.score(token, None, risk)
    assert scored.breakdown["risk_penalty"] == -10


def test_detect_returns_signals() -> None:
    scorer = AlphaScorer(min_liquidity=0)
    prev = _snapshot([_token("0xa", "A", 30, volume_1m=50_000, smart_degen=5, liquidity=100_000)])
    curr = _snapshot([_token("0xa", "A", 1, volume_1m=50_000, smart_degen=10, liquidity=100_000)])
    signals = scorer.detect(prev, curr)
    assert len(signals) > 0
    assert isinstance(signals[0], AlphaSignal)
    assert signals[0].level == "HIGH"


def test_detect_no_prev_returns_empty() -> None:
    scorer = AlphaScorer()
    curr = _snapshot([_token("0xa", "A", 1)])
    signals = scorer.detect(None, curr)
    assert signals == []


def test_detect_filters_low_liquidity() -> None:
    scorer = AlphaScorer(min_liquidity=50_000.0)
    prev = _snapshot([_token("0xa", "A", 1, liquidity=1000.0)])
    curr = _snapshot([_token("0xa", "A", 1, liquidity=1000.0)])
    signals = scorer.detect(prev, curr)
    assert signals == []


def test_detect_low_score_skipped() -> None:
    scorer = AlphaScorer(min_liquidity=0)
    prev = _snapshot([_token("0xa", "A", 50, liquidity=100_000)])
    curr = _snapshot([_token("0xa", "A", 50, liquidity=100_000)])
    signals = scorer.detect(prev, curr)
    assert signals == []


def test_score_volume_acceleration() -> None:
    scorer = AlphaScorer()
    prev = _token("0xa", "A", 1, volume_1m=1000, smart_degen=5, liquidity=100_000)
    curr = _token("0xa", "A", 1, volume_1m=5000, smart_degen=5, liquidity=100_000)
    scored = scorer.score(curr, prev, None)
    assert scored.breakdown["volume_acceleration"] == 15  # 5x > 3x threshold


def test_score_no_volume_accel_without_prev() -> None:
    scorer = AlphaScorer()
    curr = _token("0xa", "A", 1, volume_1m=5000, smart_degen=5, liquidity=100_000)
    scored = scorer.score(curr, None, None)
    assert scored.breakdown["volume_acceleration"] == 0


def test_score_rank_momentum_40_plus() -> None:
    scorer = AlphaScorer()
    prev = _token("0xa", "A", 50, volume_1m=5000, smart_degen=5, liquidity=100_000)
    curr = _token("0xa", "A", 1, volume_1m=5000, smart_degen=5, liquidity=100_000)
    scored = scorer.score(curr, prev, None)
    assert scored.breakdown["rank_momentum"] == 25


def test_detect_custom_thresholds() -> None:
    scorer = AlphaScorer(min_liquidity=0, score_high=50, score_medium=40, score_low=30)
    prev = _snapshot([_token("0xa", "A", 30, volume_1m=50_000, smart_degen=5, liquidity=100_000)])
    curr = _snapshot([_token("0xa", "A", 1, volume_1m=50_000, smart_degen=10, liquidity=100_000)])
    signals = scorer.detect(prev, curr)
    assert len(signals) > 0
    assert signals[0].level == "HIGH"
