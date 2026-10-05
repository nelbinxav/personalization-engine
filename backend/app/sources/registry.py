"""Source registry: resolves config, runs sources as a funnel, caches.

The cache is keyed on (source, target-url) rather than on the prospect, so
re-running a job -- or two sheets containing the same company -- does not
re-bill the provider.
"""
import asyncio
import logging
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import AsyncIterator, Callable

import httpx

from app.core import settings_store
from app.core.config import get_settings
from app.db import mongo
from app.models.common import Identity, utcnow
from app.models.prospect import SourceResult
from app.models.settings import AppSettings
from app.sources.base import (
    SkipSource,
    SourceBusy,
    SourceConfig,
    SourceDailyLimit,
    SourceError,
    SourceRateLimited,
    failed,
)
from app.sources.exa import PodcastSource
from app.sources.linkedin import (
    LinkedInCompanySource,
    LinkedInPostsSource,
    LinkedInProfileSource,
)
from app.sources.news import NewsSource
from app.sources.rss import RssSource
from app.sources.website import WebsiteSource

logger = logging.getLogger(__name__)

# In priority order: the best material for an opener comes first. The chain
# shows research to the model in this order and the angle prompt ranks by it,
# so a recent post beats a podcast, which beats a profile, and so on down to
# the company's own website.
ALL_SOURCES: dict[str, object] = {
    source.key: source
    for source in (
        LinkedInPostsSource(),
        PodcastSource(),
        LinkedInProfileSource(),
        LinkedInCompanySource(),
        NewsSource(),
        WebsiteSource(),
        RssSource(),
    )
}


def source_catalog() -> list[dict]:
    """Describe available sources for the settings and job-launch UI."""
    return [{"key": key, "label": source.label} for key, source in ALL_SOURCES.items()]


async def build_config(settings: AppSettings | None = None) -> SourceConfig:
    settings = settings or await settings_store.load()
    return SourceConfig(
        keys={
            "jina": await settings_store.provider_key("jina"),
            "serper": await settings_store.provider_key("serper"),
            "apify": await settings_store.provider_key("apify"),
            "exa": await settings_store.provider_key("exa"),
        },
        linkedin_provider=settings.linkedin_provider,
        linkedin_mcp_url=get_settings().linkedin_mcp_url,
        linkedin_daily_limit=settings.linkedin_daily_limit,
        linkedin_reads_per_hour=settings.linkedin_reads_per_hour,
    )


async def _cache_get(source_key: str, cache_key: str) -> SourceResult | None:
    doc = await mongo.source_cache().find_one({"source": source_key, "cache_key": cache_key})
    if not doc:
        return None
    result = SourceResult.model_validate(doc["result"])
    result.from_cache = True
    return result


async def _cache_put(source_key: str, cache_key: str, result: SourceResult, ttl_hours: int) -> None:
    # Only cache successes. A transient failure should not be pinned for a week.
    if not result.ok:
        return
    await mongo.source_cache().update_one(
        {"source": source_key, "cache_key": cache_key},
        {
            "$set": {
                "source": source_key,
                "cache_key": cache_key,
                "result": result.model_dump(mode="json"),
                "expires_at": utcnow() + timedelta(hours=ttl_hours),
            }
        },
        upsert=True,
    )


async def run_one(
    source_key: str,
    identity: Identity,
    cfg: SourceConfig,
    client: httpx.AsyncClient,
    use_cache: bool = True,
) -> SourceResult | None:
    """Run a single source. Returns None when the source does not apply."""
    source = ALL_SOURCES.get(source_key)
    if source is None:
        return failed(source_key, f"Unknown source '{source_key}'")

    target = source.target(identity)
    if not target:
        # Nothing to fetch -- an absence, not a failure. Omitted from the row.
        return None

    if use_cache:
        cached = await _cache_get(source_key, target)
        if cached:
            return cached

    try:
        result = await source.fetch(identity, cfg, client)
    except SkipSource:
        return None
    except SourceBusy as exc:
        # Not now, and the caller will not wait: it is picked up later.
        return failed(source_key, str(exc), target=target, later=True)
    except SourceRateLimited as exc:
        # Marked so the worker can put the row back in the queue for later.
        return failed(source_key, str(exc), target=target, rate_limited=True)
    except SourceDailyLimit as exc:
        # Marked so the worker can pause the whole job until tomorrow.
        return failed(source_key, str(exc), target=target, daily_limit=True)
    except SourceError as exc:
        return failed(source_key, str(exc), target=target)
    except Exception as exc:  # noqa: BLE001 - one bad source must not kill the row
        logger.exception("Source %s crashed for target %s", source_key, target)
        return failed(source_key, f"Unexpected error: {type(exc).__name__}: {exc}", target=target)

    ttl_hours = getattr(source, "cache_ttl_hours", cfg.cache_ttl_hours)
    await _cache_put(source_key, target, result, ttl_hours)
    return result


