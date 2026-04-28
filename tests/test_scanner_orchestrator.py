from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.scanner.models import (
    AlphaSignal,
    FilterResult,
    ScoredToken,
    TrendingToken,
)
from src.scanner.orchestrator import ScannerOrchestrator


def _make_token(address: str = "0xa") -> TrendingToken:
    return TrendingToken(
        address=address,
        symbol="A",
        name="A",
        price_usd=0.1,
        rank=1,
        chain="sol",
    )


def _make_signal(token: TrendingToken, level: str = "HIGH") -> AlphaSignal:
    scored = ScoredToken(token=token, score=80, breakdown={"smart_money": 30})
    return AlphaSignal(
        token=scored,
        level=level,
        chain=token.chain,
        interval="1m",
        detected_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_run_cycle_happy_path() -> None:
    token = _make_token()
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_scorer = MagicMock()
    mock_scorer.detect.return_value = []
    mock_scorer.hard_filter.return_value = FilterResult(passed=True)
    mock_scorer.score.return_value = ScoredToken(token=token, score=50, breakdown={})

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"],
        client=mock_client,
        store=mock_store,
        scorer=mock_scorer,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_client.fetch_trending.assert_called_once_with(chain="sol", interval="1m", limit=50)
    mock_store.save.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_with_alpha_signal() -> None:
    token = _make_token()
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_scorer = MagicMock()
    mock_scorer.detect.return_value = [_make_signal(token)]
    mock_scorer.hard_filter.return_value = FilterResult(passed=True)
    mock_scorer.score.return_value = ScoredToken(
        token=token, score=80, breakdown={"smart_money": 30}
    )

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"],
        client=mock_client,
        store=mock_store,
        scorer=mock_scorer,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_notifier.send_alpha.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_fetch_failure_skips_chain() -> None:
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = []

    mock_store = MagicMock()
    mock_scorer = MagicMock()
    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol", "bsc"],
        client=mock_client,
        store=mock_store,
        scorer=mock_scorer,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    assert mock_client.fetch_trending.call_count == 2


@pytest.mark.asyncio
async def test_run_cycle_emits_events() -> None:
    token = _make_token()
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_scorer = MagicMock()
    mock_scorer.detect.return_value = [_make_signal(token)]
    mock_scorer.hard_filter.return_value = FilterResult(passed=True)
    mock_scorer.score.return_value = ScoredToken(
        token=token, score=80, breakdown={"smart_money": 30}
    )

    mock_notifier = AsyncMock()

    from src.scanner.events import (
        ChainScanCompleted,
        ChainScanStarted,
        EventBus,
        SignalEmitted,
        TokenFiltered,
        TokenScored,
        TrendingFetched,
    )

    received: list[object] = []
    bus = EventBus()
    bus.subscribe(ChainScanStarted, received.append)
    bus.subscribe(TrendingFetched, received.append)
    bus.subscribe(TokenFiltered, received.append)
    bus.subscribe(TokenScored, received.append)
    bus.subscribe(SignalEmitted, received.append)
    bus.subscribe(ChainScanCompleted, received.append)

    orch = ScannerOrchestrator(
        chains=["sol"],
        client=mock_client,
        store=mock_store,
        scorer=mock_scorer,
        notifier=mock_notifier,
        event_bus=bus,
    )
    await orch.run_cycle()

    event_types = [type(e).__name__ for e in received]
    assert "ChainScanStarted" in event_types
    assert "TrendingFetched" in event_types
    assert "TokenFiltered" in event_types
    assert "TokenScored" in event_types
    assert "SignalEmitted" in event_types
    assert "ChainScanCompleted" in event_types
