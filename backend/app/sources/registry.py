"""Source registry: resolves config, runs enabled sources concurrently, caches.

The cache is keyed on (source, target-url) rather than on the prospect, so
re-running a job -- or two sheets containing the same company -- does not
re-bill the provider.
"""
import asyncio
import logging
from datetime import timedelta

import httpx

from app.core import settings_store
from app.db import mongo
from app.models.common import Identity, utcnow
from app.models.prospect import SourceResult
from app.models.settings import AppSettings
from app.sources.base import SkipSource, SourceConfig, SourceError, failed
from app.sources.linkedin import LinkedInCompanySource, LinkedInProfileSource
from app.sources.news import NewsSource
from app.sources.rss import RssSource
from app.sources.website import WebsiteSource

logger = logging.getLogger(__name__)

ALL_SOURCES: dict[str, object] = {
    source.key: source
    for source in (
        WebsiteSource(),
        RssSource(),
        NewsSource(),
        LinkedInProfileSource(),
        LinkedInCompanySource(),
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
        },
        linkedin_provider=settings.linkedin_provider,
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
    except SourceError as exc:
        return failed(source_key, str(exc), target=target)
    except Exception as exc:  # noqa: BLE001 - one bad source must not kill the row
        logger.exception("Source %s crashed for target %s", source_key, target)
        return failed(source_key, f"Unexpected error: {type(exc).__name__}: {exc}", target=target)

    await _cache_put(source_key, target, result, cfg.cache_ttl_hours)
    return result


async def run_sources(
    identity: Identity,
    source_keys: list[str],
    cfg: SourceConfig,
    use_cache: bool = True,
) -> dict[str, SourceResult]:
    """Run every enabled source for one prospect, concurrently."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=cfg.timeout) as client:
        results = await asyncio.gather(
            *(run_one(key, identity, cfg, client, use_cache) for key in source_keys)
        )

    return {
        result.key: result
        for result in results
        if result is not None
    }
