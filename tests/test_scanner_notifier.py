from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.scanner.models import AnomalyEvent, AnomalyType, TrendingToken
from src.scanner.notifier import TelegramNotifier


@pytest.mark.asyncio
async def test_send_anomalies_success() -> None:
    token = TrendingToken(
        address="0xabc123",
        symbol="TEST",
        name="Test Token",
        price_usd=0.123,
        volume_1m=45000.0,
        smart_degen_count=12,
        market_cap=1_000_000.0,
        rank=1,
        chain="sol",
    )
    event = AnomalyEvent(
        type=AnomalyType.NEW,
        token=token,
        chain="sol",
        reason="New token on 1m trending",
    )

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        notifier = TelegramNotifier(bot_token="fake:token", chat_id="123")
        await notifier.send_anomalies("sol", "1m", [event])

    assert mock_client.post.called
    call_kwargs = mock_client.post.call_args[1]
    assert "chat_id" in call_kwargs["json"]


@pytest.mark.asyncio
async def test_send_anomalies_empty_does_nothing() -> None:
    notifier = TelegramNotifier(bot_token="fake", chat_id="123")
    await notifier.send_anomalies("sol", "1m", [])
