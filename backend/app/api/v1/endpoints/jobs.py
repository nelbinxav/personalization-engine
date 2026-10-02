import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.chain import stage_model
from app.ai.openai_stage import is_openai_model
from app.api.deps import current_operator
from app.core import settings_store
from app.db import mongo
from app.models.common import Channel, RowStatus, utcnow
from app.models.job import (
    CreateJobRequest,
    Job,
    JobCounts,
    JobOut,
    JobStatus,
    JobType,
)
from app.models.prompt import Stage
from app.models.prospect import ProspectOut, outreach_of
from app.models.prospect import Prospect
from app.sources.registry import source_catalog
from app.worker.bookkeeping import STATUS_FIELD, enqueue_row, get_redis, requeue_unfinished

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(current_operator)])


@router.get("/sources")
async def sources() -> dict:
    return {"sources": source_catalog()}


async def _select_prospect_ids(payload: CreateJobRequest) -> list[str]:
    """Pick the rows this job will touch.

    Without `force`, rows that already have a result for this phase are left
    alone -- re-running a job to pick up stragglers must not re-bill the rows
    that already worked.
    """
    query: dict = {"upload_id": payload.upload_id}

    if not payload.options.force:
        done_states = [RowStatus.done.value, RowStatus.skipped.value]
        if payload.type is JobType.personalize:
            done_states += [RowStatus.thin_context.value, RowStatus.needs_review.value]
        # Rows another job already has in hand are left to it, so a second job
        # started on the same upload takes only what is left: "first 75 with
        # LinkedIn", then "everything else without" can be queued back to back.
        in_hand = [RowStatus.queued.value, RowStatus.running.value]
        query[STATUS_FIELD[payload.type]] = {"$nin": done_states + in_hand}

    if payload.type is JobType.personalize:
        # Nothing to personalize from without research.
        query["research"] = {"$nin": [None, {}]}

    cursor = mongo.prospects().find(query, {"_id": 1}).sort("row_index", 1)
    if payload.options.limit:
        cursor = cursor.limit(payload.options.limit)

    return [doc["_id"] async for doc in cursor]


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(payload: CreateJobRequest) -> JobOut:
    upload = await mongo.uploads().find_one({"_id": payload.upload_id})
    if not upload:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")

    settings = await settings_store.load()
    options = payload.options.model_copy()

    if payload.type is JobType.scrape:
        options.sources = options.sources or settings.enabled_sources
        if not options.sources:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No scraping sources are enabled. Enable at least one in Settings.",
            )
    else:
        options.channel = options.channel or Channel.email
        if not settings.offer_context.strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Set 'What we sell' in Settings before personalizing - stage 2 cannot "
                "judge whether an angle is relevant without it.",
            )

        # A stage given to an OpenAI model fails every row without its key.
        gpt_stages = sorted(
            stage
            for stage in settings.ai.enabled_stages
            if is_openai_model(stage_model(settings, Stage(stage)))
        )
        if gpt_stages and not await settings_store.provider_key("openai"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Stage {gpt_stages[0]} is set to an OpenAI model, but no OpenAI API key is "
                "saved. Add one under Settings, Keys, or choose a Claude model for that stage.",
            )

    options.concurrency = options.concurrency or settings.concurrency

    prospect_ids = await _select_prospect_ids(payload)
    if not prospect_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No rows need this job. Every row already has a result - tick 'force' to redo them."
            if not payload.options.force
            else "This upload has no rows.",
        )

    job = Job(
        type=payload.type,
        upload_id=payload.upload_id,
        options=options,
        counts=JobCounts(total=len(prospect_ids)),
    )
    await mongo.jobs().insert_one(job.to_mongo())

    # Reset the per-row status so the UI shows them as queued immediately.
    await mongo.prospects().update_many(
        {"_id": {"$in": prospect_ids}},
        {"$set": {STATUS_FIELD[payload.type]: RowStatus.queued.value}},
    )

    redis = await get_redis()
    try:
        for prospect_id in prospect_ids:
            await enqueue_row(redis, payload.type, job.id, prospect_id)
    finally:
        await redis.close()

    logger.info("Queued %s job %s over %d rows", payload.type.value, job.id, len(prospect_ids))
    return await _job_out(job.to_mongo())


async def _job_out(doc: dict) -> JobOut:
    upload = await mongo.uploads().find_one({"_id": doc["upload_id"]}, {"name": 1})
    return JobOut(
        id=doc["_id"],
        type=doc["type"],
        upload_id=doc["upload_id"],
        upload_name=(upload or {}).get("name"),
        status=doc["status"],
        counts=JobCounts.model_validate(doc.get("counts", {})),
        options=doc.get("options", {}),
        error=doc.get("error"),
        cost_usd=round(doc.get("cost_usd", 0.0), 4),
        created_at=doc.get("created_at"),
        started_at=doc.get("started_at"),
        finished_at=doc.get("finished_at"),
        resume_at=doc.get("resume_at"),
        tokens=doc.get("tokens", 0),
        limit_events=doc.get("limit_events", []),
    )


