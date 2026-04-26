from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.scanner.models import AnomalyEvent, AnomalyType, TrendingToken
from src.scanner.orchestrator import ScannerOrchestrator


@pytest.mark.asyncio
async def test_run_cycle_happy_path() -> None:
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [
        TrendingToken(address="0xa", symbol="A", name="A", price_usd=0.1, rank=1, chain="sol"),
    ]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_detector = MagicMock()
    mock_detector.detect.return_value = []

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"],
        client=mock_client,
        store=mock_store,
        detector=mock_detector,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_client.fetch_trending.assert_called_once_with(chain="sol", interval="1m", limit=50)
    mock_store.save.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_with_anomaly() -> None:
    token = TrendingToken(address="0xa", symbol="A", name="A", price_usd=0.1, rank=1, chain="sol")
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = [token]

    mock_store = MagicMock()
    mock_store.load.return_value = None

    mock_detector = MagicMock()
    mock_detector.detect.return_value = [
        AnomalyEvent(type=AnomalyType.NEW, token=token, chain="sol", reason="new"),
    ]

    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol"],
        client=mock_client,
        store=mock_store,
        detector=mock_detector,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    mock_notifier.send_anomalies.assert_called_once()


@pytest.mark.asyncio
async def test_run_cycle_fetch_failure_skips_chain() -> None:
    mock_client = AsyncMock()
    mock_client.fetch_trending.return_value = []

    mock_store = MagicMock()
    mock_detector = MagicMock()
    mock_notifier = AsyncMock()

    orch = ScannerOrchestrator(
        chains=["sol", "bsc"],
        client=mock_client,
        store=mock_store,
        detector=mock_detector,
        notifier=mock_notifier,
    )
    await orch.run_cycle()

    assert mock_client.fetch_trending.call_count == 2
