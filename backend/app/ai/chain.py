"""The three-stage personalization chain.

  1 Dossier  raw scraped text      -> structured facts, each tagged with a source
  2 Angle    dossier + our offer   -> 1-2 angles, each citing a fact
  3 Draft    angle + template      -> the message

Stage 2's forced citation is the anti-hallucination guard. An angle that cannot
quote a scraped fact is dropped, and the row comes back flagged `thin_context`
rather than carrying an invented compliment out to a real prospect.

Caching: each stage's system prompt is identical for every row in a job, so it
carries a cache breakpoint and the per-prospect content goes in the user turn.
Across a 500-row sheet that is the difference between paying full input price
500 times and paying it once. If an operator puts a per-prospect placeholder in
the prompt body, the prefix varies per row and caching silently stops working --
`cacheable` tracks that so the UI can explain a zero hit rate.
"""
import json
import logging
import re
from dataclasses import dataclass, field

import anthropic

from app.ai import pricing
from app.ai.client import AuthUnavailable, get_client
from app.ai.schemas import AnglesOut, DossierOut, DraftOut, strict_schema
from app.models.common import Channel, Identity
from app.models.prompt import Stage
from app.models.prospect import Angle, Dossier, Draft, Fact, Personalization, SourceResult, Usage
from app.models.settings import AppSettings
from app.models.template import Constraints, Template

logger = logging.getLogger(__name__)

# Placeholders whose value differs per prospect. Their presence in a prompt body
# means that stage's prefix cannot be cached.
_VOLATILE_TOKEN = re.compile(r"\{\{\s*(research|dossier|angles|identity\.[\w]+|raw\.[^}]+)\s*\}\}")
_ANY_TOKEN = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


class ChainError(Exception):
    """A stage failed in a way that should mark the row failed."""


class RefusalError(ChainError):
    """Claude declined the request (stop_reason == "refusal")."""


@dataclass
class StageResult:
    parsed: dict
    usage: Usage
    cacheable: bool
    cache_hit: bool


@dataclass
class ChainOutput:
    personalization: Personalization
    thin_context: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Placeholder rendering
# --------------------------------------------------------------------------


def render(text: str, context: dict[str, str]) -> str:
    """Substitute {{token}} placeholders. Unknown tokens are left untouched so a
    typo is visible in the output rather than silently blanking a line.
    """

    def replace(match: re.Match) -> str:
        token = match.group(1).strip()
        return context.get(token, match.group(0))

    return _ANY_TOKEN.sub(replace, text)


def build_context(
    identity: Identity,
    raw: dict[str, str],
    settings: AppSettings,
    **extra: str,
) -> dict[str, str]:
    context: dict[str, str] = {"offer_context": settings.offer_context or "(not configured)"}
    for field_name, value in identity.model_dump().items():
        context[f"identity.{field_name}"] = value or ""
    for column, value in raw.items():
        context[f"raw.{column}"] = value or ""
    context.update(extra)
    return context


def _split_stable(body: str, context: dict[str, str]) -> tuple[str, bool]:
    """Render a prompt body and report whether it is still cacheable.

    A body with no per-prospect placeholders renders identically for every row,
    so it can sit behind a cache breakpoint.
    """
    cacheable = not _VOLATILE_TOKEN.search(body)
    return render(body, context), cacheable


# --------------------------------------------------------------------------
# Per-prospect payloads (the volatile half, always in the user turn)
# --------------------------------------------------------------------------


def format_research(research: dict[str, SourceResult]) -> str:
    if not research:
        return "(no research was collected for this prospect)"

    blocks: list[str] = []
    for key, result in research.items():
        if result.ok and result.content:
            blocks.append(f"### source: {key}\n{result.content}")
        else:
            blocks.append(f"### source: {key}\n(unavailable: {result.error or 'no content'})")
    return "\n\n".join(blocks)


def format_dossier(dossier: Dossier) -> str:
    lines = [f"Summary: {dossier.summary}"]
    for label, facts in (
        ("Facts", dossier.facts),
        ("Recent events", dossier.recent_events),
        ("Tech signals", dossier.tech_signals),
    ):
        if facts:
            lines.append(
                f"\n{label}:\n"
                + "\n".join(f"- {fact.text}  [source: {fact.source_key}]" for fact in facts)
            )
    return "\n".join(lines)


def format_angles(angles: list[Angle]) -> str:
    if not angles:
        return "(no angle available)"
    return "\n\n".join(
        f"Angle: {a.angle}\nEvidence: {a.evidence}  [source: {a.source_key}]" for a in angles
    )


def format_constraints(constraints: Constraints, channel: Channel) -> str:
    lines = [f"Channel: {channel.value}"]
    if constraints.max_chars:
        lines.append(f"Body must be at most {constraints.max_chars} characters. This is a hard limit.")
    if constraints.has_subject:
        limit = constraints.subject_max_chars or 78
        lines.append(f"Include a subject line of at most {limit} characters.")
    else:
        lines.append("Do not include a subject line; return null for subject.")
    return "\n".join(lines)


