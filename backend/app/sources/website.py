"""Website content via Jina Reader (https://r.jina.ai).

Jina returns a clean markdown rendering of a page, which is far better prompt
input than raw HTML and costs nothing on the free tier. An API key raises the
rate limit but is not required.
"""
import httpx

from app.models.common import Identity
from app.models.prospect import SourceResult
from app.sources.base import (
    SourceConfig,
    SourceRateLimited,
    SkipSource,
    failed,
    normalize_url,
    ok,
    request_with_retry,
)

JINA_ENDPOINT = "https://r.jina.ai/"


class WebsiteSource:
    key = "website"
    label = "Company website"

    def target(self, identity: Identity) -> str | None:
        return normalize_url(identity.website)

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult:
        url = self.target(identity)
        if not url:
            raise SkipSource("No website on this row")

        headers = {
            "Accept": "text/plain",
            "X-Return-Format": "markdown",
            # Ask for the words only. Images, menus and link targets are most of
            # a page by size and none of its meaning; leaving them out cuts a
            # page to a fraction (measured: 52,000 characters to under 7,000),
            # which saves Jina allowance and lets real content fit the limit.
            "X-Retain-Images": "none",
            "X-Remove-Selector": "nav, header",
            "X-Md-Link-Style": "discarded",
        }
        api_key = cfg.key("jina")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        response = await request_with_retry(
            client, "GET", f"{JINA_ENDPOINT}{url}", headers=headers, timeout=cfg.timeout
        )

        if response.status_code == 404:
            return failed(self.key, f"Website returned 404: {url}", url=url)
        if response.status_code == 429:
            raise SourceRateLimited(
                "Jina Reader rate limit hit. Add a Jina API key in Settings to raise it."
            )
        if response.status_code >= 400:
            return failed(
                self.key,
                f"Jina Reader returned HTTP {response.status_code}",
                url=url,
            )

        text = response.text.strip()
        if not text:
            return failed(self.key, "Website returned no readable content", url=url)

        return ok(self.key, text, cfg, url=url)
