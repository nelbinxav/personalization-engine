"""Blog / news feed for the prospect's own site.

There is rarely an RSS URL in the sheet, so this discovers one from the
homepage via <link rel="alternate">, then falls back to the handful of
conventional paths most CMSs use.
"""
import asyncio

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.models.common import Identity
from app.models.prospect import SourceResult
from app.sources.base import (
    SourceConfig,
    SkipSource,
    failed,
    normalize_url,
    ok,
    request_with_retry,
)

COMMON_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/blog/feed", "/news/feed")
MAX_ENTRIES = 10


class RssSource:
    key = "rss"
    label = "Blog / RSS feed"

    def target(self, identity: Identity) -> str | None:
        return normalize_url(identity.website)

    async def _discover(
        self, site: str, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> str | None:
        try:
            response = await request_with_retry(
                client, "GET", site, timeout=cfg.timeout, attempts=2
            )
        except Exception:  # noqa: BLE001 - discovery is best effort
            return None

        if response.status_code >= 400:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        link = soup.find(
            "link",
            rel=lambda value: value and "alternate" in value,
            type=lambda value: value
            and ("rss" in value or "atom" in value or "xml" in value),
        )
        if link and link.get("href"):
            return httpx.URL(site).join(link["href"]).__str__()

        # No declared feed; probe the usual suspects concurrently.
        async def probe(path: str) -> str | None:
            try:
                candidate = str(httpx.URL(site).join(path))
                head = await client.get(candidate, timeout=10)
                if head.status_code < 400 and "xml" in head.headers.get("content-type", ""):
                    return candidate
            except Exception:  # noqa: BLE001
                return None
            return None

        for result in await asyncio.gather(*(probe(p) for p in COMMON_PATHS)):
            if result:
                return result
        return None

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        site = self.target(identity)
        if not site:
            raise SkipSource("No website on this row")

        feed_url = await self._discover(site, cfg, client)
        if not feed_url:
            return failed(self.key, "No RSS/Atom feed found on this site", site=site)

        response = await request_with_retry(client, "GET", feed_url, timeout=cfg.timeout)
        if response.status_code >= 400:
            return failed(self.key, f"Feed returned HTTP {response.status_code}", url=feed_url)

        # feedparser is sync and CPU-bound on large feeds; keep the loop free.
        parsed = await asyncio.to_thread(feedparser.parse, response.content)
        entries = parsed.entries[:MAX_ENTRIES]
        if not entries:
            return failed(self.key, "Feed contained no entries", url=feed_url)

        lines: list[str] = []
        for entry in entries:
            published = entry.get("published") or entry.get("updated") or "unknown date"
            summary = (entry.get("summary") or "").strip()
            soup_summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
            lines.append(
                f"- {entry.get('title', 'Untitled')} ({published})\n"
                f"  {entry.get('link', '')}\n"
                f"  {soup_summary[:400]}"
            )

        body = f"Recent posts from {feed_url}:\n\n" + "\n".join(lines)
        return ok(self.key, body, cfg, url=feed_url, entry_count=len(entries))
