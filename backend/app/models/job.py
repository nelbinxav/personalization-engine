from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.common import Channel, Doc


class JobType(str, Enum):
    scrape = "scrape"
    personalize = "personalize"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"
    # Claude credential died mid-run. Rows keep their progress; re-connecting
    # and resuming picks up where it stopped instead of restarting.
    blocked_auth = "blocked_auth"
    # Claude asked us to wait (a plan usage window, or repeated rate limits).
    # Unlike blocked_auth nobody has to do anything: the worker re-queues the
    # unfinished rows by itself once `resume_at` passes.
    rate_limited = "rate_limited"


class JobCounts(BaseModel):
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def finished(self) -> int:
        return self.done + self.failed + self.skipped


class JobOptions(BaseModel):
    sources: list[str] = Field(default_factory=list)
    channel: Channel | None = None
    template_id: str | None = None
    prompt_ids: dict[str, str] = Field(default_factory=dict)
    concurrency: int = 4
    # Re-run rows that already have a result instead of skipping them.
    force: bool = False
    # Cap for a cheap trial run before committing the whole sheet.
    limit: int | None = None


class Job(Doc):
    type: JobType
    upload_id: str
    status: JobStatus = JobStatus.queued
    counts: JobCounts = Field(default_factory=JobCounts)
    options: JobOptions = Field(default_factory=JobOptions)
    error: str | None = None
    cost_usd: float = 0.0
    # All tokens the job's rows used, whatever the credential mode.
    tokens: int = 0
    # Each time the job paused for a limit: when, why, and when it resumed.
    limit_events: list[dict] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Only set while status is rate_limited.
    resume_at: datetime | None = None


class CreateJobRequest(BaseModel):
    upload_id: str
    type: JobType
    options: JobOptions = Field(default_factory=JobOptions)


class JobOut(BaseModel):
    id: str
    type: JobType
    upload_id: str
    upload_name: str | None = None
    status: JobStatus
    counts: JobCounts
    options: JobOptions
    error: str | None = None
    cost_usd: float = 0.0
    created_at: object
    started_at: datetime | None = None
    finished_at: datetime | None = None
    resume_at: datetime | None = None
    tokens: int = 0
    limit_events: list[dict] = Field(default_factory=list)
