from datetime import datetime

from pydantic import BaseModel, Field

from app.models.common import Channel, Doc, Identity, RowStatus, utcnow


class SourceResult(BaseModel):
    """Outcome of one scraping source for one prospect.

    Every source writes one of these whether it succeeded or not, so a dead
    source is visible in the export rather than silently absent.
    """

    key: str
    ok: bool
    content: str | None = None
    meta: dict = Field(default_factory=dict)
    error: str | None = None
    fetched_at: datetime = Field(default_factory=utcnow)
    from_cache: bool = False


class Fact(BaseModel):
    """A single researched claim, tagged with the source it came from."""

    text: str
    source_key: str


class Dossier(BaseModel):
    """Stage 1 output."""

    summary: str = ""
    facts: list[Fact] = Field(default_factory=list)
    recent_events: list[Fact] = Field(default_factory=list)
    tech_signals: list[Fact] = Field(default_factory=list)


class Angle(BaseModel):
    """Stage 2 output. `evidence` must quote a fact from the dossier."""

    angle: str
    evidence: str
    source_key: str


class Draft(BaseModel):
    """Stage 3 output."""

    subject: str | None = None
    body: str = ""


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def add(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens
            + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
        )


class Personalization(BaseModel):
    channel: Channel | None = None
    dossier: Dossier | None = None
    angles: list[Angle] = Field(default_factory=list)
    draft: Draft | None = None
    model: str | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    prompt_versions: dict[str, int] = Field(default_factory=dict)
    template_version: int | None = None
    generated_at: datetime | None = None
    # Set when stage 3 output violated the template constraints even after a re-ask.
    constraint_warning: str | None = None


class Prospect(Doc):
    upload_id: str
    row_index: int
    raw: dict[str, str] = Field(default_factory=dict)
    identity: Identity = Field(default_factory=Identity)

    research: dict[str, SourceResult] = Field(default_factory=dict)
    researched_at: datetime | None = None
    scrape_status: RowStatus = RowStatus.pending
    scrape_error: str | None = None

    personalization: Personalization = Field(default_factory=Personalization)
    personalize_status: RowStatus = RowStatus.pending
    personalize_error: str | None = None


class ProspectOut(BaseModel):
    id: str
    row_index: int
    identity: Identity
    scrape_status: RowStatus
    personalize_status: RowStatus
    scrape_error: str | None = None
    personalize_error: str | None = None
    # key -> ok, for the status chips in the job detail table
    sources: dict[str, bool] = Field(default_factory=dict)
    subject: str | None = None
    body: str | None = None
    angle: str | None = None
    evidence: str | None = None
    cost_usd: float = 0.0
