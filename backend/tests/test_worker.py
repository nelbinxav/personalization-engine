"""Worker pieces that do not need Redis or Mongo: retry pacing and the
concurrency limiter."""
import asyncio

from app.worker.limiter import MAX_CONCURRENCY, RowLimiter
from app.worker.tasks import MAX_TRIES, retry_delay


def test_retry_delay_grows_and_respects_the_providers_wait():
    delays = [retry_delay(attempt) for attempt in range(1, MAX_TRIES)]
    assert delays == sorted(delays) and delays[0] == 30
    # Never sooner than the provider asked, never an unbounded wait.
    assert retry_delay(1, retry_after=120) == 120
    assert retry_delay(1, retry_after=86_400) == 900


def test_limiter_never_runs_more_rows_than_the_setting():
    async def scenario() -> int:
        async def limit() -> int:
            return 3

        limiter = RowLimiter(limit)
        peak = 0

        async def row() -> None:
            nonlocal peak
            async with limiter.slot():
                peak = max(peak, limiter.active)
                await asyncio.sleep(0.01)

        await asyncio.gather(*(row() for _ in range(12)))
        assert limiter.active == 0
        return peak

    assert asyncio.run(scenario()) == 3


def test_limiter_releases_its_slot_when_a_row_raises():
    async def scenario() -> int:
        async def limit() -> int:
            return 1

        limiter = RowLimiter(limit)
        try:
            async with limiter.slot():
                raise RuntimeError("row failed")
        except RuntimeError:
            pass
        return limiter.active

    assert asyncio.run(scenario()) == 0


def test_limiter_clamps_a_bad_setting():
    async def scenario() -> tuple[int, int]:
        async def zero() -> int:
            return 0

        async def huge() -> int:
            return 10_000

        return await RowLimiter(zero).limit(), await RowLimiter(huge).limit()

    assert asyncio.run(scenario()) == (1, MAX_CONCURRENCY)
