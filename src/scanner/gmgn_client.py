from __future__ import annotations

import asyncio
import json
import logging

from src.scanner.models import TrendingToken

logger = logging.getLogger(__name__)


class GmgnClient:
    def __init__(
        self,
        gmgn_cli_path: str = "gmgn-cli",
        api_key: str = "",
        cmd_timeout_seconds: float = 30.0,
    ) -> None:
        self._cli_path = gmgn_cli_path
        self._api_key = api_key
        self._timeout = cmd_timeout_seconds

    async def fetch_trending(
        self,
        chain: str,
        interval: str,
        limit: int = 50,
    ) -> list[TrendingToken]:
        cmd = [
            self._cli_path,
            "market",
            "trending",
            "--chain",
            chain,
            "--interval",
            interval,
            "--limit",
            str(limit),
            "--raw",
        ]
        env = {}
        if self._api_key:
            env["GMGN_API_KEY"] = self._api_key

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env or None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            if proc.returncode != 0:
                logger.error("gmgn-cli failed (exit=%d): %s", proc.returncode, stderr.decode())
                return []
        except (TimeoutError, OSError) as e:
            logger.error("gmgn-cli error: %s", e)
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error("gmgn-cli JSON parse error: %s", e)
            return []

        raw_tokens = data.get("data", []) if isinstance(data, dict) else []
        return [
            TrendingToken(
                address=t.get("address", ""),
                symbol=t.get("symbol", ""),
                name=t.get("name", ""),
                price_usd=float(t.get("price_usd", 0) or 0),
                volume_1m=_safe_float(t, "volume_1m"),
                volume_1h=_safe_float(t, "volume_1h"),
                market_cap=_safe_float(t, "market_cap"),
                liquidity=_safe_float(t, "liquidity"),
                smart_degen_count=t.get("smart_degen_count"),
                rank=int(t.get("rank", 0)),
                chain=chain,
            )
            for t in raw_tokens
        ]


def _safe_float(d: dict, key: str) -> float | None:
    val = d.get(key)
    if val is None:
        return None
    return float(val)
