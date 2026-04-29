from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from src.scanner.models import TokenRisk, TrendingToken
from src.shared.resilience.executor import ResilienceConfig, ResilientExecutor

logger = logging.getLogger(__name__)


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))

    async def run(self, coro_factory):
        async with self._semaphore:
            return await coro_factory()


class GmgnClient:
    def __init__(
        self,
        gmgn_cli_path: str = "gmgn-cli",
        api_key: str = "",
        trending_timeout_seconds: float = 30.0,
        security_timeout_seconds: float = 15.0,
        rate_limit_per_second: float = 2.0,
        rate_limit_capacity: int = 5,
        circuit_failure_threshold: int = 5,
        circuit_recovery_seconds: float = 30.0,
        circuit_half_open_max_calls: int = 2,
        retry_attempts: int = 3,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 30.0,
        security_max_concurrency: int = 5,
    ) -> None:
        self._cli_path = gmgn_cli_path
        self._api_key = api_key
        self._trending_timeout = trending_timeout_seconds
        self._security_timeout = security_timeout_seconds

        def _is_retryable(e: Exception) -> bool:
            return isinstance(e, TimeoutError | OSError)

        base_config = ResilienceConfig(
            rate_limit_per_second=rate_limit_per_second,
            rate_limit_capacity=rate_limit_capacity,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_recovery_seconds=circuit_recovery_seconds,
            circuit_half_open_max_calls=circuit_half_open_max_calls,
            retry_attempts=retry_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
            backoff_base_seconds=retry_base_seconds,
            backoff_max_seconds=retry_max_seconds,
        )
        self._trending_executor = ResilientExecutor(
            name="gmgn_trending",
            config=base_config,
            is_retryable=_is_retryable,
        )
        self._security_executor = ResilientExecutor(
            name="gmgn_security",
            config=base_config,
            is_retryable=_is_retryable,
        )
        self._concurrency_limiter = ConcurrencyLimiter(max_concurrent=security_max_concurrency)

    async def fetch_trending(
        self,
        chain: str,
        interval: str,
        limit: int = 50,
    ) -> list[TrendingToken]:
        return await self._trending_executor.execute(
            lambda: self._do_fetch_trending(chain, interval, limit)
        )

    async def _do_fetch_trending(
        self,
        chain: str,
        interval: str,
        limit: int,
    ) -> list[TrendingToken]:
        env = dict(os.environ)
        if self._api_key:
            env["GMGN_API_KEY"] = self._api_key

        try:
            if sys.platform == "win32":
                args = (
                    f"{self._cli_path} market trending"
                    f" --chain {chain} --interval {interval}"
                    f" --limit {limit} --raw"
                )
                proc = await asyncio.create_subprocess_shell(
                    args,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
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
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._trending_timeout
            )
            if proc.returncode != 0:
                logger.error(
                    "gmgn-cli failed (exit=%d) stderr=%s stdout=%s",
                    proc.returncode,
                    stderr.decode()[:500],
                    stdout.decode()[:500],
                )
                return []
        except (TimeoutError, OSError) as e:
            logger.error("gmgn-cli error: %s", e)
            raise

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error("gmgn-cli JSON parse error: %s (stdout=%s)", e, stdout.decode()[:500])
            return []

        inner = data.get("data", {}) if isinstance(data, dict) else data
        if isinstance(inner, list):
            raw_tokens = inner
        elif isinstance(inner, dict):
            raw_tokens = next((v for v in inner.values() if isinstance(v, list)), [])
        else:
            raw_tokens = []
        if not isinstance(raw_tokens, list):
            logger.warning("gmgn-cli unexpected data format")
            return []
        result: list[TrendingToken] = []
        for t in raw_tokens:
            if not isinstance(t, dict):
                logger.warning("gmgn-cli skipping non-dict token: %s", type(t).__name__)
                continue
            result.append(
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
            )
        return result

    async def fetch_token_security(self, chain: str, address: str) -> TokenRisk | None:
        return await self._concurrency_limiter.run(
            lambda: self._security_executor.execute(
                lambda: self._do_fetch_token_security(chain, address)
            )
        )

    async def _do_fetch_token_security(self, chain: str, address: str) -> TokenRisk | None:
        cmd = [
            self._cli_path,
            "token",
            "security",
            "--chain",
            chain,
            "--address",
            address,
            "--raw",
        ]
        env = dict(os.environ)
        if self._api_key:
            env["GMGN_API_KEY"] = self._api_key
        try:
            if sys.platform == "win32":
                args = " ".join(cmd)
                proc = await asyncio.create_subprocess_shell(
                    args,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._security_timeout
            )
            if proc.returncode != 0:
                logger.error(
                    "gmgn-cli security failed (exit=%d) stderr=%s",
                    proc.returncode,
                    stderr.decode()[:500],
                )
                return None
            data = json.loads(stdout)
            inner = data.get("data", {}) if isinstance(data, dict) else data
            if not isinstance(inner, dict):
                return None
            return TokenRisk(
                rug_risk=float(inner.get("rug_risk", 0) or 0),
                is_honeypot=bool(inner.get("is_honeypot", False)),
                bundler_ratio=float(inner.get("bundler_trader_amount_rate", 0) or 0),
                rat_ratio=float(inner.get("rat_trader_amount_rate", 0) or 0),
                sniper_count=int(inner.get("sniper_count", 0) or 0),
                top10_holder_pct=float(inner.get("top10_holder_rate", 0) or 0),
            )
        except (json.JSONDecodeError, TimeoutError, OSError) as e:
            logger.warning("fetch_token_security failed for %s: %s", address, e)
            raise


def _safe_float(d: dict, key: str) -> float | None:
    val = d.get(key)
    if val is None:
        return None
    return float(val)
