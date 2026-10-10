from pydantic import BaseModel, Field

from app.models.common import Doc
from app.models.settings import OutputMode


class Objection(BaseModel):
    objection: str = ""
    response: str = ""


class AgentProfile(BaseModel):
    """What the agent knows about one offer, trained in chat and editable."""

    offer: str = ""
    what_we_do: str = ""
    icp: str = ""
    proof_points: list[str] = Field(default_factory=list)
    voice: str = ""
    sample_messages: list[str] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    qualification: str = ""
    booking_link: str = ""
    never_claim: list[str] = Field(default_factory=list)
    # The campaign's own vocabulary; the trainer fills it from the conversation.
    relevance_terms: list[str] = Field(default_factory=list)
    # How this agent's jobs write and research. Set on the Agents page, not by
    # the trainer. They replace the global defaults for a job run with this agent.
    output_mode: OutputMode = OutputMode.full_message
    compact_research: bool = False


class Agent(Doc):
    """Append-only like prompts: each save is a new version of the lineage, so an
    export can be traced to the exact profile that produced it.
    """

    lineage_id: str
    name: str
    profile: AgentProfile = Field(default_factory=AgentProfile)
    version: int = 1
    is_active: bool = False
    created_by: str | None = None


class AgentIn(BaseModel):
    # Omit to start a new agent; set to add a version to an existing one.
    lineage_id: str | None = None
    name: str
    profile: AgentProfile = Field(default_factory=AgentProfile)
    activate: bool = True


class AgentOut(BaseModel):
    id: str
    lineage_id: str
    name: str
    profile: AgentProfile
    version: int
    is_active: bool
    created_at: object
