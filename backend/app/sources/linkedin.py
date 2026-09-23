"""LinkedIn profile and company page.

IMPORTANT CONTEXT FOR WHOEVER MAINTAINS THIS:

Proxycurl -- the obvious choice for years -- was sued by LinkedIn in January
2026 and shut down on 4 July 2026. LinkedIn actively litigates profile
scraping, so treat the vendor here as a moving part, not a fixture.

The provider is therefore pluggable via `settings.linkedin_provider`:

  apify       (default) -- marketplace actors, pay per result
  brightdata            -- dataset API
  scrapin               -- closest drop-in to the old Proxycurl shape
  unipile               -- account-based; uses YOUR LinkedIn session, which
                           trades legal exposure for account-ban risk

Only Apify is implemented. Adding another is a `_fetch_<provider>` function
plus a branch in `_dispatch` -- nothing outside this file changes.
"""
import asyncio
import logging

import httpx

from app.models.common import Identity
from app.models.prospect import SourceResult
from app.sources.base import (
    SourceConfig,
    SourceError,
    SkipSource,
    failed,
    normalize_url,
    ok,
)

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
# Actor ids are configurable because the marketplace churns.
APIFY_PROFILE_ACTOR = "dev_fusion~linkedin-profile-scraper"
APIFY_COMPANY_ACTOR = "dev_fusion~linkedin-company-detail"
APIFY_POLL_SECONDS = 5
APIFY_MAX_WAIT_SECONDS = 180


async def _apify_run(
    client: httpx.AsyncClient, actor: str, payload: dict, token: str
) -> list[dict]:
    """Start an Apify actor and wait for its dataset.

    Apify runs are asynchronous: start, poll status, then read the dataset.
    `waitForFinish` blocks server-side up to 60s, which usually covers it; the
    poll loop handles the slower runs.
    """
    start = await client.post(
        f"{APIFY_BASE}/acts/{actor}/runs",
        params={"token": token, "waitForFinish": 60},
        json=payload,
        timeout=90,
    )
    if start.status_code == 401:
        raise SourceError("Apify rejected the token (401). Check it in Settings.")
    if start.status_code == 404:
        raise SourceError(f"Apify actor '{actor}' not found. It may have been renamed or removed.")
    if start.status_code >= 400:
        raise SourceError(f"Apify returned HTTP {start.status_code}: {start.text[:200]}")

    run = start.json().get("data", {})
    run_id = run.get("id")
    status = run.get("status")
    dataset_id = run.get("defaultDatasetId")

    waited = 0
    while status in ("READY", "RUNNING") and waited < APIFY_MAX_WAIT_SECONDS:
        await asyncio.sleep(APIFY_POLL_SECONDS)
        waited += APIFY_POLL_SECONDS
        poll = await client.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token})
        run = poll.json().get("data", {})
        status = run.get("status")
        dataset_id = run.get("defaultDatasetId") or dataset_id

    if status != "SUCCEEDED":
        raise SourceError(f"Apify run finished with status {status}")
    if not dataset_id:
        raise SourceError("Apify run produced no dataset")

    items = await client.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"},
        timeout=60,
    )
    items.raise_for_status()
    return items.json()


def _render_profile(item: dict) -> str:
    """Flatten a profile record into prose the model can actually use."""
    parts: list[str] = []
    name = item.get("fullName") or item.get("name")
    if name:
        parts.append(f"Name: {name}")
    for label, field in (
        ("Headline", "headline"),
        ("Current position", "jobTitle"),
        ("Company", "companyName"),
        ("Location", "addressWithCountry"),
        ("About", "about"),
    ):
        value = item.get(field)
        if value:
            parts.append(f"{label}: {value}")

    experiences = item.get("experiences") or []
    if experiences:
        lines = [
            f"- {exp.get('title', '')} at {exp.get('subtitle', '')} ({exp.get('caption', '')})"
            for exp in experiences[:5]
        ]
        parts.append("Experience:\n" + "\n".join(lines))

    posts = item.get("updates") or item.get("posts") or []
    if posts:
        lines = [f"- {(post.get('postText') or '')[:300]}" for post in posts[:5]]
        parts.append("Recent activity:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def _render_company(item: dict) -> str:
    parts: list[str] = []
    for label, field in (
        ("Company", "companyName"),
        ("Tagline", "tagline"),
        ("About", "description"),
        ("Industry", "industry"),
        ("Size", "companySize"),
        ("Headquarters", "headquarter"),
        ("Founded", "founded"),
        ("Specialties", "specialities"),
        ("Website", "websiteUrl"),
    ):
        value = item.get(field)
        if value:
            parts.append(f"{label}: {value}")

    updates = item.get("updates") or []
    if updates:
        lines = [f"- {(u.get('text') or '')[:300]}" for u in updates[:5]]
        parts.append("Recent company posts:\n" + "\n".join(lines))

    return "\n\n".join(parts)


class LinkedInProfileSource:
    key = "linkedin_profile"
    label = "LinkedIn profile"

    def target(self, identity: Identity) -> str | None:
        return normalize_url(identity.linkedin_url)

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        url = self.target(identity)
        if not url:
            raise SkipSource("No LinkedIn profile URL on this row")

        if cfg.linkedin_provider != "apify":
            raise SourceError(
                f"LinkedIn provider '{cfg.linkedin_provider}' is selected but not implemented. "
                "Implement it in app/sources/linkedin.py or switch back to 'apify' in Settings."
            )

        token = cfg.require_key("apify", "Apify")
        items = await _apify_run(client, APIFY_PROFILE_ACTOR, {"profileUrls": [url]}, token)
        if not items:
            return failed(self.key, "Apify returned no profile data (profile may be private)", url=url)

        body = _render_profile(items[0])
        if not body.strip():
            return failed(self.key, "Profile record was empty", url=url)
        return ok(self.key, body, cfg, url=url)


class LinkedInCompanySource:
    key = "linkedin_company"
    label = "LinkedIn company page"

    def target(self, identity: Identity) -> str | None:
        return normalize_url(identity.linkedin_company_url)

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        url = self.target(identity)
        if not url:
            raise SkipSource("No LinkedIn company URL on this row")

        if cfg.linkedin_provider != "apify":
            raise SourceError(
                f"LinkedIn provider '{cfg.linkedin_provider}' is selected but not implemented."
            )

        token = cfg.require_key("apify", "Apify")
        items = await _apify_run(client, APIFY_COMPANY_ACTOR, {"companyUrls": [url]}, token)
        if not items:
            return failed(self.key, "Apify returned no company data", url=url)

        body = _render_company(items[0])
        if not body.strip():
            return failed(self.key, "Company record was empty", url=url)
        return ok(self.key, body, cfg, url=url)
