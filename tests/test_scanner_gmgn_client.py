from __future__ import annotations

import json
import pathlib

import pytest
from src.scanner.gmgn_client import GmgnClient


def _echo_bat(tmp_path: pathlib.Path, content: str) -> str:
    script = tmp_path / "_gmgn_echo.bat"
    script.write_text(f"@echo {content}", encoding="ascii")
    return str(script)


def _bat_that_sleeps(tmp_path: pathlib.Path, seconds: int) -> str:
    script = tmp_path / "_gmgn_sleep.bat"
    script.write_text(f"@ping -n {seconds + 1} 127.0.0.1 > nul", encoding="ascii")
    return str(script)


@pytest.mark.asyncio
async def test_fetch_trending_parses_json(tmp_path: pathlib.Path) -> None:
    fake_output = json.dumps(
        {
            "data": [
                {
                    "address": "0xabc",
                    "symbol": "TEST",
                    "name": "Test Token",
                    "price_usd": "0.123",
                    "volume_1m": "45000",
                    "volume_1h": "500000",
                    "market_cap": "1000000",
                    "liquidity": "500000",
                    "smart_degen_count": 12,
                    "rank": 1,
                }
            ]
        }
    )
    client = GmgnClient(gmgn_cli_path=_echo_bat(tmp_path, fake_output))
    tokens = await client.fetch_trending(chain="sol", interval="1m", limit=50)
    assert len(tokens) == 1
    t = tokens[0]
    assert t.symbol == "TEST"
    assert t.price_usd == 0.123
    assert t.volume_1m == 45000.0
    assert t.rank == 1
    assert t.chain == "sol"


@pytest.mark.asyncio
async def test_fetch_trending_empty_data(tmp_path: pathlib.Path) -> None:
    fake_output = json.dumps({"data": []})
    client = GmgnClient(gmgn_cli_path=_echo_bat(tmp_path, fake_output))
    tokens = await client.fetch_trending(chain="sol", interval="1m", limit=50)
    assert tokens == []


@pytest.mark.asyncio
async def test_fetch_trending_timeout_returns_empty(tmp_path: pathlib.Path) -> None:
    client = GmgnClient(
        gmgn_cli_path=_bat_that_sleeps(tmp_path, 10),
        cmd_timeout_seconds=0.001,
    )
    tokens = await client.fetch_trending(chain="sol", interval="1m", limit=50)
    assert tokens == []
