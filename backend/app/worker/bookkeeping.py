"""Shared job bookkeeping for row tasks.

Rows are independent arq jobs, so progress is tracked by atomic $inc on the
parent job document. The last row to finish closes the job -- determined from
the incremented counters returned by the update itself, so two rows finishing
simultaneously cannot both think they were last.
"""
import logging

from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings
from app.db import mongo
from app.models.common import utcnow
from app.models.job import JobStatus

logger = logging.getLogger(__name__)


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_redis() -> ArqRedis:
    from arq import create_pool

    return await create_pool(redis_settings())


async def mark_started(job_id: str) -> None:
    await mongo.jobs().update_one(
        {"_id": job_id, "started_at": None},
        {"$set": {"status": JobStatus.running.value, "started_at": utcnow()}},
    )


async def record_row(
    job_id: str,
    outcome: str,
    cost_usd: float = 0.0,
) -> None:
    """Increment one counter and close the job if this was the final row.

    `outcome` is one of done / failed / skipped.
    """
    field = f"counts.{outcome}"
    updated = await mongo.jobs().find_one_and_update(
        {"_id": job_id},
        {"$inc": {field: 1, "cost_usd": cost_usd}},
        return_document=True,
    )
    if not updated:
        return

    counts = updated.get("counts", {})
    finished = counts.get("done", 0) + counts.get("failed", 0) + counts.get("skipped", 0)
    total = counts.get("total", 0)

    if finished >= total and updated.get("status") in (
        JobStatus.running.value,
        JobStatus.queued.value,
    ):
        status = JobStatus.done if counts.get("done", 0) or counts.get("skipped", 0) else JobStatus.failed
        await mongo.jobs().update_one(
            {"_id": job_id},
            {"$set": {"status": status.value, "finished_at": utcnow()}},
        )
        logger.info(
            "Job %s finished: %s done, %s failed, %s skipped",
            job_id,
            counts.get("done", 0),
            counts.get("failed", 0),
            counts.get("skipped", 0),
        )


async def block_job(job_id: str, reason: str) -> None:
    """Park a job on a credential failure instead of burning through rows.

    Rows already finished keep their results; resuming re-enqueues only the
    ones still pending.
    """
    await mongo.jobs().update_one(
        {"_id": job_id, "status": {"$in": [JobStatus.queued.value, JobStatus.running.value]}},
        {"$set": {"status": JobStatus.blocked_auth.value, "error": reason}},
    )
    logger.error("Job %s blocked: %s", job_id, reason)


async def job_is_active(job_id: str) -> bool:
    doc = await mongo.jobs().find_one({"_id": job_id}, {"status": 1})
    if not doc:
        return False
    return doc.get("status") in (JobStatus.queued.value, JobStatus.running.value)
