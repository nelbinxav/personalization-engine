"""Web search through Exa's hosted MCP endpoint, which needs no API key.

Used for two things a scrape of the prospect's own site cannot find: podcast
and interview appearances, and news when no Serper key is configured. This is
the search backend Agent Reach routes to.
"""
import httpx

from app.models.common import Identity
from app.models.prospect import SourceResult
from app.sources.base import SkipSource, SourceConfig, failed, ok
from app.sources.mcp_http import call_tool, tool_text

EXA_MCP_URL = "https://mcp.exa.ai/mcp"


async def search(
    client: httpx.AsyncClient, query: str, objective: str, *, results: int = 5, timeout: float = 45
) -> str:
    """Search and return Exa's text block of titles, URLs, dates and highlights."""
    result = await call_tool(
        client,
        EXA_MCP_URL,
        "web_search_exa",
        {"query": query, "objective": objective, "numResults": results},
        timeout=timeout,
        # Exa answers a bare call, so skip the two handshake round trips.
        handshake=False,
    )
    return tool_text(result)


def person_name(identity: Identity) -> str | None:
    if identity.full_name:
        return identity.full_name.strip() or None
    parts = [p.strip() for p in (identity.first_name, identity.last_name) if p and p.strip()]
    # A first name alone matches thousands of people.
    return " ".join(parts) if len(parts) == 2 else None


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
        )
        if not text or text.lower().startswith("no "):
            return failed(self.key, f"No podcast or interview found for {name}", query=name)

        body = (
            f"Search results for podcast and interview appearances by {name} ({company}).\n"
            "A result counts only if it names this person together with this company or role; "
            "people with the same name appear in searches like this.\n\n" + text
        )
        return ok(self.key, body, cfg, query=name)


async def company_news(client: httpx.AsyncClient, company: str) -> str:
    return await search(
        client,
        f"recent news and press releases about the company {company}",
        f"News articles and press releases about {company} from the last three months, newest "
        "first, each with its publication date. Exclude product pages, job listings and "
        "companies with a similar name.",
    )