# The two hooks worth stopping for, in order. A recent post ends the research
# for that prospect; failing that, a podcast or interview does.
_PERSON_KEYS = ("linkedin_posts", "linkedin_profile")
_FALLBACK_KEYS = ("news", "website", "rss")
# Upper bound on one step's own work. Waiting for a turn on LinkedIn is not
# work and is not timed: at a careful pace it can take hours.
STEP_TIMEOUT = 5 * 60


@asynccontextmanager
async def _no_limit() -> AsyncIterator[None]:
    yield


def for_later(result: SourceResult) -> bool:
    """A result that is not an answer, only "not now"."""
    return any(result.meta.get(flag) for flag in ("later", "daily_limit", "rate_limited"))


async def run_funnel(
    identity: Identity,
    source_keys: list[str],
    cfg: SourceConfig,
    use_cache: bool = True,
    busy: Callable[[], AbstractAsyncContextManager] = _no_limit,
) -> tuple[dict[str, SourceResult], list[str]]:
    """Research one prospect, stopping at the first thing worth opening with.
    Returns (results, the LinkedIn sources left for the background check).

      1. The prospect's LinkedIn, if it can be read this instant: a recent
         post ends it. Their profile comes from the same read.
      2. Podcasts and interviews: one found ends it.
      3. News, website and blog feed together: anything found ends it.
      4. The company's LinkedIn page, only when nothing else turned up and it
         can be read this instant.

    Nothing here waits. LinkedIn is read slowly on purpose, and the free web
    search has a daily allowance; a source that cannot answer this instant is
    returned as pending and the prospect is researched from the rest now.
    `linkedin_backfill` fetches the pending ones when they become available and
    adds them to the row. Only the sources in
    `source_keys` are used. `busy` wraps the fetches so the caller can cap how
    many run at once.
    """
    cfg = replace(cfg, linkedin_wait=False)
    pending: list[str] = []
    wanted = [key for key in ALL_SOURCES if key in source_keys]
    results: dict[str, SourceResult] = {}

    async with httpx.AsyncClient(follow_redirects=True, timeout=cfg.timeout) as client:

        async def fetch(keys: list[str], limited: bool = True) -> None:
            async def one(key: str) -> SourceResult | None:
                try:
                    if not limited:
                        return await run_one(key, identity, cfg, client, use_cache)
                    async with busy():
                        return await asyncio.wait_for(
                            run_one(key, identity, cfg, client, use_cache), STEP_TIMEOUT
                        )
                except asyncio.TimeoutError:
                    return failed(key, f"Took longer than {STEP_TIMEOUT // 60} minutes")

            for result in await asyncio.gather(*(one(key) for key in keys)):
                if result is None:
                    continue
                if for_later(result):
                    # Not an answer, only "not now" (LinkedIn between reads, a
                    # search allowance used up). The background check gets it.
                    pending.append(result.key)
                else:
                    results[result.key] = result

        def found(*keys: str) -> bool:
            return any(key in results and results[key].ok for key in keys)

        podcasts = (
            asyncio.ensure_future(fetch(["podcasts"])) if "podcasts" in wanted else None
        )
        try:
            await fetch([key for key in _PERSON_KEYS if key in wanted], limited=False)
            if found("linkedin_posts"):
                # A recent post is the opener. The podcast search, finished or
                # not, is dropped so the model reads only what it will use.
                results.pop("podcasts", None)
                return results, pending
            if podcasts is not None:
                await podcasts
                podcasts = None
            if found("podcasts"):
                return results, pending
        finally:
            if podcasts is not None:
                podcasts.cancel()
                await asyncio.gather(podcasts, return_exceptions=True)
                results.pop("podcasts", None)

        await fetch([key for key in _FALLBACK_KEYS if key in wanted])
        if found(*_FALLBACK_KEYS):
            return results, pending

        if "linkedin_company" in wanted:
            await fetch(["linkedin_company"], limited=False)
            # A last resort that is not available right now is just skipped.
            if "linkedin_company" in pending:
                pending.remove("linkedin_company")
        return results, pending
