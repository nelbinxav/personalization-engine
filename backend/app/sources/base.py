"""The scraping source interface.

Every data source implements `Source`. The registry runs enabled sources
concurrently per prospect and stores each result independently, so a dead
source degrades one column rather than failing the row.

Adding a source means: write a module here, add it to `registry.ALL_SOURCES`.
Nothing else in the system needs to change.
"""
import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.models.common import Identity
from app.models.prospect import SourceResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_CONTENT_CHARS = 20_000


class SourceError(Exception):
    """A source failed in a way worth reporting on the row."""


class SourceRateLimited(SourceError):
    """The provider told us to slow down, after our own retries. The row is
    worth trying again later, unlike a failure that will repeat."""


class SourceDailyLimit(SourceError):
    """Our own daily cap for a provider is spent. Nothing will work until
    tomorrow, so the job waits rather than retrying."""


class SourceBusy(SourceError):
    """The provider cannot be used this instant and the caller asked not to
    wait (LinkedIn between paced reads). Not a failure: it is done later."""


class SkipSource(Exception):
    """This prospect has nothing for this source to work with (e.g. no website).

    Distinct from an error: a missing LinkedIn URL is not a failure, it is an
    absence, and the row should not be marked failed because of it.
    """


@dataclass
class SourceConfig:
    keys: dict[str, str | None] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    cache_ttl_hours: int = 24 * 7
    linkedin_provider: str = "apify"
    # The `account` LinkedIn provider: where its browser service listens, and
    # how many LinkedIn page reads a day we allow ourselves on that account.
    linkedin_mcp_url: str = "http://linkedin:8080/mcp"
    linkedin_daily_limit: int = 150
    linkedin_reads_per_hour: int = 20
    # False: a LinkedIn read that would have to wait for its turn raises
    # SourceBusy instead. Research never waits; the background check does.
    linkedin_wait: bool = True
    # A post older than this is not "recent" enough to open a message with.
    recent_post_days: int = 14
    max_content_chars: int = MAX_CONTENT_CHARS

    def key(self, name: str) -> str | None:
        return self.keys.get(name)

    def require_key(self, name: str, provider: str) -> str:
        value = self.keys.get(name)
        if not value:
            raise SourceError(
                f"No {provider} API key configured. Add one in Settings to enable this source."
            )
        return value


class Source(Protocol):
    key: str
    label: str

    def target(self, identity: Identity) -> str | None:
        """What this source will fetch, or None if the prospect lacks the input.

        Doubles as the cache key, so it must be deterministic for a prospect.
        """

    async def fetch(
        self, identity: Identity, cfg: SourceConfig, client: httpx.AsyncClient
    ) -> SourceResult: ...


def truncate(text: str, limit: int) -> str:
    """Cap scraped content. Long pages are mostly nav and footer past the fold,
    and the whole corpus has to fit in a prompt later.
    """
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated at {limit} characters]"


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    retry_on: tuple[int, ...] = (429, 500, 502, 503, 504),
    **kwargs,
) -> httpx.Response:
    """HTTP with bounded retries and jittered backoff.

    Retries transient failures only; a 404 is an answer, not a blip.
    """
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in retry_on and attempt < attempts - 1:
                delay = _backoff(attempt, response)
                logger.info(
                    "%s %s returned %s; retrying in %.1fs", method, url, response.status_code, delay
                )
                await asyncio.sleep(delay)
                continue
            return response
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(_backoff(attempt, None))
                continue
            raise SourceError(f"Network error after {attempts} attempts: {exc}") from exc

    raise SourceError(f"Request failed: {last_error}")


def _backoff(attempt: int, response: httpx.Response | None) -> float:
    # Honour Retry-After when the server bothers to send one.
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(float(header), 30.0)
            except ValueError:
                pass
    return min(2**attempt, 8) + random.uniform(0, 0.75)


def ok(key: str, content: str, cfg: SourceConfig, **meta) -> SourceResult:
    return SourceResult(
        key=key, ok=True, content=truncate(content, cfg.max_content_chars), meta=meta
    )


def failed(key: str, error: str, **meta) -> SourceResult:
    return SourceResult(key=key, ok=False, error=error, meta=meta)
