"""Row-level arq tasks.

One task per prospect per phase. This is what makes a 500-row sheet safe: a row
that fails retries on its own, a row that succeeds is never redone, and killing
the worker mid-run loses at most the in-flight rows.

A job has to be able to run unattended, so every path out of a task leaves the
row in a counted state or back in the queue:

  * a provider or Claude asking us to slow down puts the row back with a
    growing delay (arq only retries on `Retry`, never on a plain exception);
  * if Claude keeps refusing, or the plan's usage window is spent, the whole
    job pauses and `bookkeeping.resume_due_jobs` restarts it by itself;
  * anything unexpected marks the row failed rather than leaving it "running"
    with a job that can never close.
"""
import asyncio
import logging
from datetime import timedelta

from arq import Retry

from app.ai.chain import ChainError, RateLimited, RefusalError, run_chain
from app.ai.claude_code import UsageLimitReached
from app.ai.client import AuthUnavailable
from app.core import settings_store
from app.db import mongo
from app.models.common import Channel, RowStatus, utcnow
from app.models.prospect import Prospect
from app.models.template import Template
from app.sources import registry
from app.worker import bookkeeping, limiter

logger = logging.getLogger(__name__)

# Attempts per row, counting the first. arq's `max_tries` is set from this.
MAX_TRIES = 5
# Upper bound on the work itself, well under arq's job_timeout, so a hung row
# is marked failed here instead of being killed where nothing can record it.
# (Research times each of its steps instead: see registry.STEP_TIMEOUT.)
PERSONALIZE_TIMEOUT = 25 * 60
# How long the job waits when Claude rate-limits a row on every attempt.
RATE_LIMIT_PAUSE = timedelta(minutes=10)


def retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Seconds before a rate-limited row is tried again: 30s, 1m, 2m, 4m, and
    never sooner than the provider asked for."""
    backoff = min(30 * 2 ** (attempt - 1), 600)
    return min(max(backoff, retry_after or 0), 900)


async def _load_prospect(prospect_id: str) -> Prospect | None:
    doc = await mongo.prospects().find_one({"_id": prospect_id})
    return Prospect.model_validate(doc) if doc else None


async def _set_status(prospect_id: str, field: str, status: RowStatus) -> None:
    await mongo.prospects().update_one({"_id": prospect_id}, {"$set": {field: status.value}})


async def scrape_prospect(ctx: dict, job_id: str, prospect_id: str) -> str:
    """Research one prospect (see `registry.run_funnel`).

    No row slot is held for the whole task. The funnel takes one only around
    the fetches that do work, so a prospect waiting for its turn on LinkedIn
    does not stop other prospects being researched in the meantime.
    """
    # Checked first so a cancelled job drains quickly.
    if not await bookkeeping.job_is_active(job_id):
        return "cancelled"
    return await _scrape(ctx, job_id, prospect_id)


async def _scrape(ctx: dict, job_id: str, prospect_id: str) -> str:
    await bookkeeping.mark_started(job_id)

    job = await mongo.jobs().find_one({"_id": job_id})
    prospect = await _load_prospect(prospect_id)
    if not job or not prospect:
        await bookkeeping.record_row(job_id, "failed")
        return "missing"
    if not await bookkeeping.claim_row(prospect_id, "scrape_status"):
        return "duplicate"

    options = job.get("options", {})
    source_keys: list[str] = options.get("sources") or []
    use_cache = not options.get("force", False)

    try:
        cfg = await registry.build_config()
        results, linkedin_later = await registry.run_funnel(
            prospect.identity, source_keys, cfg, use_cache, busy=limiter.rows.slot
        )
    except Exception as exc:  # noqa: BLE001 - the registry already isolates per source
        logger.exception("Scrape crashed for prospect %s", prospect_id)
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {"$set": {"scrape_status": RowStatus.failed.value, "scrape_error": str(exc)}},
        )
        await bookkeeping.record_row(job_id, "failed")
        return "failed"

    # LinkedIn that could not be read this instant is left for the background
    # check; the row carries on with what it has.
    later = {
        "linkedin_pending": bool(linkedin_later),
        "linkedin_pending_keys": linkedin_later,
        "linkedin_pending_at": utcnow() if linkedin_later else None,
    }

    if not results and linkedin_later:
        # Only LinkedIn applies to this row, and its turn has not come yet.
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {
                "$set": {
                    "research": {},
                    "researched_at": utcnow(),
                    "scrape_status": RowStatus.done.value,
                    "scrape_error": "Waiting for the LinkedIn check, which runs in the background.",
                    **later,
                }
            },
        )
        await bookkeeping.record_row(job_id, "done")
        return "done"

    if not results:
        # Nothing applied to this row -- no website, no LinkedIn. Not a failure.
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {
                "$set": {
                    "scrape_status": RowStatus.skipped.value,
                    "scrape_error": "No source had anything to fetch for this row "
                    "(no website or LinkedIn URL).",
                    "researched_at": utcnow(),
                }
            },
        )
        await bookkeeping.record_row(job_id, "skipped")
        return "skipped"

    any_ok = any(result.ok for result in results.values())
    errors = [f"{key}: {r.error}" for key, r in results.items() if not r.ok]

    await mongo.prospects().update_one(
        {"_id": prospect_id},
        {
            "$set": {
                "research": {key: r.model_dump(mode="json") for key, r in results.items()},
                "researched_at": utcnow(),
                # Partial success still counts: one dead source should not void
                # the four that worked.
                "scrape_status": (RowStatus.done if any_ok else RowStatus.failed).value,
                "scrape_error": "; ".join(errors) if errors else None,
                **later,
            }
        },
    )

    await bookkeeping.record_row(job_id, "done" if any_ok else "failed")
    return "done" if any_ok else "failed"


async def personalize_prospect(ctx: dict, job_id: str, prospect_id: str) -> str:
    """Run the three-stage chain for one prospect."""
    if not await bookkeeping.job_is_active(job_id):
        return "cancelled"
    async with limiter.rows.slot():
        return await _personalize(ctx, job_id, prospect_id)


async def _personalize(ctx: dict, job_id: str, prospect_id: str) -> str:
    # Again after the wait: the job may have been paused or cancelled meanwhile.
    if not await bookkeeping.job_is_active(job_id):
        return "cancelled"

    await bookkeeping.mark_started(job_id)

    job = await mongo.jobs().find_one({"_id": job_id})
    prospect = await _load_prospect(prospect_id)
    if not job or not prospect:
        await bookkeeping.record_row(job_id, "failed")
        return "missing"
    if not await bookkeeping.claim_row(prospect_id, "personalize_status"):
        return "duplicate"

    async def fail(message: str) -> str:
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {
                "$set": {
                    "personalize_status": RowStatus.failed.value,
                    "personalize_error": message,
                }
            },
        )
        await bookkeeping.record_row(job_id, "failed")
        return "failed"

    options = job.get("options", {})
    channel = Channel(options.get("channel") or Channel.email.value)

    if not prospect.research:
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {
                "$set": {
                    "personalize_status": RowStatus.skipped.value,
                    "personalize_error": "No research on this row yet. Run a scrape job first.",
                }
            },
        )
        await bookkeeping.record_row(job_id, "skipped")
        return "skipped"

    settings = await settings_store.load()

    template_doc = await mongo.templates().find_one({"_id": options.get("template_id")})
    if not template_doc:
        template_doc = await mongo.templates().find_one(
            {"channel": channel.value, "is_active": True}
        )
    if not template_doc:
        return await fail(f"No active template for channel '{channel.value}'.")

    template = Template.model_validate(template_doc)

    prompts: dict[int, str] = {}
    for stage in (1, 2, 3, 4):
        prompt_id = (options.get("prompt_ids") or {}).get(str(stage))
        doc = None
        if prompt_id:
            doc = await mongo.prompts().find_one({"_id": prompt_id})
        if not doc:
            doc = await mongo.prompts().find_one({"stage": stage, "is_active": True})
        if not doc and stage == 4:
            continue  # optional: without it the row takes the three-call chain
        if not doc:
            return await fail(f"No active prompt for stage {stage}.")
        prompts[stage] = doc["body"]

    try:
        output = await asyncio.wait_for(
            run_chain(
                identity=prospect.identity,
                raw=prospect.raw,
                research=prospect.research,
                prompts=prompts,
                template=template,
                settings=settings,
                channel=channel,
            ),
            timeout=PERSONALIZE_TIMEOUT,
        )
    except UsageLimitReached as exc:
        # The plan's usage window is spent. Nothing is wrong with the row or the
        # credential: pause the job, and the worker restarts it after the reset.
        await _set_status(prospect_id, "personalize_status", RowStatus.queued)
        await bookkeeping.pause_job(job_id, str(exc), exc.resume_at)
        return "paused"
    except AuthUnavailable as exc:
        # Credential problem is job-wide, not row-specific. Park the whole job so
        # the operator reconnects once instead of watching 500 rows fail.
        await _set_status(prospect_id, "personalize_status", RowStatus.pending)
        await bookkeeping.block_job(job_id, str(exc))
        return "blocked"
    except RateLimited as exc:
        await _set_status(prospect_id, "personalize_status", RowStatus.queued)
        attempt = ctx.get("job_try", 1)
        if attempt < MAX_TRIES:
            raise Retry(defer=retry_delay(attempt, exc.retry_after)) from exc
        # Still limited after every attempt: slowing down one row is not enough,
        # so give the whole job a rest.
        await bookkeeping.pause_job(
            job_id,
            f"{str(exc).rstrip('.')}. The job paused itself and will carry on automatically.",
            utcnow() + RATE_LIMIT_PAUSE,
        )
        return "paused"
    except RefusalError as exc:
        return await fail(str(exc))
    except ChainError as exc:
        return await fail(str(exc))
    except asyncio.TimeoutError:
        return await fail(
            f"Personalization took longer than {PERSONALIZE_TIMEOUT // 60} minutes."
        )
    except Exception as exc:  # noqa: BLE001 - a row must always end in a counted state
        logger.exception("Personalization crashed for prospect %s", prospect_id)
        return await fail(f"Unexpected error: {type(exc).__name__}: {exc}")

    personalization = output.personalization
    personalization.generated_at = utcnow()
    if output.hold or (output.thin_context and personalization.draft is None):
        # The contact is in doubt, or there is nothing to send: a person decides.
        status = RowStatus.needs_review
    elif output.thin_context:
        status = RowStatus.thin_context
    else:
        status = RowStatus.done

    await mongo.prospects().update_one(
        {"_id": prospect_id},
        {
            "$set": {
                "personalization": personalization.model_dump(mode="json"),
                "personalize_status": status.value,
                "personalize_error": output.reason if output.thin_context else None,
            }
        },
    )

    if output.warnings:
        logger.warning("Prospect %s: %s", prospect_id, "; ".join(set(output.warnings)))

    # thin_context counts as done for progress: the row was processed, it just
    # needs a human rather than a retry.
    usage = personalization.usage
    await bookkeeping.record_row(
        job_id,
        "done",
        cost_usd=personalization.cost_usd,
        tokens=usage.input_tokens
        + usage.output_tokens
        + usage.cache_read_input_tokens
        + usage.cache_creation_input_tokens,
    )
    return status.value
