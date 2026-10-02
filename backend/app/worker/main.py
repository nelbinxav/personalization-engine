"""arq worker entrypoint.

Run with:  arq app.worker.main.WorkerSettings

Concurrency is the Settings value, enforced by `app.worker.limiter` and re-read
while jobs run; it is the single knob controlling both scraping provider load
and Claude spend rate. arq's own `max_jobs` is only the ceiling, because arq
fixes it at startup.
"""
import logging

from arq import cron

from app.core.config import get_settings
from app.db import mongo
from app.db.init_db import initialize_database
from app.worker.bookkeeping import redis_settings, resume_due_jobs
from app.worker.limiter import ARQ_MAX_JOBS
from app.worker.tasks import MAX_TRIES, personalize_prospect, scrape_prospect

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

    logger.info("Worker ready (concurrency=%s, from Settings)", settings.concurrency)


async def shutdown(ctx: dict) -> None:
    await mongo.close_client()


class WorkerSettings:
    functions = [scrape_prospect, personalize_prospect]
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown

    # Paused jobs (a plan usage window, repeated rate limits) restart themselves.
    cron_jobs = [cron(resume_due_jobs, second=0, run_at_startup=True)]

    max_jobs = ARQ_MAX_JOBS
    # A backstop only. Rows time their own work out much sooner (see tasks.py);
    # this has to cover a row waiting for a slot or for its turn on LinkedIn,
    # which at a careful pace can be most of a day.
    job_timeout = 26 * 60 * 60
    # arq retries a row only when the task raises `Retry`, which it does for
    # rate limits. Terminal failures are caught inside the task and never raise.
    max_tries = MAX_TRIES
    # Results are not read anywhere, and a stored result would stop the same
    # row being queued again under its fixed id (see bookkeeping.enqueue_row).
    keep_result = 0
    health_check_interval = 60
