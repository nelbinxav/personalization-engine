"""Recent news about the prospect's company via Serper.dev.

Serper is the cheapest way to get Google News results as JSON. The query is
built from the company name rather than the person, because company-level news
is what makes a useful outreach hook.
"""
import httpx

from app.models.common import Identity
from app.models.prospect import SourceResult
from app.sources.base import (
    SourceConfig,
    SkipSource,
    failed,
    ok,
    request_with_retry,
)

SERPER_ENDPOINT = "https://google.serper.dev/news"
MAX_RESULTS = 8


class NewsSource:
    key = "news"
    label = "Google News"

    def target(self, identity: Identity) -> str | None:
        return identity.company

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        company = self.target(identity)
        if not company:
            raise SkipSource("No company name on this row")

        api_key = cfg.require_key("serper", "Serper")
        response = await request_with_retry(
            client,
            "POST",
            SERPER_ENDPOINT,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": company, "num": MAX_RESULTS},
            timeout=cfg.timeout,
        )

        if response.status_code == 401:
            return failed(self.key, "Serper rejected the API key (401). Check it in Settings.")
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
