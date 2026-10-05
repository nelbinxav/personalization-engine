"""Web search through Exa's hosted MCP endpoint, which needs no API key.

Used for two things a scrape of the prospect's own site cannot find: podcast
and interview appearances, and news when no Serper key is configured. This is
the search backend Agent Reach routes to.
"""
import asyncio
import re
import time
from datetime import datetime, timezone

import httpx

from app.models.common import Identity
from app.models.prospect import SourceResult
from app.sources.base import (
    SkipSource,
    SourceConfig,
    SourceDailyLimit,
    SourceRateLimited,
    failed,
    ok,
)
from app.sources.mcp_http import call_tool, tool_text

EXA_MCP_URL = "https://mcp.exa.ai/mcp"
_gate = asyncio.Semaphore(2)
_RETRY_WAITS = (3, 8, 20)
# Wall-clock time until which the free endpoint has said its allowance is gone.
_blocked_until = 0.0


def blocked() -> bool:
    """True while the free allowance is known to be used up."""
    return time.time() < _blocked_until


def _quota_error() -> SourceDailyLimit:
    resets = datetime.fromtimestamp(_blocked_until, timezone.utc).strftime("%H:%M")
    return SourceDailyLimit(
        f"The free web search allowance is used up until {resets} UTC. It is tried again "
        "then; an Exa API key in Settings removes the limit."
    )


async def search(
    client: httpx.AsyncClient,
    query: str,
    objective: str,
    *,
    results: int = 5,
    timeout: float = 45,
    api_key: str | None = None,
) -> str:
    """Search and return Exa's text block of titles, URLs, dates and highlights.

    Without a key this is Exa's free endpoint, which has a small daily
    allowance and refuses bursts. So searches go two at a time, a short refusal
    is retried, and once the day's allowance is gone every further search fails
    at once (no request is sent) until it resets: research must not sit waiting
    on a source that will not answer for hours.
    """
    global _blocked_until
    if not api_key and blocked():
        raise _quota_error()

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    async with _gate:
        for wait in (*_RETRY_WAITS, None):
            if not api_key and blocked():
                raise _quota_error()
            try:
                result = await call_tool(
                    client,
                    EXA_MCP_URL,
                    "web_search_exa",
                    {"query": query, "objective": objective, "numResults": results},
                    timeout=timeout,
                    # Exa answers a bare call, so skip the two handshake round trips.
                    handshake=False,
                    extra_headers=headers,
                )
                return tool_text(result)
            except SourceRateLimited as exc:
                retry_after = getattr(exc, "retry_after", None)
                if retry_after and retry_after > _RETRY_WAITS[-1] * 3:
                    # Not a burst: the allowance itself. Remember when it resets.
                    _blocked_until = time.time() + retry_after
                    raise _quota_error() from exc
                if wait is None:
                    raise
                await asyncio.sleep(wait)
    return ""


def person_name(identity: Identity) -> str | None:
    if identity.full_name:
        return identity.full_name.strip() or None
    parts = [p.strip() for p in (identity.first_name, identity.last_name) if p and p.strip()]
    # A first name alone matches thousands of people.
    return " ".join(parts) if len(parts) == 2 else None


_COMPANY_SUFFIX = re.compile(
    r"\b(?:inc|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|pvt|private)\b\.?", re.IGNORECASE
)


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# What makes a result an appearance rather than a page about the person.
_APPEARANCE = re.compile(
    r"\b(?:podcast|episode|interview(?:ed|s)?|webinar|fireside|keynote|panel(?:ist)?)\b", re.IGNORECASE
)
# Profile and directory pages name the person and the company, and say nothing.
_PROFILE_HOSTS = (
    "linkedin.com", "theorg.com", "humantic.ai", "neuron.com", "zoominfo.com", "rocketreach.co",
    "apollo.io", "crunchbase.com", "signalhire.com", "contactout.com",
)


def matching_results(text: str, name: str, company: str) -> list[str]:
    """The search results that are an appearance by this person at this company:
    they name both, mention a podcast, interview, webinar or panel, and are not
    a profile page."""
    person = _plain(name)
    firm = _plain(_COMPANY_SUFFIX.sub(" ", company))
    if not person or not firm:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*---\s*\n", text) if block.strip()]
    kept = []
    for block in blocks:
        plain = f" {_plain(block)} "
        url = re.search(r"^URL:\s*(\S+)", block, re.MULTILINE)
        if url and any(host in url.group(1).lower() for host in _PROFILE_HOSTS):
            continue
        if f" {person} " in plain and f" {firm} " in plain and _APPEARANCE.search(block):
            kept.append(block)
    return kept


class PodcastSource:
    key = "podcasts"
    label = "Podcasts and interviews"

    def target(self, identity: Identity) -> str | None:
        name = person_name(identity)
        if not name or not identity.company:
            return None
        return f"{name} | {identity.company.strip()}"

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        name = person_name(identity)
        company = (identity.company or "").strip()
        if not name or not company:
            raise SkipSource("Needs the person's full name and company")

        role = f", {identity.title}" if identity.title else ""
        text = await search(
            client,
            f"podcast episode or interview with {name}{role} at {company}",
            f"Podcast episodes, interviews, panels or webinars where {name} of {company} is the "
            "guest or a speaker. Newest first. Exclude pages about a different person with the "
            "same name, and pages that only mention them in passing.",
            api_key=cfg.key("exa"),
        )
        # A search for a name always returns something, usually other people
        # who share it. Only a result naming this person AND this company is a
        # find; without that test the funnel would stop here for everyone.
        matches = matching_results(text, name, company)
        if not matches:
            return failed(
                self.key, f"No podcast or interview naming {name} at {company}", query=name
            )

        body = (
            f"Podcast and interview appearances by {name} ({company}), from a web search.\n\n"
            + "\n\n---\n\n".join(matches)
        )
        return ok(self.key, body, cfg, query=name, result_count=len(matches))


async def company_news(client: httpx.AsyncClient, company: str, api_key: str | None = None) -> str:
    return await search(
        client,
        f"recent news and press releases about the company {company}",
        f"News articles and press releases about {company} from the last three months, newest "
        "first, each with its publication date. Exclude product pages, job listings and "
        "companies with a similar name.",
        api_key=api_key,
    )
