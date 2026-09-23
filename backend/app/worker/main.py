"""arq worker entrypoint.

Run with:  arq app.worker.main.WorkerSettings

Concurrency is set by `max_jobs`: rows run in parallel up to that number, which
is the single knob controlling both scraping provider load and Claude spend
rate.
"""
import logging

from app.core.config import get_settings
from app.db import mongo
from app.db.init_db import initialize_database
from app.worker.bookkeeping import redis_settings
from app.worker.tasks import personalize_prospect, scrape_prospect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    await initialize_database()

    # Fail loudly here rather than subtly at row 200. This is the check that
    # catches a stray ANTHROPIC_API_KEY silently overriding the OAuth profile.
    from app.ai.client import api_key_is_set
    from app.core.settings_store import load
    from app.models.settings import CredentialMode

    settings = await load()
    if settings.ai.mode is CredentialMode.oauth and api_key_is_set():
        raise RuntimeError(
            "Credential mode is OAuth but ANTHROPIC_API_KEY is set in the worker "
            "environment. The SDK would use the key and bill the wrong org. Remove it "
            "from .env / docker-compose, or switch Settings to API key mode."
        )

    logger.info("Worker ready (concurrency=%s)", ctx["max_jobs"] if "max_jobs" in ctx else "?")


async def shutdown(ctx: dict) -> None:
    await mongo.close_client()


class WorkerSettings:
    functions = [scrape_prospect, personalize_prospect]
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown

    max_jobs = 4
    job_timeout = 600
    # Rows retry on transient failures (rate limits, network blips). Terminal
    # failures are caught inside the task and never raise, so they do not retry.
    max_tries = 3
    keep_result = 3600
    health_check_interval = 60
