from pydantic import BaseModel, Field

from app.models.common import Channel, Doc


class Constraints(BaseModel):
    max_chars: int | None = None
    has_subject: bool = False
    subject_max_chars: int | None = None


# Channel defaults. LinkedIn's 300 is the connection-note limit -- the tightest
# real constraint in the system and the one most worth enforcing.
CHANNEL_DEFAULTS: dict[Channel, Constraints] = {
    Channel.linkedin: Constraints(max_chars=300),
    Channel.email: Constraints(max_chars=1200, has_subject=True, subject_max_chars=78),
    Channel.whatsapp: Constraints(max_chars=600),
}


class Template(Doc):
    channel: Channel
    name: str
    body: str
    # Approved copy for a row whose research does not show the prospect has the
    # problem we solve: it asks instead of assuming. Empty means there is only
    # one version of the copy. May carry a {{personalization}} slot of its own.
    fallback_body: str = ""
    constraints: Constraints = Field(default_factory=Constraints)
    version: int = 1
    is_active: bool = False


class TemplateIn(BaseModel):
    channel: Channel
    name: str
    body: str
    fallback_body: str = ""
    constraints: Constraints | None = None
    activate: bool = True


class TemplateOut(BaseModel):
    id: str
    channel: Channel
    name: str
    body: str
    fallback_body: str = ""
    constraints: Constraints
    version: int
    is_active: bool
    created_at: object
