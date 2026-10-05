"""Structured-output schemas for the chain's stages.

These are passed to `client.messages.parse(output_format=...)`, so the worker
never parses prose and a malformed generation surfaces as a validation error
rather than as a corrupt CSV cell.
"""
from typing import Literal

from pydantic import BaseModel, Field


FactKind = Literal[
    "own_post", "repost", "podcast", "tech_uses", "tech_sells", "tech_talks", "event", "other"
]


class FactOut(BaseModel):
    text: str
    source_key: str
    kind: FactKind


class DossierOut(BaseModel):
    """Stage 1. Descriptions are kept out of the schema because the schema is
    re-sent on every call; the rules live in the cached stage 1 prompt."""

    summary: str
    facts: list[FactOut]
    contact_issue: str
    has_signal: bool
    signal_note: str


# With ai.compact_research on, stage 1 also labels the items that are kept as
# facts but cannot by themselves make has_signal true. See chain.WEAK_KINDS.
WeakKind = Literal["funding", "award", "earnings", "partnership", "customer_stack", "certification"]
WEAK_KINDS = frozenset(WeakKind.__args__)
FactKindStrict = Literal[
    "own_post", "repost", "podcast", "tech_uses", "tech_sells", "tech_talks", "event", "other",
    "funding", "award", "earnings", "partnership", "customer_stack", "certification",
]


class FactStrictOut(FactOut):
    kind: FactKindStrict


class DossierStrictOut(DossierOut):
    facts: list[FactStrictOut]


class AngleOut(BaseModel):
    angle: str
    evidence: str
    source_key: str


class FinalOut(BaseModel):
    """Stages 2 and 3 in one call, for a template with a {{personalization}} slot.
    The model writes only the slot; the code places it in the approved copy."""

    angles: list[AngleOut]
    sufficient: bool
    reason: str
    fit_established: bool
    fit_evidence: str
    personalization: str
    subject: str | None


class LineOut(BaseModel):
    """Stage 4 in ai.personalization_output_mode = "personalized_line": the same
    judgement as FinalOut, but the only copy written is the one line."""

    angles: list[AngleOut]
    sufficient: bool
    reason: str
    fit_established: bool
    fit_evidence: str
    personalized_line: str


class AnglesOut(BaseModel):
    """Stage 2 (three-call chain)."""

    angles: list[AngleOut] = Field(
        default_factory=list,
        description="One or two angles. Return an empty list if the research does not support "
        "any specific, non-generic angle.",
    )
    sufficient: bool = Field(
        description="False if the research is too thin to personalize honestly. Setting this "
        "false is strongly preferred over inventing a plausible-sounding angle."
    )
    reason: str = Field(
        default="", description="If sufficient is false, one line on what was missing."
    )
    fit_established: bool = Field(
        description="True only if a dossier item shows this company itself has the problem "
        "our offer solves: it runs the platform or technology the offer targets, or is "
        "hiring people to work on it in its own team. Being on our list, the prospect's "
        "role or industry, selling services around the technology, and writing about it do "
        "not count. When unsure, false."
    )
    fit_evidence: str = Field(
        default="",
        description="If fit_established is true, the exact dossier item that shows it. "
        "Otherwise an empty string.",
    )


class DraftOut(BaseModel):
    """Stage 3."""

    subject: str | None = Field(
        default=None, description="Email subject line. Null for LinkedIn and WhatsApp."
    )
    body: str = Field(description="The message body, ready to send, with no placeholders left.")


class SlotOut(BaseModel):
    """Stage 3 when the template has a {{personalization}} slot: the model writes
    only the slot and the code places it into the approved copy."""

    personalization: str = Field(
        description="Only the text that replaces {{personalization}}. No greeting, "
        "no sign-off and no other template copy."
    )
    subject: str | None = Field(
        default=None,
        description="Subject line, only when the template does not fix one. Otherwise null.",
    )


def strict_schema(model: type[BaseModel]) -> dict:
    """Turn a pydantic model into a schema the API's json_schema format accepts.

    Two transforms are needed on top of `model_json_schema()`:
      * `$ref`/`$defs` are inlined, since nested models otherwise emit references.
      * every object gets `additionalProperties: false` and a `required` list
        covering all of its properties, which strict JSON schema demands.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref_name = node["$ref"].rsplit("/", 1)[-1]
            target = defs.get(ref_name, {})
            # Merge any sibling keys (e.g. description) over the resolved target.
            merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            return resolve(merged)

        resolved = {key: resolve(value) for key, value in node.items()}
        if resolved.get("type") == "object" and "properties" in resolved:
            resolved["additionalProperties"] = False
            resolved["required"] = list(resolved["properties"].keys())
        return resolved

    return resolve(schema)