def prospect_block(identity: Identity, **sections: str) -> str:
    lines = [
        "PROSPECT",
        f"Name: {identity.display_name}",
        f"Title: {identity.title or '(unknown)'}",
        f"Company: {identity.company or '(unknown)'}",
    ]
    for heading, content in sections.items():
        lines.append(f"\n{heading.upper().replace('_', ' ')}\n{content}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# API call
# --------------------------------------------------------------------------


async def call_stage(
    client: anthropic.AsyncAnthropic,
    *,
    system_text: str,
    user_text: str,
    schema_model,
    model: str,
    effort: str,
    max_tokens: int,
    cacheable: bool,
) -> StageResult:
    system_block: dict = {"type": "text", "text": system_text}
    if cacheable:
        # 1h TTL: a job over a few hundred rows runs well past the 5-minute default.
        system_block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[system_block],
            messages=[{"role": "user", "content": user_text}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": strict_schema(schema_model)},
            },
        )
    except anthropic.AuthenticationError as exc:
        raise AuthUnavailable(f"Claude rejected the credential: {exc}") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AuthUnavailable(f"Claude credential lacks permission: {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise ChainError(f"Model '{model}' not found or not available to this account: {exc}") from exc
    except anthropic.RateLimitError as exc:
        # arq retries the row; surfacing it as a ChainError would waste the attempt.
        raise
    except anthropic.APIStatusError as exc:
        raise ChainError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ChainError(f"Could not reach the Claude API: {exc}") from exc

    # A refusal is an HTTP 200, so this has to be checked before reading content.
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise RefusalError(f"Claude declined this request (category: {category or 'unspecified'})")
    if response.stop_reason == "max_tokens":
        raise ChainError(
            f"Response hit the {max_tokens} token cap before finishing. "
            "Raise max_tokens in Settings or shorten the template."
        )

    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise ChainError("Claude returned no text content")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChainError(f"Claude returned invalid JSON: {exc}") from exc

    usage = pricing.usage_from_response(response)
    return StageResult(
        parsed=parsed,
        usage=usage,
        cacheable=cacheable,
        cache_hit=usage.cache_read_input_tokens > 0,
    )


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------


def _constraint_violations(draft: Draft, constraints: Constraints) -> list[str]:
    problems: list[str] = []
    if constraints.max_chars and len(draft.body) > constraints.max_chars:
        problems.append(
            f"Body is {len(draft.body)} characters; the limit is {constraints.max_chars}."
        )
    if constraints.has_subject:
        if not draft.subject:
            problems.append("A subject line is required but none was returned.")
        elif constraints.subject_max_chars and len(draft.subject) > constraints.subject_max_chars:
            problems.append(
                f"Subject is {len(draft.subject)} characters; "
                f"the limit is {constraints.subject_max_chars}."
            )
    # An unresolved placeholder in a sent message is worse than a long one.
    leftover = _ANY_TOKEN.findall(draft.body)
    if leftover:
        problems.append(f"Unresolved placeholders left in the body: {', '.join(leftover)}")
    return problems


async def run_chain(
    identity: Identity,
    raw: dict[str, str],
    research: dict[str, SourceResult],
    prompts: dict[int, str],
    template: Template,
    settings: AppSettings,
    channel: Channel,
) -> ChainOutput:
    client = await get_client()
    model = settings.ai.model
    max_tokens = settings.ai.max_tokens
    enabled = set(settings.ai.enabled_stages)

    usage_total = Usage()
    warnings: list[str] = []

    def effort_for(stage: Stage) -> str:
        return settings.ai.effort.get(str(int(stage)), "high")

    def accumulate(result: StageResult, stage: Stage) -> None:
        nonlocal usage_total
        usage_total = usage_total.add(result.usage)
        if result.cacheable and not result.cache_hit:
            logger.debug("Stage %s prefix was cacheable but missed", int(stage))
        if not result.cacheable:
            warnings.append(
                f"Stage {int(stage)} prompt contains a per-prospect placeholder, so its prefix "
                "cannot be cached. Move per-prospect references out of the prompt body to cut cost."
            )

    base_context = build_context(identity, raw, settings)

    # --- Stage 1: dossier -------------------------------------------------
    dossier = Dossier()
    if int(Stage.dossier) in enabled:
        system_text, cacheable = _split_stable(prompts[int(Stage.dossier)], base_context)
        user_text = prospect_block(identity, research=format_research(research))
        result = await call_stage(
            client,
            system_text=system_text,
            user_text=user_text,
            schema_model=DossierOut,
            model=model,
            effort=effort_for(Stage.dossier),
            max_tokens=max_tokens,
            cacheable=cacheable,
        )
        accumulate(result, Stage.dossier)
        parsed = DossierOut.model_validate(result.parsed)
        dossier = Dossier(
            summary=parsed.summary,
            facts=[Fact(text=f.text, source_key=f.source_key) for f in parsed.facts],
            recent_events=[Fact(text=f.text, source_key=f.source_key) for f in parsed.recent_events],
            tech_signals=[Fact(text=f.text, source_key=f.source_key) for f in parsed.tech_signals],
        )
    else:
        # Stage 1 off: hand the raw research straight to stage 2.
        dossier = Dossier(summary=format_research(research))

    dossier_text = format_dossier(dossier)

    # --- Stage 2: angle ---------------------------------------------------
    angles: list[Angle] = []
    thin_context = False
    reason = ""

    if int(Stage.angle) in enabled:
        context = {**base_context, "dossier": dossier_text}
        system_text, cacheable = _split_stable(prompts[int(Stage.angle)], context)
        user_text = prospect_block(identity, dossier=dossier_text)
        result = await call_stage(
            client,
            system_text=system_text,
            user_text=user_text,
            schema_model=AnglesOut,
            model=model,
            effort=effort_for(Stage.angle),
            max_tokens=max_tokens,
            cacheable=cacheable,
        )
        accumulate(result, Stage.angle)
        parsed = AnglesOut.model_validate(result.parsed)

        # Drop angles whose evidence does not point at a real source.
        known_sources = set(research.keys()) | {"website", "rss", "news", "linkedin_profile", "linkedin_company"}
        angles = [
            Angle(angle=a.angle, evidence=a.evidence, source_key=a.source_key)
            for a in parsed.angles
            if a.angle.strip() and a.evidence.strip() and a.source_key in known_sources
        ]

        if not parsed.sufficient or not angles:
            thin_context = True
            reason = parsed.reason or "The research did not support a specific angle."

    if thin_context:
        # Stop before stage 3. Generating anyway is exactly the failure mode the
        # citation guard exists to prevent.
        return ChainOutput(
            personalization=Personalization(
                channel=channel,
                dossier=dossier,
                angles=angles,
                model=model,
                usage=usage_total,
                cost_usd=pricing.cost_usd(model, usage_total),
                template_version=template.version,
            ),
            thin_context=True,
            reason=reason,
            warnings=warnings,
        )

    # --- Stage 3: draft ---------------------------------------------------
    angles_text = format_angles(angles)
    constraints_text = format_constraints(template.constraints, channel)
    # Deliberately NOT rendered: the template keeps its {{identity.first_name}}
    # placeholders so the stage-3 prefix stays identical across every row (and
    # therefore cacheable). The model fills them from the PROSPECT block in the
    # user turn, and `_constraint_violations` catches any it leaves behind.
    template_text = template.body

    context = {
        **base_context,
        "dossier": dossier_text,
        "angles": angles_text,
        "template": template_text,
        "constraints": constraints_text,
    }
    system_text, cacheable = _split_stable(prompts[int(Stage.draft)], context)
    user_text = prospect_block(identity, angle=angles_text, dossier=dossier_text)

    result = await call_stage(
        client,
        system_text=system_text,
        user_text=user_text,
        schema_model=DraftOut,
        model=model,
        effort=effort_for(Stage.draft),
        max_tokens=max_tokens,
        cacheable=cacheable,
    )
    accumulate(result, Stage.draft)
    parsed_draft = DraftOut.model_validate(result.parsed)
    draft = Draft(subject=parsed_draft.subject, body=parsed_draft.body)

    # One bounded re-ask on a constraint violation, then accept and flag.
    violations = _constraint_violations(draft, template.constraints)
    constraint_warning = None
    if violations:
        retry_text = (
            user_text
            + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED\n"
            + "\n".join(f"- {problem}" for problem in violations)
            + "\n\nRewrite it. Keep the same angle and voice; fix these problems exactly."
        )
        retry = await call_stage(
            client,
            system_text=system_text,
            user_text=retry_text,
            schema_model=DraftOut,
            model=model,
            effort=effort_for(Stage.draft),
            max_tokens=max_tokens,
            cacheable=cacheable,
        )
        accumulate(retry, Stage.draft)
        retried = DraftOut.model_validate(retry.parsed)
        retried_draft = Draft(subject=retried.subject, body=retried.body)

        remaining = _constraint_violations(retried_draft, template.constraints)
        if remaining:
            # Keep the better of the two rather than discarding the work.
            draft = retried_draft if len(remaining) < len(violations) else draft
            constraint_warning = "; ".join(remaining)
            logger.warning("Constraints still violated after re-ask: %s", constraint_warning)
        else:
            draft = retried_draft

    return ChainOutput(
        personalization=Personalization(
            channel=channel,
            dossier=dossier,
            angles=angles,
            draft=draft,
            model=model,
            usage=usage_total,
            cost_usd=pricing.cost_usd(model, usage_total),
            template_version=template.version,
            constraint_warning=constraint_warning,
        ),
        warnings=warnings,
    )
