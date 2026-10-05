from datetime import datetime
from typing import Any

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
    # What the item is (own_post, repost, tech_uses, ...). Empty on older rows.
    kind: str = ""


class Dossier(BaseModel):
    """Stage 1 output."""

    summary: str = ""
    facts: list[Fact] = Field(default_factory=list)
    recent_events: list[Fact] = Field(default_factory=list)
    tech_signals: list[Fact] = Field(default_factory=list)
    # Stage 1's own verdict on whether anything it found is worth looking for
    # an angle in. False skips stage 2. True by default so rows written before
    # this existed read as they always did.
    has_signal: bool = True
    signal_note: str = ""
    # Why this person should not be contacted as addressed, when a source says
    # so (left the company, died, company gone). Empty when there is no issue.
    contact_issue: str = ""


class Angle(BaseModel):
    """Stage 2 output. `evidence` must quote a fact from the dossier."""

    angle: str
    evidence: str
    source_key: str


class Draft(BaseModel):
    """Stage 3 output."""

    subject: str | None = None
    body: str = ""
    # The one line the model wrote, when the template has a slot. Kept apart
    # from the body so a sending tool can take just this as a custom variable.
    personal_line: str | None = None


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
    # The same usage split by stage number, to show where a row's tokens went.
    usage_by_stage: dict[str, Usage] = Field(default_factory=dict)
    cost_usd: float = 0.0
    prompt_versions: dict[str, int] = Field(default_factory=dict)
    template_version: int | None = None
    generated_at: datetime | None = None
    # Set when stage 3 output violated the template constraints even after a re-ask.
    constraint_warning: str | None = None
    # Whether the research showed the prospect has the problem we solve (for
    # example that they run the platform we cut costs on), with the dossier item
    # that showed it. None when stage 2 did not run.
    fit_established: bool | None = None
    fit_evidence: str | None = None
    # True when the template's ask-first copy was used instead of the main copy.
    ask_first: bool = False
    # "personalized_line" when only the line was written (no message, no template
    # copy). Rows written before this existed read as full messages.
    output_mode: str = "full_message"
    # Per-row counts and flags for comparing configurations (tokens, retries,
    # whether stage 4 ran). Only written when line mode or compact research is
    # on; never holds text. See chain.run_chain and scripts/summarize_test.py.
    metrics: dict[str, Any] = Field(default_factory=dict)


class Prospect(Doc):
    upload_id: str
    row_index: int
    raw: dict[str, str] = Field(default_factory=dict)
    identity: Identity = Field(default_factory=Identity)

    research: dict[str, SourceResult] = Field(default_factory=dict)
    researched_at: datetime | None = None
    scrape_status: RowStatus = RowStatus.pending
    scrape_error: str | None = None
    # Research did not wait for LinkedIn: these sources are still to be read by
    # the background check (worker/linkedin_backfill.py), oldest request first.
    linkedin_pending: bool = False
    linkedin_pending_keys: list[str] = Field(default_factory=list)
    linkedin_pending_at: datetime | None = None

    personalization: Personalization = Field(default_factory=Personalization)
    personalize_status: RowStatus = RowStatus.pending
    personalize_error: str | None = None


def outreach_of(prospect: "Prospect") -> str:
    """What to do with a row once it has been personalized, in one word.

      personalised  a line was written for this lead; send it
      generic       no personal line, but the approved copy is there; send it
      hold          do not send until someone has looked (see the status note)

    Empty for a row that has not been personalized yet.
    """
    status = prospect.personalize_status
    if status in (RowStatus.pending, RowStatus.queued, RowStatus.running, RowStatus.skipped):
        return ""
    if prospect.personalization.output_mode == "personalized_line":
        # No message exists in this mode: the line, or nothing. A blank line is
        # sent without personalization; only a contact in doubt is held.
        if status in (RowStatus.failed, RowStatus.needs_review):
            return "hold"
        draft = prospect.personalization.draft
        return "personalised" if draft and (draft.personal_line or "").strip() else "generic"
    draft = prospect.personalization.draft
    if status in (RowStatus.failed, RowStatus.needs_review) or not draft or not draft.body.strip():
        return "hold"
    return "generic" if status is RowStatus.thin_context else "personalised"


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
    # personalised / generic / hold, see `outreach_of`.
    outreach: str = ""
    cost_usd: float = 0.0
