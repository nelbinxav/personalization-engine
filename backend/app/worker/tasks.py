"""Row-level arq tasks.

One task per prospect per phase. This is what makes a 500-row sheet safe: a row
that fails retries on its own, a row that succeeds is never redone, and killing
the worker mid-run loses at most the in-flight rows.
"""
import logging

from app.ai.chain import ChainError, RefusalError, run_chain
from app.ai.client import AuthUnavailable
from app.core import settings_store
from app.db import mongo
from app.models.common import Channel, RowStatus, utcnow
from app.models.prospect import Prospect
from app.models.template import Template
from app.sources import registry
from app.worker import bookkeeping

logger = logging.getLogger(__name__)


async def _load_prospect(prospect_id: str) -> Prospect | None:
    doc = await mongo.prospects().find_one({"_id": prospect_id})
    return Prospect.model_validate(doc) if doc else None


async def scrape_prospect(ctx: dict, job_id: str, prospect_id: str) -> str:
    """Fetch every enabled source for one prospect."""
    if not await bookkeeping.job_is_active(job_id):
        return "cancelled"

    await bookkeeping.mark_started(job_id)

    job = await mongo.jobs().find_one({"_id": job_id})
    prospect = await _load_prospect(prospect_id)
    if not job or not prospect:
        await bookkeeping.record_row(job_id, "failed")
        return "missing"

    options = job.get("options", {})
    source_keys: list[str] = options.get("sources") or []
    use_cache = not options.get("force", False)

    await mongo.prospects().update_one(
        {"_id": prospect_id}, {"$set": {"scrape_status": RowStatus.running.value}}
    )

    try:
        cfg = await registry.build_config()
        results = await registry.run_sources(prospect.identity, source_keys, cfg, use_cache)
    except Exception as exc:  # noqa: BLE001 - the registry already isolates per source
        logger.exception("Scrape crashed for prospect %s", prospect_id)
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {"$set": {"scrape_status": RowStatus.failed.value, "scrape_error": str(exc)}},
        )
        await bookkeeping.record_row(job_id, "failed")
        return "failed"

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
            }
        },
    )

    await bookkeeping.record_row(job_id, "done" if any_ok else "failed")
    return "done" if any_ok else "failed"


async def personalize_prospect(ctx: dict, job_id: str, prospect_id: str) -> str:
    """Run the three-stage chain for one prospect."""
    if not await bookkeeping.job_is_active(job_id):
        return "cancelled"

    await bookkeeping.mark_started(job_id)

    job = await mongo.jobs().find_one({"_id": job_id})
    prospect = await _load_prospect(prospect_id)
    if not job or not prospect:
        await bookkeeping.record_row(job_id, "failed")
        return "missing"

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

    await mongo.prospects().update_one(
        {"_id": prospect_id}, {"$set": {"personalize_status": RowStatus.running.value}}
    )

    settings = await settings_store.load()

    template_doc = await mongo.templates().find_one({"_id": options.get("template_id")})
    if not template_doc:
        template_doc = await mongo.templates().find_one(
            {"channel": channel.value, "is_active": True}
        )
    if not template_doc:
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {
                "$set": {
                    "personalize_status": RowStatus.failed.value,
                    "personalize_error": f"No active template for channel '{channel.value}'.",
                }
            },
        )
        await bookkeeping.record_row(job_id, "failed")
        return "failed"

    template = Template.model_validate(template_doc)

    prompts: dict[int, str] = {}
    for stage in (1, 2, 3):
        prompt_id = (options.get("prompt_ids") or {}).get(str(stage))
        doc = None
        if prompt_id:
            doc = await mongo.prompts().find_one({"_id": prompt_id})
        if not doc:
            doc = await mongo.prompts().find_one({"stage": stage, "is_active": True})
        if not doc:
            await mongo.prospects().update_one(
                {"_id": prospect_id},
                {
                    "$set": {
                        "personalize_status": RowStatus.failed.value,
                        "personalize_error": f"No active prompt for stage {stage}.",
                    }
                },
            )
            await bookkeeping.record_row(job_id, "failed")
            return "failed"
        prompts[stage] = doc["body"]

    try:
        output = await run_chain(
            identity=prospect.identity,
            raw=prospect.raw,
            research=prospect.research,
            prompts=prompts,
            template=template,
            settings=settings,
            channel=channel,
        )
    except AuthUnavailable as exc:
        # Credential problem is job-wide, not row-specific. Park the whole job so
        # the operator reconnects once instead of watching 500 rows fail.
        await mongo.prospects().update_one(
            {"_id": prospect_id}, {"$set": {"personalize_status": RowStatus.pending.value}}
        )
        await bookkeeping.block_job(job_id, str(exc))
        return "blocked"
    except RefusalError as exc:
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {
                "$set": {
                    "personalize_status": RowStatus.failed.value,
                    "personalize_error": str(exc),
                }
            },
        )
        await bookkeeping.record_row(job_id, "failed")
        return "failed"
    except ChainError as exc:
        await mongo.prospects().update_one(
            {"_id": prospect_id},
            {
                "$set": {
                    "personalize_status": RowStatus.failed.value,
                    "personalize_error": str(exc),
                }
            },
        )
        await bookkeeping.record_row(job_id, "failed")
        return "failed"

    personalization = output.personalization
    personalization.generated_at = utcnow()
    status = RowStatus.thin_context if output.thin_context else RowStatus.done

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
    await bookkeeping.record_row(job_id, "done", cost_usd=personalization.cost_usd)
    return status.value