@router.get("", response_model=list[JobOut])
async def list_jobs(upload_id: str | None = None, limit: int = 50) -> list[JobOut]:
    query = {"upload_id": upload_id} if upload_id else {}
    cursor = mongo.jobs().find(query).sort("created_at", -1).limit(limit)
    return [await _job_out(doc) async for doc in cursor]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str) -> JobOut:
    doc = await mongo.jobs().find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return await _job_out(doc)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: str) -> JobOut:
    doc = await mongo.jobs().find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if doc["status"] not in (
        JobStatus.queued.value,
        JobStatus.running.value,
        # A paused job would otherwise restart itself with no way to stop it.
        JobStatus.rate_limited.value,
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Job is not running")

    # Queued row tasks check job status before doing any work, so flipping the
    # status here drains the rest of the queue without killing in-flight rows.
    await mongo.jobs().update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": JobStatus.cancelled.value,
                "finished_at": utcnow(),
                "resume_at": None,
            }
        },
    )
    # Hand its waiting rows back, so a later job can pick them up. Resuming
    # this job still finds them: it takes pending rows as well as queued ones.
    field = STATUS_FIELD[JobType(doc["type"])]
    await mongo.prospects().update_many(
        {"upload_id": doc["upload_id"], field: RowStatus.queued.value},
        {"$set": {field: RowStatus.pending.value}},
    )
    return await _job_out(await mongo.jobs().find_one({"_id": job_id}))


@router.post("/{job_id}/resume", response_model=JobOut)
async def resume_job(job_id: str) -> JobOut:
    """Re-enqueue the rows a paused, blocked or cancelled job never got to.

    A rate-limited job does this by itself when its wait is over; resuming it
    here just skips the wait.
    """
    doc = await mongo.jobs().find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if doc["status"] not in (
        JobStatus.blocked_auth.value,
        JobStatus.rate_limited.value,
        JobStatus.cancelled.value,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only paused or cancelled jobs can be resumed"
        )

    redis = await get_redis()
    try:
        await requeue_unfinished(doc, redis)
    finally:
        await redis.close()

    return await _job_out(await mongo.jobs().find_one({"_id": job_id}))


@router.post("/{job_id}/rows/{prospect_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_row(job_id: str, prospect_id: str) -> dict:
    job = await mongo.jobs().find_one({"_id": job_id})
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    job_type = JobType(job["type"])
    field = STATUS_FIELD[job_type]

    prospect = await mongo.prospects().find_one({"_id": prospect_id}, {field: 1})
    if not prospect:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found")

    previous = prospect.get(field)
    # Re-open the parent job so bookkeeping does not close it on this row, and
    # give back the counter slot the previous attempt consumed.
    decrement = {}
    counted_done = (
        RowStatus.done.value,
        RowStatus.thin_context.value,
        RowStatus.needs_review.value,
    )
    if previous in (RowStatus.failed.value, RowStatus.skipped.value, *counted_done):
        bucket = "done" if previous in counted_done else (
            "skipped" if previous == RowStatus.skipped.value else "failed"
        )
        decrement = {f"counts.{bucket}": -1}

    await mongo.jobs().update_one(
        {"_id": job_id},
        {
            "$set": {"status": JobStatus.running.value, "finished_at": None},
            **({"$inc": decrement} if decrement else {}),
        },
    )
    await mongo.prospects().update_one(
        {"_id": prospect_id},
        {"$set": {field: RowStatus.queued.value}},
    )

    redis = await get_redis()
    try:
        await enqueue_row(redis, job_type, job_id, prospect_id)
    finally:
        await redis.close()

    return {"status": "queued"}


def _prospect_out(doc: dict) -> ProspectOut:
    prospect = Prospect.model_validate(doc)
    personalization = prospect.personalization
    angle = personalization.angles[0] if personalization.angles else None
    return ProspectOut(
        id=prospect.id,
        row_index=prospect.row_index,
        identity=prospect.identity,
        scrape_status=prospect.scrape_status,
        personalize_status=prospect.personalize_status,
        scrape_error=prospect.scrape_error,
        personalize_error=prospect.personalize_error,
        sources={key: result.ok for key, result in prospect.research.items()},
        subject=personalization.draft.subject if personalization.draft else None,
        body=personalization.draft.body if personalization.draft else None,
        angle=angle.angle if angle else None,
        evidence=angle.evidence if angle else None,
        outreach=outreach_of(prospect),
        cost_usd=round(personalization.cost_usd, 5),
    )


@router.get("/{job_id}/rows", response_model=list[ProspectOut])
async def job_rows(
    job_id: str,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[ProspectOut]:
    job = await mongo.jobs().find_one({"_id": job_id})
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    query: dict = {"upload_id": job["upload_id"]}
    if status_filter:
        query[STATUS_FIELD[JobType(job["type"])]] = status_filter

    cursor = mongo.prospects().find(query).sort("row_index", 1).skip(skip).limit(min(limit, 200))
    return [_prospect_out(doc) async for doc in cursor]
