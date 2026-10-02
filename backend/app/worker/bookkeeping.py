"""Shared job bookkeeping for row tasks.

Rows are independent arq jobs, so progress is tracked by atomic $inc on the
parent job document. The last row to finish closes the job -- determined from
the incremented counters returned by the update itself, so two rows finishing
simultaneously cannot both think they were last.
"""
import logging
from datetime import datetime, timedelta

from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings
from app.db import mongo
from app.models.common import RowStatus, utcnow
from app.models.job import JobStatus, JobType

logger = logging.getLogger(__name__)

TASK_FOR_TYPE = {
    JobType.scrape: "scrape_prospect",
    JobType.personalize: "personalize_prospect",
}
STATUS_FIELD = {
    JobType.scrape: "scrape_status",
    JobType.personalize: "personalize_status",
}

# How long a paused job waits when Claude did not say when the limit resets.
# Each probe costs one failed call, so a wrong guess is cheap.
DEFAULT_PAUSE = timedelta(minutes=30)
# Start a little after the stated reset rather than on the dot.
RESUME_MARGIN = timedelta(minutes=2)


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_redis() -> ArqRedis:
    from arq import create_pool

    return await create_pool(redis_settings())


async def enqueue_row(redis: ArqRedis, job_type: JobType, job_id: str, prospect_id: str) -> bool:
    """Queue one row. The fixed arq id means a row already queued or running for
    this job is not queued a second time, so resuming a job whose old tasks have
    not drained yet cannot process a row twice. False when it was already there.
    """
    queued = await redis.enqueue_job(
        TASK_FOR_TYPE[job_type],
        job_id,
        prospect_id,
        _job_id=f"{job_type.value}:{job_id}:{prospect_id}",
    )
    return queued is not None


async def claim_row(prospect_id: str, field: str) -> bool:
    """Mark a row running, unless it has already finished.

    A second task for a finished row (a late duplicate) must not run it again or
    count it twice. `running` is claimable so a row interrupted by a worker
    restart is picked up when arq re-runs it.
    """
    result = await mongo.prospects().update_one(
        {"_id": prospect_id, field: {"$in": [RowStatus.queued.value, RowStatus.running.value]}},
        {"$set": {field: RowStatus.running.value}},
    )
    return result.matched_count == 1


async def mark_started(job_id: str) -> None:
    await mongo.jobs().update_one(
        {"_id": job_id, "started_at": None},
        {"$set": {"status": JobStatus.running.value, "started_at": utcnow()}},
    )


async def record_row(
    job_id: str,
    outcome: str,
    cost_usd: float = 0.0,
    tokens: int = 0,
) -> None:
    """Increment one counter and close the job if this was the final row.

    `outcome` is one of done / failed / skipped.
    """
    field = f"counts.{outcome}"
    updated = await mongo.jobs().find_one_and_update(
        {"_id": job_id},
        {"$inc": {field: 1, "cost_usd": cost_usd, "tokens": tokens}},
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


async def pause_job(job_id: str, reason: str, resume_at: datetime | None = None) -> None:
    """Park a job because Claude asked us to wait. `resume_due_jobs` restarts it.

    Only the first row to hit the limit sets the time; the rows in flight
    behind it find the job already paused.
    """
    resume_at = (resume_at + RESUME_MARGIN) if resume_at else utcnow() + DEFAULT_PAUSE
    result = await mongo.jobs().update_one(
        {"_id": job_id, "status": {"$in": [JobStatus.queued.value, JobStatus.running.value]}},
        {
            "$set": {
                "status": JobStatus.rate_limited.value,
                "error": reason,
                "resume_at": resume_at,
            },
            "$push": {
                "limit_events": {
                    "$each": [{"at": utcnow(), "reason": reason[:300], "resume_at": resume_at}],
                    # A long wait re-pauses on every probe; keep the recent ones.
                    "$slice": -20,
                }
            },
        },
    )
    if result.modified_count:
        logger.warning("Job %s paused until %s: %s", job_id, resume_at.isoformat(), reason)


async def requeue_unfinished(job: dict, redis: ArqRedis) -> int:
    """Put a parked or cancelled job's unfinished rows back in the queue.

    Returns how many rows were waiting. With none left the job is closed.
    """
    job_id = job["_id"]
    job_type = JobType(job["type"])
    field = STATUS_FIELD[job_type]
    waiting = {"$in": [RowStatus.pending.value, RowStatus.queued.value]}

    pending = [
        prospect["_id"]
        async for prospect in mongo.prospects().find(
            {"upload_id": job["upload_id"], field: waiting}, {"_id": 1}
        )
    ]

    if not pending:
        await mongo.jobs().update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": JobStatus.done.value,
                    "finished_at": utcnow(),
                    "error": None,
                    "resume_at": None,
                }
            },
        )
        return 0

    await mongo.prospects().update_many(
        {"_id": {"$in": pending}, field: waiting}, {"$set": {field: RowStatus.queued.value}}
    )
    await mongo.jobs().update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": JobStatus.running.value,
                "error": None,
                "finished_at": None,
                "resume_at": None,
            }
        },
    )
    for prospect_id in pending:
        await enqueue_row(redis, job_type, job_id, prospect_id)

    logger.info("Resumed job %s with %d unfinished rows", job_id, len(pending))
    return len(pending)


async def resume_due_jobs(ctx: dict) -> int:
    """Cron, every minute: restart the paused jobs whose wait is over.

    If the limit has not actually lifted, the first row pauses the job again
    with a new time, so this never spins.
    """
    resumed = 0
    cursor = mongo.jobs().find(
        {"status": JobStatus.rate_limited.value, "resume_at": {"$lte": utcnow()}}
    )
    async for job in cursor:
        await requeue_unfinished(job, ctx["redis"])
        resumed += 1
    return resumed


async def job_is_active(job_id: str) -> bool:
    doc = await mongo.jobs().find_one({"_id": job_id}, {"status": 1})
    if not doc:
        return False
    return doc.get("status") in (JobStatus.queued.value, JobStatus.running.value)
