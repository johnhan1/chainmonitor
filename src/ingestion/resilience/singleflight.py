from __future__ import annotations

import asyncio


class SingleFlightGroup:
    def __init__(self) -> None:
        self._inflight_requests: dict[str, asyncio.Future[dict | None]] = {}
        self._inflight_lock = asyncio.Lock()

    async def acquire(self, key: str) -> tuple[asyncio.Future[dict | None], bool]:
        async with self._inflight_lock:
            holder = self._inflight_requests.get(key)
            if holder is not None:
                return holder, False
            loop = asyncio.get_running_loop()
            holder = loop.create_future()
            self._inflight_requests[key] = holder
            return holder, True

    async def release(self, key: str, holder: asyncio.Future[dict | None]) -> None:
        async with self._inflight_lock:
            current = self._inflight_requests.get(key)
            if current is holder:
                self._inflight_requests.pop(key, None)
