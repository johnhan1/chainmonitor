from __future__ import annotations

import asyncio

import pytest
from src.shared.resilience.rate_limiter import AsyncTokenBucket, RateLimiterRegistry


@pytest.mark.asyncio
async def test_token_bucket_allows_immediate_acquisition() -> None:
    bucket = AsyncTokenBucket(rate_per_second=100.0, capacity=10)
    await bucket.acquire()
    assert True


@pytest.mark.asyncio
async def test_token_bucket_blocks_when_empty() -> None:
    bucket = AsyncTokenBucket(rate_per_second=1.0, capacity=1)
    await bucket.acquire()
    t0 = asyncio.get_running_loop().time()
    await asyncio.wait_for(bucket.acquire(), timeout=2.0)
    elapsed = asyncio.get_running_loop().time() - t0
    assert elapsed > 0.5


@pytest.mark.asyncio
async def test_rate_limiter_registry_returns_singleton() -> None:
    b1 = RateLimiterRegistry.get_bucket(name="test", rate_per_second=10.0, capacity=5)
    b2 = RateLimiterRegistry.get_bucket(name="test", rate_per_second=10.0, capacity=5)
    assert b1 is b2


@pytest.mark.asyncio
async def test_rate_limiter_registry_different_names() -> None:
    b1 = RateLimiterRegistry.get_bucket(name="alpha", rate_per_second=10.0, capacity=5)
    b2 = RateLimiterRegistry.get_bucket(name="beta", rate_per_second=10.0, capacity=5)
    assert b1 is not b2
