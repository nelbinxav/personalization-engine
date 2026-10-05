"""Recent news about the prospect's company.

Serper.dev (Google News as JSON) when a key is configured; otherwise, or when
Serper refuses the key, Exa's free search. The query is built from the company
name rather than the person, because company-level news is what makes a useful
outreach hook.
"""
import logging

import httpx

from app.sources import exa

from app.models.common import Identity
from app.models.prospect import SourceResult
from app.sources.base import (
    SourceConfig,
    SourceRateLimited,
    SkipSource,
    failed,
    ok,
    request_with_retry,
)

logger = logging.getLogger(__name__)

SERPER_ENDPOINT = "https://google.serper.dev/news"
MAX_RESULTS = 8


class NewsSource:
    key = "news"
    label = "News"

    def target(self, identity: Identity) -> str | None:
        return identity.company

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        company = self.target(identity)
        if not company:
            raise SkipSource("No company name on this row")

        api_key = cfg.key("serper")
        if not api_key:
            return await self._from_exa(company, cfg, client)

        response = await request_with_retry(
            client,
            "POST",
            SERPER_ENDPOINT,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": company, "num": MAX_RESULTS},
            timeout=cfg.timeout,
        )

        if response.status_code in (401, 403):
            # A dead key should not cost the row its news: use the free search.
            logger.warning("Serper rejected the API key (%s); using Exa", response.status_code)
            return await self._from_exa(company, cfg, client)
        if response.status_code == 429:
            raise SourceRateLimited("Serper rate limit hit.")
        if response.status_code >= 400:
            return failed(self.key, f"Serper returned HTTP {response.status_code}")

        payload = response.json()
        articles = payload.get("news", [])[:MAX_RESULTS]
        if not articles:
            return failed(self.key, f"No recent news found for '{company}'", query=company)

        lines = [
            f"- {item.get('title', 'Untitled')} ({item.get('date', 'undated')}"
            f" - {item.get('source', 'unknown source')})\n"
            f"  {item.get('link', '')}\n"
            f"  {(item.get('snippet') or '').strip()}"
            for item in articles
        ]
        body = f"Recent news for {company}:\n\n" + "\n".join(lines)
        return ok(self.key, body, cfg, query=company, result_count=len(articles))

    async def _from_exa(
        self, company: str, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        text = await exa.company_news(client, company, cfg.key("exa"))
        if not text or text.lower().startswith("no "):
            return failed(self.key, f"No recent news found for '{company}'", query=company)
        return ok(self.key, f"Recent news for {company}:\n\n{text}", cfg, query=company, via="exa")
