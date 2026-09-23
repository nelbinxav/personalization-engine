from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    """Document ids are uuid4 hex strings, not ObjectIds.

    Ids travel through arq job payloads and URLs constantly; strings keep that
    friction-free and avoid pydantic/bson serialization dances everywhere.
    """
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Doc(BaseModel):
    """Base for anything persisted. Serializes `id` to mongo's `_id`."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=new_id, alias="_id")
    created_at: datetime = Field(default_factory=utcnow)

    def to_mongo(self) -> dict:
        return self.model_dump(by_alias=True)


class Channel(str, Enum):
    linkedin = "linkedin"
    email = "email"
    whatsapp = "whatsapp"


class RowStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"
    # Generated, but nothing solid to personalize on -- needs a human look.
    thin_context = "thin_context"


class Identity(BaseModel):
    """Canonical prospect fields that every column mapping targets.

    Adding a field here automatically flows to the mapping UI, the scrapers and
    the exporter -- see `app.ingest.mapping.IDENTITY_FIELDS`.
    """

    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    company: str | None = None
    website: str | None = None
    linkedin_url: str | None = None
    linkedin_company_url: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None

    @property
    def display_name(self) -> str:
        if self.full_name:
            return self.full_name
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) if parts else (self.email or "unknown")
