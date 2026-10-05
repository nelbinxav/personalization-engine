"""Caps how many rows run at once.

arq's own `max_jobs` is fixed when the worker starts, so it is set to the
ceiling and the real limit is enforced here from the Concurrency setting,
re-read while a job runs. Changing it in Settings takes effect within seconds,
with no restart. There is one worker process, so an in-process counter is
enough.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

from app.core import settings_store

# The most the Concurrency setting can ask for.
MAX_CONCURRENCY = 32
# arq's max_jobs. Far above MAX_CONCURRENCY on purpose: a research task spends
# most of its life waiting for its turn on LinkedIn, which costs nothing, and a
# low ceiling would let those waiting rows keep arq from starting others.
ARQ_MAX_JOBS = 400
_REFRESH_SECONDS = 10
_POLL_SECONDS = 0.25


async def _configured_limit() -> int:
    return (await settings_store.load()).concurrency


class RowLimiter:
    def __init__(self, read_limit: Callable[[], Awaitable[int]] = _configured_limit) -> None:
        self._read_limit = read_limit
        self._limit = 1
        self._read_at = 0.0
        self.active = 0

    async def limit(self) -> int:
        if time.monotonic() - self._read_at >= _REFRESH_SECONDS or not self._read_at:
            try:
                self._limit = max(1, min(int(await self._read_limit()), MAX_CONCURRENCY))
            except Exception:  # noqa: BLE001 - keep the last known limit if the read fails
                pass
            self._read_at = time.monotonic()
        return self._limit

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        while True:
            limit = await self.limit()
            # No await between the check and the increment, so two waiters
            # cannot both take the last slot.
            if self.active < limit:
                self.active += 1
                break
            await asyncio.sleep(_POLL_SECONDS)
        try:
            yield
        finally:
            self.active -= 1


rows = RowLimiter()
