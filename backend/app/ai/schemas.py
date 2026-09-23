"""Structured-output schemas for the three stages.

These are passed to `client.messages.parse(output_format=...)`, so the worker
never parses prose and a malformed generation surfaces as a validation error
rather than as a corrupt CSV cell.
"""
from pydantic import BaseModel, Field


class FactOut(BaseModel):
    text: str = Field(description="One specific, verifiable fact about the prospect or company.")
    source_key: str = Field(
        description="Which source this came from: website, rss, news, "
        "linkedin_profile or linkedin_company."
    )


class DossierOut(BaseModel):
    """Stage 1."""

    summary: str = Field(description="Two or three sentences on who this company is and what they do.")
    facts: list[FactOut] = Field(default_factory=list, description="Durable facts.")
    recent_events: list[FactOut] = Field(
        default_factory=list,
        description="Things that happened recently: funding, launches, hires, press, posts.",
    )
    tech_signals: list[FactOut] = Field(
        default_factory=list,
        description="Technology, tooling or platform signals visible in the sources.",
    )


class AngleOut(BaseModel):
    angle: str = Field(description="The personalization angle, in one sentence.")
    evidence: str = Field(
        description="The exact fact from the dossier this rests on. Quote it; do not paraphrase "
        "into something the sources do not support."
    )
    source_key: str = Field(description="Which source the evidence came from.")


class AnglesOut(BaseModel):
    """Stage 2."""

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


class DraftOut(BaseModel):
    """Stage 3."""

    subject: str | None = Field(
        default=None, description="Email subject line. Null for LinkedIn and WhatsApp."
    )
    body: str = Field(description="The message body, ready to send, with no placeholders left.")


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
