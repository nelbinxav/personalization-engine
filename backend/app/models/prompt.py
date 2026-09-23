from enum import IntEnum

from pydantic import BaseModel, Field

from app.models.common import Doc


class Stage(IntEnum):
    dossier = 1
    angle = 2
    draft = 3


STAGE_LABELS = {
    Stage.dossier: "Dossier - condense scraped context into tagged facts",
    Stage.angle: "Angle - pick personalization angles, each citing a fact",
    Stage.draft: "Draft - write the message into the template",
}


class Prompt(Doc):
    """Prompts are append-only. Editing creates a new version; the old one stays
    so an export can always be traced back to the exact prompt that produced it.
    """

    stage: Stage
    name: str
    body: str
    version: int = 1
    is_active: bool = False
    created_by: str | None = None


class PromptIn(BaseModel):
    stage: Stage
    name: str
    body: str
    activate: bool = True


class PromptOut(BaseModel):
    id: str
    stage: Stage
    name: str
    body: str
    version: int
    is_active: bool
    created_at: object
