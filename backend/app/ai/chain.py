"""The personalization chain.

  1 Dossier  raw scraped text      -> structured facts, each tagged with a source
  2 Angle    dossier + our offer   -> 1-2 angles, each citing a fact
  3 Draft    angle + template      -> the message

With `ai.combined_final` on and a slot template, 2 and 3 are one call (stage 4:
angles, fit and the slot text together), so a row costs two calls, not three.
Everything the model claims is then checked in code (`grounding.py`): facts
against their source text, angles and fit against the facts.

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

from app.ai import claude_code, grounding, openai_stage, pricing
from app.ai.client import AuthUnavailable, get_client
from app.ai.line_prompt import LINE_PROMPT
from app.ai.research_select import select_paragraphs
from app.ai.schemas import (
    WEAK_KINDS,
    AnglesOut,
    DossierOut,
    DossierStrictOut,
    DraftOut,
    FinalOut,
    LineOut,
    SlotOut,
    strict_schema,
)
from app.models.common import Channel, Identity
from app.models.prompt import Stage
from app.models.prospect import Angle, Dossier, Draft, Fact, Personalization, SourceResult, Usage
from app.models.settings import AppSettings, CredentialMode, OutputMode
from app.models.template import Constraints, Template
from app.sources.registry import ALL_SOURCES

logger = logging.getLogger(__name__)

# Placeholders whose value differs per prospect. Their presence in a prompt body
# means that stage's prefix cannot be cached.
_VOLATILE_TOKEN = re.compile(r"\{\{\s*(research|dossier|angles|identity\.[\w]+|raw\.[^}]+)\s*\}\}")
_ANY_TOKEN = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
_TEMPLATE_TOKEN = re.compile(r"\{\{\s*template\s*\}\}")
_OFFER_TOKEN = re.compile(r"\{\{\s*offer_context\s*\}\}")
# A template carrying this slot is approved copy: the model writes only the
# slot, and every other character, including the sending tool's own merge tags
# such as {{firstName|there}}, goes out exactly as written.
_SLOT = re.compile(r"\{\{\s*personali[sz]ation\s*\}\}")
_SLOT_LINE = re.compile(
    r"^[ \t]*\{\{\s*personali[sz]ation\s*\}\}[ \t]*(?:\r?\n|\Z)(?:[ \t]*\r?\n)?", re.MULTILINE
)
_SUBJECT_LINE = re.compile(r"\A\s*subject\s*:[ \t]*(.*?)[ \t]*(?:\r?\n|\Z)", re.IGNORECASE)


class ChainError(Exception):
    """A stage failed in a way that should mark the row failed."""


class RefusalError(ChainError):
    """Claude declined the request (stop_reason == "refusal")."""


class RateLimited(Exception):
    """Claude is rate-limiting us, overloaded or unreachable, after the SDK's
    own retries. Not a ChainError: the row did nothing wrong, so the worker
    tries it again later instead of marking it failed.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None


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
    # Not to be sent until a person has looked (the contact itself is in doubt).
    hold: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Placeholder rendering
# --------------------------------------------------------------------------


def render(text: str, context: dict[str, str]) -> str:
    """Substitute {{token}} placeholders. Unknown tokens are left untouched so a
    typo is visible in the output rather than silently blanking a line.

    `{{token|fallback}}` uses the fallback when the token is known but empty.
    """

    def replace(match: re.Match) -> str:
        name, has_fallback, fallback = match.group(1).partition("|")
        name = name.strip()
        if name not in context:
            return match.group(0)
        value = context[name]
        if has_fallback and not value.strip():
            return fallback.strip()
        return value

    return _ANY_TOKEN.sub(replace, text)


# Sending-tool merge tags the app can fill from the prospect's own row, so a
# message reads right wherever it is pasted. {{sendingAccountFirstName}} is not
# here: only the sending tool knows which inbox sends it.
_MERGE_TAGS = {
    "firstName": lambda c: c.get("identity.first_name")
    or (c.get("identity.full_name") or "").split(" ")[0],
    "lastName": lambda c: c.get("identity.last_name", ""),
    "companyName": lambda c: c.get("identity.company", ""),
}


def render_copy(text: str, context: dict[str, str]) -> str:
    """Render approved template copy: the app's own tokens plus the merge tags."""
    merged = {**context, **{tag: value(context) or "" for tag, value in _MERGE_TAGS.items()}}
    return render(text, merged)


def split_subject(template_body: str) -> tuple[str | None, str]:
    """Peel a leading "Subject: ..." line off a template."""
    match = _SUBJECT_LINE.match(template_body)
    if not match:
        return None, template_body
    return match.group(1) or None, template_body[match.end():].lstrip("\r\n")


def fill_slot(template_body: str, context: dict[str, str], text: str) -> str:
    """Place the model's text into the approved copy.

    The app's own tokens and the merge tags it can fill ({{firstName|there}})
    are rendered; anything else, like {{sendingAccountFirstName}}, survives
    untouched for the sending tool.
    """
    body = render_copy(template_body, context)
    return _SLOT.sub(lambda _: text.strip(), body)


def copy_for(template: Template, fit: bool | None) -> tuple[str, bool]:
    """Which approved copy a row gets, and whether it is the ask-first one.

    The main copy may assume the prospect has the problem we solve, so it only
    goes to rows where the research showed that. A row on the list without that
    evidence gets the template's ask-first copy, when it has one. `fit` is None
    when stage 2 did not run; that row gets the main copy as before.
    """
    if fit is False and template.fallback_body.strip():
        return template.fallback_body, True
    return template.body, False


def generic_draft(template_body: str, context: dict[str, str]) -> Draft | None:
    """The approved copy with the personalization left out, for a row whose
    research supported no angle. It says nothing about the prospect, so it
    cannot carry an invented fact; the row stays flagged for a human to decide.
    None when the template has no slot, because then all of it is model-written.
    """
    if not _SLOT.search(template_body):
        return None
    return fixed_draft(template_body, context)


def fixed_draft(template_body: str, context: dict[str, str]) -> Draft:
    """Approved copy rendered with no model text at all: any slot is dropped."""
    subject, body = split_subject(template_body)
    body = render_copy(body, context)
    # A slot on its own line goes with the blank line after it; an inline one
    # just disappears.
    body = _SLOT_LINE.sub("", body)
    body = _SLOT.sub("", body)
    return Draft(subject=render_copy(subject, context) if subject else None, body=body)


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


_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")
_EMPTY_BULLET = re.compile(r"^[ \t]*(?:[-*+]|\d+\.)?[ \t]*$\n?", re.MULTILINE)
# Bounded by the source itself (a handful of posts), and the best material we
# have, so it is never trimmed.
_UNCAPPED_SOURCES = {"linkedin_posts"}


def compact_source_text(text: str) -> str:
    """Drop what costs tokens and tells the model nothing: image tags, link
    targets (the link text stays) and the empty lines they leave behind. A
    scraped page is largely navigation, and its URLs are the bulk of that.
    """
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    text = _EMPTY_BULLET.sub("\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def funnel_view(research: dict[str, SourceResult]) -> dict[str, SourceResult]:
    """What the model should read: the best material found, and nothing below it.

    Research no longer waits for LinkedIn, so a row can hold a website and a
    recent post that arrived later. A recent post is the opener and a podcast
    is next, so the lower sources are left out: they would only cost tokens
    and tempt a weaker angle. The profile rides along; it says who they are.
    """

    def ok(key: str) -> bool:
        result = research.get(key)
        return bool(result and result.ok and (result.content or "").strip())

    for hook in ("linkedin_posts", "podcasts"):
        if ok(hook):
            return {k: v for k, v in research.items() if k in (hook, "linkedin_profile")}
    return research


def has_usable_research(research: dict[str, SourceResult]) -> bool:
    return any(r.ok and (r.content or "").strip() for r in research.values())


def research_texts(
    research: dict[str, SourceResult], max_chars: int | None = None, *, select=None
) -> dict[str, str]:
    """The text of each source that has any, as the model reads it, best first.
    `select` (text -> text) replaces the character cap, for ai.compact_research."""
    priority = {key: rank for rank, key in enumerate(ALL_SOURCES)}
    ordered = sorted(research.items(), key=lambda item: priority.get(item[0], len(priority)))
    texts: dict[str, str] = {}
    for key, result in ordered:
        if result.ok and result.content:
            content = compact_source_text(result.content)
            if select and key not in _UNCAPPED_SOURCES:
                content = select(content)
            elif max_chars and key not in _UNCAPPED_SOURCES and len(content) > max_chars:
                content = content[:max_chars].rstrip() + "\n[trimmed]"
            texts[key] = content
    return texts


def format_research(
    research: dict[str, SourceResult], max_chars: int | None = None, *, select=None
) -> str:
    """The research as the model sees it. `max_chars` caps each source after
    compaction; what is stored on the row and exported is left whole.
    """
    if not research:
        return "(no research was collected for this prospect)"

    # Best material first (see registry.ALL_SOURCES), whatever order it was
    # fetched or stored in.
    priority = {key: rank for rank, key in enumerate(ALL_SOURCES)}
    ordered = sorted(research.items(), key=lambda item: priority.get(item[0], len(priority)))
    texts = research_texts(research, max_chars, select=select)

    blocks: list[str] = []
    for key, result in ordered:
        if key in texts:
            blocks.append(f"### source: {key}\n{texts[key]}")
        else:
            blocks.append(f"### source: {key}\n(unavailable: {result.error or 'no content'})")
    return "\n\n".join(blocks)


def format_dossier(dossier: Dossier) -> str:
    lines = [f"Summary: {dossier.summary}"]
    items = [*dossier.facts, *dossier.recent_events, *dossier.tech_signals]
    if items:
        lines.append("\nItems:")
        for fact in items:
            kind = f"[{fact.kind}] " if fact.kind else ""
            lines.append(f"- {kind}{fact.text}  [source: {fact.source_key}]")
    return "\n".join(lines)


def format_angles(angles: list[Angle]) -> str:
    if not angles:
        return "(no angle available)"
    return "\n\n".join(
        f"Angle: {a.angle}\nEvidence: {a.evidence}  [source: {a.source_key}]" for a in angles
    )


def format_fit(fit: bool, evidence: str) -> str:
    if fit:
        return f"Established. The dossier shows it: {evidence}"
    return (
        "Not established. Nothing in the dossier shows this company uses the technology, "
        "or has the problem, that our offer targets. Being on our list is not evidence. "
        "Do not state or imply that they do; ask instead of assuming."
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


def format_slot_constraints(
    constraints: Constraints, channel: Channel, budget: int | None, fixed_subject: str | None
) -> str:
    lines = [
        f"Channel: {channel.value}",
        "Write only the text that replaces {{personalization}}. Every other line of the "
        "template is sent exactly as written, so do not reproduce, reword or add to it.",
    ]
    if budget:
        lines.append(f"Your text must be at most {budget} characters. This is a hard limit.")
    if fixed_subject:
        lines.append("The template fixes the subject line; return null for subject.")
    elif constraints.has_subject:
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
    client: anthropic.AsyncAnthropic | None,
    *,
    system_text: str,
    user_text: str,
    schema_model,
    model: str,
    effort: str,
    max_tokens: int,
    cacheable: bool,
) -> StageResult:
    if openai_stage.is_openai_model(model):
        try:
            parsed, usage = await openai_stage.run_stage(
                system_text=system_text,
                user_text=user_text,
                schema=strict_schema(schema_model),
                model=model,
                effort=effort,
                max_tokens=max_tokens,
            )
        except openai_stage.OpenAIBusy as exc:
            raise RateLimited(str(exc), exc.retry_after) from exc
        except openai_stage.OpenAIRefusal as exc:
            raise RefusalError(str(exc)) from exc
        except openai_stage.OpenAIError as exc:
            raise ChainError(str(exc)) from exc
        return StageResult(
            parsed=parsed,
            usage=usage,
            cacheable=cacheable,
            cache_hit=usage.cache_read_input_tokens > 0,
        )

    if client is None:
        # claude_code mode: the subscription, through the unmodified CLI.
        try:
            parsed, usage = await claude_code.run_stage(
                system_text=system_text,
                user_text=user_text,
                schema=strict_schema(schema_model),
                model=model,
                effort=effort,
            )
        except claude_code.ClaudeCodeError as exc:
            raise ChainError(str(exc)) from exc
        return StageResult(
            parsed=parsed,
            usage=usage,
            cacheable=cacheable,
            cache_hit=usage.cache_read_input_tokens > 0,
        )

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
        raise RateLimited(f"Claude rate limit reached: {exc.message}", _retry_after(exc)) from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            # Overloaded (529) or a server error: transient, same as a rate limit.
            raise RateLimited(
                f"Claude API is unavailable ({exc.status_code}): {exc.message}", _retry_after(exc)
            ) from exc
        raise ChainError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RateLimited(f"Could not reach the Claude API: {exc}") from exc

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


def stage_model(settings: AppSettings, stage: Stage) -> str:
    """The model a stage runs on: its own override, else the default model."""
    return settings.ai.stage_models.get(str(int(stage))) or settings.ai.model


def _subject_violations(subject: str | None, constraints: Constraints) -> list[str]:
    if not constraints.has_subject:
        return []
    if not subject:
        return ["A subject line is required but none was returned."]
    if constraints.subject_max_chars and len(subject) > constraints.subject_max_chars:
        return [
            f"Subject is {len(subject)} characters; the limit is {constraints.subject_max_chars}."
        ]
    return []


def _slot_violations(text: str, budget: int | None) -> list[str]:
    problems: list[str] = []
    if not text.strip():
        problems.append("The personalization text is empty.")
    if budget and len(text.strip()) > budget:
        problems.append(f"The personalization is {len(text.strip())} characters; the limit is {budget}.")
    leftover = _ANY_TOKEN.findall(text)
    if leftover:
        problems.append(f"Placeholders left in the personalization: {', '.join(leftover)}")
    return problems


def _constraint_violations(draft: Draft, constraints: Constraints) -> list[str]:
    problems: list[str] = []
    if constraints.max_chars and len(draft.body) > constraints.max_chars:
        problems.append(
            f"Body is {len(draft.body)} characters; the limit is {constraints.max_chars}."
        )
    problems.extend(_subject_violations(draft.subject, constraints))
    # An unresolved placeholder in a sent message is worse than a long one.
    leftover = _ANY_TOKEN.findall(draft.body)
    if leftover:
        problems.append(f"Unresolved placeholders left in the body: {', '.join(leftover)}")
    return problems


# Appended to the stage 1 prompt when ai.compact_research is on. Kept in code,
# not in the stored prompt, so it can be switched off without editing a prompt.
# The longest line the line-only mode accepts. The prompt asks for 45 words.
LINE_MAX_CHARS = 400

STAGE_1_STRICT_NOTE = """

EXTRA KINDS
For an item that is only one of these, use its kind instead of event, tech_sells or other:
  funding         a round, valuation or investor news
  award           a prize, ranking or "best places to work"
  earnings        revenue, profit or results announcements
  partnership     a generic business partnership or alliance, no technology named
  customer_stack  a customer's, client's or portfolio company's technology or
                  products, not the prospect's own
  certification   a course, badge or credential the prospect holds
They stay in the list as facts, but they do not count toward has_signal: set
has_signal true only if an item of another kind relates to what we sell or is
something the prospect said themselves about their work."""


def clean_issue(text: str) -> str:
    """contact_issue as written by the model, minus its way of saying "none":
    a literal "" or "none" is not a reason to hold a row."""
    text = text.strip().strip("\"'`").strip()
    return "" if text.lower() in ("", "none", "n/a", "null", "no issue") else text


def strict_signal(has_signal: bool, facts: list[Fact]) -> tuple[bool, str]:
    """has_signal once the weak kinds are discounted. Those facts stay in the
    dossier; they just cannot be the only reason to spend a stage 4 call. A row
    with no facts at all is left as the model judged it."""
    if has_signal and facts and all(f.kind in WEAK_KINDS for f in facts):
        kinds = ", ".join(sorted({f.kind for f in facts}))
        return False, f"Only {kinds} items, which do not count as a personalization signal."
    return has_signal, ""


def validate_facts(
    facts: list[Fact], texts: dict[str, str]
) -> tuple[list[Fact], list[str]]:
    """Keep the dossier items their source supports. Returns what is kept and a
    note for each item dropped."""
    kept: list[Fact] = []
    dropped: list[str] = []
    for fact in facts:
        problem = grounding.fact_problem(fact, texts.get(fact.source_key))
        if problem:
            dropped.append(f"{fact.text[:70]}: {problem}")
        else:
            kept.append(fact)
    return kept, dropped


def validate_angles(angles: list[Angle], facts: list[Fact]) -> list[Angle]:
    """Keep the angles whose evidence is one of the dossier items, and name the
    source that item came from rather than the one the model said."""
    kept: list[Angle] = []
    for angle in angles:
        if not angle.angle.strip():
            continue
        fact = grounding.match_fact(angle.evidence, facts)
        if fact:
            kept.append(Angle(angle=angle.angle, evidence=angle.evidence, source_key=fact.source_key))
    return kept


def validate_fit(claimed: bool, evidence: str, facts: list[Fact]) -> tuple[bool, str]:
    """A claim of fit stands only if its evidence is a dossier item showing the
    company uses the platform. Items marked as selling around it or writing
    about it cannot establish fit, whatever the model concluded."""
    evidence = evidence.strip()
    if not (claimed and evidence):
        return False, ""
    fact = grounding.match_fact(evidence, facts)
    if not fact or fact.kind not in ("tech_uses", ""):
        return False, ""
    return True, evidence


def slot_window(template_body: str) -> str:
    """The lines around the slot, which is all the writer needs to make its line
    join up: the one before, the slot's own line, and the next two."""
    _, body = split_subject(template_body)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if _SLOT.search(line):
            return "\n".join(lines[max(i - 1, 0) : i + 3])
    return ""


def can_combine(template: Template) -> bool:
    """The merged call writes only the slot and the code picks the copy after,
    so every copy a row can get must have a slot."""
    if not _SLOT.search(template.body):
        return False
    return not template.fallback_body.strip() or bool(_SLOT.search(template.fallback_body))


def final_slot_rules(template: Template, channel: Channel) -> tuple[str, int | None]:
    """The slot's limits for the merged call, and the length budget it uses.

    The copy is chosen after the model has written, so the budget is the
    tighter of the two copies' and the subject is requested unless both fix it.
    """
    copies = [template.body] + ([template.fallback_body] if template.fallback_body.strip() else [])
    budgets = []
    for copy in copies:
        _, body = split_subject(copy)
        fixed = len(_SLOT.sub("", body))
        if template.constraints.max_chars:
            budgets.append(template.constraints.max_chars - fixed)
    budget = min(budgets) if budgets and min(budgets) > 0 else None
    all_fix_subject = all(split_subject(c)[0] for c in copies)

    lines = [f"Channel: {channel.value}", "Copy around the slot (all of it is sent as written):"]
    for label, copy in zip(("Main copy", "Ask-first copy"), copies):
        lines.append(f"{label}:\n{slot_window(copy)}")
    if budget:
        lines.append(f"The personalization must be at most {budget} characters. Hard limit.")
    if all_fix_subject or not template.constraints.has_subject:
        lines.append("subject: null.")
    else:
        lines.append(f"subject: at most {template.constraints.subject_max_chars or 78} characters.")
    return "\n".join(lines), budget


async def run_chain(
    identity: Identity,
    raw: dict[str, str],
    research: dict[str, SourceResult],
    prompts: dict[int, str],
    template: Template,
    settings: AppSettings,
    channel: Channel,
) -> ChainOutput:
    """Run the chain for one row. With ai.compact_research on, also log what the
    saving was (sizes and token counts only, never the research text)."""
    line_mode = settings.ai.personalization_output_mode is OutputMode.personalized_line
    if not settings.ai.compact_research and not line_mode:
        return await _run_chain(identity, raw, research, prompts, template, settings, channel)

    metrics: dict = {}
    output = await _run_chain(
        identity, raw, research, prompts, template, settings, channel, metrics=metrics
    )
    seen = funnel_view(research)
    p = output.personalization
    by_stage = p.usage_by_stage

    def tokens(usage) -> int:
        return usage.input_tokens + usage.output_tokens + usage.cache_read_input_tokens + (
            usage.cache_creation_input_tokens
        )

    stage4 = by_stage.get("4") or by_stage.get("2")
    # Counts and flags only: never research text, a line, a name or an email.
    # Stored on the row so a test batch can be summarised from the database
    # (scripts/summarize_test.py); retry_count is counted inside the row's own
    # chain run, so concurrent rows cannot mix their numbers up.
    row = {
        "output_mode": p.output_mode,
        "compact_research": settings.ai.compact_research,
        "stage1_tokens": tokens(by_stage["1"]) if "1" in by_stage else 0,
        "stage4_tokens": tokens(stage4) if stage4 else 0,
        "total_tokens": tokens(p.usage),
        "stage1_stopped": "1" in by_stage and stage4 is None,
        "stage4_called": stage4 is not None,
        "line_generated": bool(p.draft and (p.draft.personal_line or "").strip()),
        "hold": output.hold,
        "contact_issue": bool(p.dossier and p.dossier.contact_issue),
        "retry_count": metrics.get("retry_count", 0),
        "grounding_failure": metrics.get("grounding_failure", False),
        "grounding_retry": metrics.get("grounding_retry", False),
        "sufficient": metrics.get("sufficient"),
        "fit_established": p.fit_established,
    }
    p.metrics = row
    if line_mode:
        logger.info("personalization_output %s", json.dumps(row))
    if not settings.ai.compact_research:
        return output

    logger.info(
        "compact_research %s",
        json.dumps(
            {
                "sources": sum(1 for r in seen.values() if r.ok and (r.content or "").strip()),
                "original_chars": sum(len(r.content or "") for r in seen.values() if r.ok),
                "baseline_chars": metrics.get("baseline_chars", 0),
                "selected_chars": metrics.get("selected_chars", 0),
                "stage1_tokens": tokens(by_stage["1"]) if "1" in by_stage else 0,
                "stage1_stopped": ("1" in by_stage and not ({"2", "4"} & set(by_stage))),
                "stage4_called": bool({"2", "4"} & set(by_stage)),
                "total_tokens": tokens(p.usage),
                "has_signal": p.dossier.has_signal if p.dossier else None,
                "thin_context": output.thin_context,
                "hold": output.hold,
            }
        ),
    )
    return output


async def _run_chain(
    identity: Identity,
    raw: dict[str, str],
    research: dict[str, SourceResult],
    prompts: dict[int, str],
    template: Template,
    settings: AppSettings,
    channel: Channel,
    metrics: dict | None = None,
) -> ChainOutput:
    if metrics is None:
        metrics = {}
    model = settings.ai.model
    research = funnel_view(research)
    line_mode = settings.ai.personalization_output_mode is OutputMode.personalized_line

    if not has_usable_research(research):
        # Every source came back empty or failed. Asking Claude would spend two
        # calls to conclude there is nothing to say, so the row goes straight to
        # the copy that claims nothing about the prospect.
        if line_mode:
            # No message is written in this mode, so there is no copy to fall back to.
            return ChainOutput(
                personalization=Personalization(
                    channel=channel,
                    draft=Draft(body=""),
                    model=model,
                    fit_established=False,
                    output_mode=OutputMode.personalized_line.value,
                ),
                thin_context=True,
                reason="None of the research sources returned anything for this row, so there "
                "was nothing to personalize from.",
            )
        template_text, ask_first = copy_for(template, False)
        context = build_context(identity, raw, settings)
        return ChainOutput(
            personalization=Personalization(
                channel=channel,
                draft=(
                    fixed_draft(template_text, context)
                    if ask_first
                    else generic_draft(template_text, context)
                ),
                model=model,
                template_version=template.version,
                fit_established=False,
                ask_first=ask_first,
            ),
            thin_context=True,
            reason="None of the research sources returned anything for this row, so there "
            "was nothing to personalize from.",
        )

    max_tokens = settings.ai.max_tokens
    enabled = set(settings.ai.enabled_stages)

    def model_for(stage: Stage) -> str:
        return stage_model(settings, stage)

    models_used = list(dict.fromkeys(model_for(s) for s in Stage if int(s) in enabled))
    model = " + ".join(models_used) or model

    # None selects the claude_code path in call_stage. A stage on an OpenAI
    # model never touches the Claude credential, so only ask for it if needed.
    subscription = settings.ai.mode is CredentialMode.claude_code
    needs_claude = any(not openai_stage.is_openai_model(m) for m in models_used)
    client = None if subscription or not needs_claude else await get_client()

    usage_total = Usage()
    usage_by_stage: dict[str, Usage] = {}
    cost_total = 0.0
    warnings: list[str] = []

    def cost_of(_: Usage) -> float:
        return round(cost_total, 6)

    def effort_for(stage: Stage) -> str:
        return settings.ai.effort.get(str(int(stage)), "high")

    def accumulate(result: StageResult, stage: Stage) -> None:
        nonlocal usage_total, cost_total
        usage_total = usage_total.add(result.usage)
        key = str(int(stage))
        usage_by_stage[key] = usage_by_stage.get(key, Usage()).add(result.usage)
        stage_model_id = model_for(stage)
        # Claude on the subscription is covered by the plan; an OpenAI stage is
        # always billed per token.
        if openai_stage.is_openai_model(stage_model_id) or not subscription:
            cost_total += pricing.cost_usd(stage_model_id, result.usage)
        if result.cacheable and not result.cache_hit:
            logger.debug("Stage %s prefix was cacheable but missed", int(stage))
        if not result.cacheable:
            warnings.append(
                f"Stage {int(stage)} prompt contains a per-prospect placeholder, so its prefix "
                "cannot be cached. Move per-prospect references out of the prompt body to cut cost."
            )

    base_context = build_context(identity, raw, settings)
    compact = settings.ai.compact_research
    selector = None
    if compact:
        anchors = [identity.last_name, identity.company, identity.first_name]
        budget = settings.ai.compact_chars_per_source
        terms = settings.ai.relevance_terms
        selector = lambda text: select_paragraphs(text, budget, anchors, terms)  # noqa: E731
    research_text = format_research(research, settings.ai.research_chars_per_source, select=selector)
    texts = research_texts(research, settings.ai.research_chars_per_source, select=selector)
    if metrics is not None:
        # What the same row would have sent with the switch off, to compare against.
        metrics["baseline_chars"] = sum(
            len(t) for t in research_texts(research, settings.ai.research_chars_per_source).values()
        )
        metrics["selected_chars"] = sum(len(t) for t in texts.values())
    # Stages 2 and 3 as one call needs stage 1's items to check its quotes against.
    combined = (
        settings.ai.combined_final
        and {int(Stage.dossier), int(Stage.angle), int(Stage.draft)} <= enabled
        and int(Stage.final) in prompts
        and can_combine(template)
    )

    # --- Stage 1: dossier -------------------------------------------------
    dossier = Dossier()
    if int(Stage.dossier) in enabled:
        system_text, cacheable = _split_stable(prompts[int(Stage.dossier)], base_context)
        if compact:
            system_text += STAGE_1_STRICT_NOTE  # after rendering, so it stays cacheable
        dossier_schema = DossierStrictOut if compact else DossierOut
        user_text = prospect_block(identity, research=research_text)
        result = await call_stage(
            client,
            system_text=system_text,
            user_text=user_text,
            schema_model=dossier_schema,
            model=model_for(Stage.dossier),
            effort=effort_for(Stage.dossier),
            max_tokens=max_tokens,
            cacheable=cacheable,
        )
        accumulate(result, Stage.dossier)
        parsed = dossier_schema.model_validate(result.parsed)
        extracted = [Fact(text=f.text, source_key=f.source_key, kind=f.kind) for f in parsed.facts]
        # Code, not the model, decides whether each item is in the source it names.
        facts, dropped = validate_facts(extracted, texts)
        if dropped:
            warnings.append(
                f"Dropped {len(dropped)} dossier item(s) their source does not support: "
                + "; ".join(dropped[:3])
            )
        has_signal, signal_note = parsed.has_signal, parsed.signal_note.strip()
        if extracted and not facts:
            has_signal, signal_note = False, "Every item extracted failed the check against its source."
        if compact:
            discounted, why = strict_signal(has_signal, facts)
            if not discounted and has_signal:
                has_signal, signal_note = False, why
        dossier = Dossier(
            summary=parsed.summary,
            facts=facts,
            has_signal=has_signal,
            signal_note=signal_note,
            contact_issue=clean_issue(parsed.contact_issue),
        )
    else:
        # Stage 1 off: hand the raw research straight to stage 2.
        dossier = Dossier(summary=research_text)

    if dossier.contact_issue:
        # The research says this is the wrong person to write to. No copy at
        # all, not even the generic one: a message to someone who has died or
        # left is worse than no message. A person decides what happens next.
        return ChainOutput(
            personalization=Personalization(
                channel=channel,
                dossier=dossier,
                model=model,
                usage=usage_total,
                usage_by_stage=usage_by_stage,
                cost_usd=cost_of(usage_total),
                template_version=template.version,
                fit_established=False,
            ),
            thin_context=True,
            hold=True,
            reason=f"Check before sending: {dossier.contact_issue}",
            warnings=warnings,
        )

    dossier_text = format_dossier(dossier)

    if line_mode:
        mode = OutputMode.personalized_line.value

        def line_output(line: str, reason: str = "", fit: bool = False, fit_ev: str = "",
                        angles_: list[Angle] | None = None, warning: str | None = None) -> ChainOutput:
            return ChainOutput(
                personalization=Personalization(
                    channel=channel,
                    dossier=dossier,
                    angles=angles_ or [],
                    # The line alone, in its own field. There is no message, so the
                    # body stays empty; an empty draft means "processed, nothing to say".
                    draft=Draft(body="", personal_line=line or None),
                    model=model,
                    usage=usage_total,
                    usage_by_stage=usage_by_stage,
                    cost_usd=cost_of(usage_total),
                    constraint_warning=warning,
                    fit_established=fit,
                    fit_evidence=fit_ev or None,
                    output_mode=mode,
                ),
                thin_context=not line,
                reason=reason,
                warnings=warnings,
            )

        if not dossier.has_signal:
            return line_output(
                "", dossier.signal_note or "The research held nothing related to what we sell."
            )

        line_rules = LINE_PROMPT
        if not _OFFER_TOKEN.search(line_rules):
            line_rules += "\nWHAT WE SELL\n{{offer_context}}"
        system_text, cacheable = _split_stable(line_rules, base_context)
        user_text = prospect_block(identity, dossier=dossier_text)
        prospect_details = " ".join([identity.display_name, identity.title or "", identity.company or ""])
        dossier_pool = " ".join([dossier.summary, *(f.text for f in dossier.facts)])
        # The full text of what the model could see, not the compact selection.
        originals = {k: r.content for k, r in research.items() if r.ok and r.content}

        def evaluate_line(parsed_dict: dict):
            out = LineOut.model_validate(parsed_dict)
            valid_angles = validate_angles(
                [Angle(angle=a.angle, evidence=a.evidence, source_key=a.source_key) for a in out.angles],
                dossier.facts,
            )
            fit_ok, fit_ev = validate_fit(out.fit_established, out.fit_evidence, dossier.facts)
            line = out.personalized_line.strip()
            style: list[str] = []
            grounded: list[str] = []
            if out.sufficient and valid_angles:
                style = _slot_violations(line, LINE_MAX_CHARS) + grounding.copy_problems(
                    line,
                    [valid_angles[0].evidence, fit_ev],
                    own_post=valid_angles[0].source_key == "linkedin_posts",
                )
                grounded = grounding.unsupported_in_line(
                    line, prospect=prospect_details, dossier=dossier_pool, research=originals
                )
            return out, valid_angles, fit_ok, fit_ev, line, style, grounded

        async def ask_line(text: str) -> StageResult:
            result = await call_stage(
                client,
                system_text=system_text,
                user_text=text,
                schema_model=LineOut,
                model=model_for(Stage.angle),
                effort=effort_for(Stage.angle),
                max_tokens=max_tokens,
                cacheable=cacheable,
            )
            accumulate(result, Stage.final)
            return result

        current = evaluate_line((await ask_line(user_text)).parsed)
        problems = current[5] + current[6]
        metrics["grounding_retry"] = bool(current[6])
        if problems:
            metrics["retry_count"] = 1
            # One bounded re-ask, as in full-message mode.
            retried = evaluate_line(
                (
                    await ask_line(
                        user_text
                        + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED\n"
                        + "\n".join(f"- {p}" for p in problems)
                        + "\n\nAnswer again. Keep the same angle; fix these problems exactly."
                    )
                ).parsed
            )
            usable = retried[0].sufficient and bool(retried[1])
            if usable and len(retried[5]) + len(retried[6]) < len(problems):
                current = retried

        out, angles, fit, fit_evidence, line, style, grounded = current
        metrics["sufficient"] = out.sufficient
        metrics["grounding_failure"] = bool(grounded)
        if not out.sufficient or not angles or not line:
            return line_output(
                "", out.reason or "The research did not support a specific angle.", fit, fit_evidence, angles
            )
        if grounded:
            # A claim the research does not support is dropped, not sent.
            reason = "The line said things the research does not support: " + " ".join(grounded)
            warnings.append(reason)
            return line_output("", reason, fit, fit_evidence, angles)
        return line_output(
            line, "", fit, fit_evidence, angles, "; ".join(style) if style else None
        )

    # --- Stage 2: angle ---------------------------------------------------
    angles: list[Angle] = []
    thin_context = False
    reason = ""
    constraint_warning: str | None = None
    # Whether the research showed this prospect has the problem we solve. Being
    # in the sheet is not evidence of that, so it is decided from the dossier.
    fit: bool | None = None
    fit_evidence = ""

    if int(Stage.angle) in enabled and not dossier.has_signal:
        # Stage 1 found nothing related to what we sell and nothing the prospect
        # said themselves. Most rows that end without an angle end here, so the
        # second call is not spent confirming it.
        thin_context = True
        fit = False
        reason = dossier.signal_note or "The research held nothing related to what we sell."
    elif combined:
        slot_rules, budget = final_slot_rules(template, channel)
        prompt_body = prompts[int(Stage.final)]
        if not _OFFER_TOKEN.search(prompt_body):
            # Relevance cannot be judged against an offer the model never saw.
            prompt_body += "\n\nWHAT WE SELL\n{{offer_context}}"
        system_text, cacheable = _split_stable(prompt_body, base_context)
        # After rendering: the template lines keep their {{tokens}} as written,
        # so the prefix stays the same for every row.
        system_text += "\n\nSLOT\n" + slot_rules
        user_text = prospect_block(identity, dossier=dossier_text)

        def evaluate(parsed_dict: dict):
            out = FinalOut.model_validate(parsed_dict)
            valid_angles = validate_angles(
                [Angle(angle=a.angle, evidence=a.evidence, source_key=a.source_key) for a in out.angles],
                dossier.facts,
            )
            fit_ok, fit_ev = validate_fit(out.fit_established, out.fit_evidence, dossier.facts)
            problems: list[str] = []
            if out.sufficient and valid_angles:
                copy_text, _ = copy_for(template, fit_ok)
                fixed, _ = split_subject(copy_text)
                subject = render_copy(fixed, base_context) if fixed else out.subject
                problems = (
                    _slot_violations(out.personalization, budget)
                    + grounding.copy_problems(
                        out.personalization,
                        [valid_angles[0].evidence, fit_ev],
                        own_post=valid_angles[0].source_key == "linkedin_posts",
                    )
                    + _subject_violations(subject, template.constraints)
                )
            return out, valid_angles, fit_ok, fit_ev, problems

        result = await call_stage(
            client,
            system_text=system_text,
            user_text=user_text,
            schema_model=FinalOut,
            model=model_for(Stage.angle),
            effort=effort_for(Stage.angle),
            max_tokens=max_tokens,
            cacheable=cacheable,
        )
        accumulate(result, Stage.final)
        final, angles, fit, fit_evidence, violations = evaluate(result.parsed)
        metrics["sufficient"] = final.sufficient

        # One bounded re-ask on a rule the code found broken, then accept and flag.
        if violations:
            metrics["retry_count"] = 1
            retry = await call_stage(
                client,
                system_text=system_text,
                user_text=user_text
                + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED\n"
                + "\n".join(f"- {problem}" for problem in violations)
                + "\n\nAnswer again. Keep the same angle; fix these problems exactly.",
                schema_model=FinalOut,
                model=model_for(Stage.angle),
                effort=effort_for(Stage.angle),
                max_tokens=max_tokens,
                cacheable=cacheable,
            )
            accumulate(retry, Stage.final)
            second = evaluate(retry.parsed)
            usable = second[0].sufficient and bool(second[1])
            if usable and (not second[4] or len(second[4]) < len(violations)):
                final, angles, fit, fit_evidence, violations = second
            if violations:
                constraint_warning = "; ".join(violations)
                logger.warning("Rules still broken after re-ask: %s", constraint_warning)

        if not final.sufficient or not angles:
            thin_context = True
            reason = final.reason or "The research did not support a specific angle."
        elif final.fit_established and not fit:
            # The line was written assuming fit that the dossier does not show.
            # Do not send it; the copy that claims nothing goes out instead.
            thin_context = True
            reason = "The model claimed fit its evidence did not support, so its line was discarded."
            warnings.append(reason)
        else:
            template_text, ask_first = copy_for(template, fit)
            fixed_subject, slot_body = split_subject(template_text)
            line = final.personalization.strip()
            draft = Draft(
                subject=render_copy(fixed_subject, base_context) if fixed_subject else final.subject,
                body=fill_slot(slot_body, base_context, line),
                personal_line=line or None,
            )
            return ChainOutput(
                personalization=Personalization(
                    channel=channel,
                    dossier=dossier,
                    angles=angles,
                    draft=draft,
                    model=model,
                    usage=usage_total,
                    usage_by_stage=usage_by_stage,
                    cost_usd=cost_of(usage_total),
                    template_version=template.version,
                    constraint_warning=constraint_warning,
                    fit_established=fit,
                    fit_evidence=fit_evidence or None,
                    ask_first=ask_first,
                ),
                warnings=warnings,
            )

    elif int(Stage.angle) in enabled:
        context = {**base_context, "dossier": dossier_text}
        prompt_body = prompts[int(Stage.angle)]
        if not _OFFER_TOKEN.search(prompt_body):
            # Relevance cannot be judged against an offer the model never saw.
            # The same for every row, so this stays cacheable.
            prompt_body += "\n\nWHAT WE SELL\n{{offer_context}}"
        system_text, cacheable = _split_stable(prompt_body, context)
        user_text = prospect_block(identity, dossier=dossier_text)
        result = await call_stage(
            client,
            system_text=system_text,
            user_text=user_text,
            schema_model=AnglesOut,
            model=model_for(Stage.angle),
            effort=effort_for(Stage.angle),
            max_tokens=max_tokens,
            cacheable=cacheable,
        )
        accumulate(result, Stage.angle)
        parsed = AnglesOut.model_validate(result.parsed)

        metrics["sufficient"] = parsed.sufficient
        # Drop angles whose evidence is not one of the dossier items.
        angles = validate_angles(
            [Angle(angle=a.angle, evidence=a.evidence, source_key=a.source_key) for a in parsed.angles],
            dossier.facts,
        )

        if not parsed.sufficient or not angles:
            thin_context = True
            reason = parsed.reason or "The research did not support a specific angle."

        # Same rule as the angles: a claim of fit with no dossier item behind it
        # does not count.
        fit, fit_evidence = validate_fit(
            parsed.fit_established, parsed.fit_evidence, dossier.facts
        )

    template_text, ask_first = copy_for(template, fit)

    if thin_context:
        # Stop before stage 3. Generating anyway is exactly the failure mode the
        # citation guard exists to prevent. The row still yields approved copy
        # with no personal line: the ask-first copy when the template has one,
        # otherwise a slot template's main copy. Neither claims anything about
        # the prospect.
        return ChainOutput(
            personalization=Personalization(
                channel=channel,
                dossier=dossier,
                angles=angles,
                draft=(
                    fixed_draft(template_text, base_context)
                    if ask_first
                    else generic_draft(template_text, base_context)
                ),
                model=model,
                usage=usage_total,
                usage_by_stage=usage_by_stage,
                cost_usd=cost_of(usage_total),
                template_version=template.version,
                fit_established=fit,
                fit_evidence=fit_evidence or None,
                ask_first=ask_first,
            ),
            thin_context=True,
            reason=reason,
            warnings=warnings,
        )

    # --- Stage 3: draft ---------------------------------------------------
    angles_text = format_angles(angles)
    # Deliberately NOT rendered: the template keeps its {{identity.first_name}}
    # placeholders so the stage-3 prefix stays identical across every row (and
    # therefore cacheable). The model fills them from the PROSPECT block in the
    # user turn, and `_constraint_violations` catches any it leaves behind.
    # `template_text` is the main copy or the ask-first copy (see `copy_for`);
    # either one is the same for every row that gets it.

    # Slot mode: the model writes only {{personalization}} and the code places it,
    # so the approved copy cannot drift and a reply can never be just the opener.
    slot_mode = bool(_SLOT.search(template_text))
    fixed_subject, slot_body = split_subject(template_text) if slot_mode else (None, "")
    budget: int | None = None
    if slot_mode:
        if template.constraints.max_chars:
            fixed_length = len(fill_slot(slot_body, base_context, ""))
            budget = template.constraints.max_chars - fixed_length
            if budget <= 0:
                warnings.append(
                    f"The template alone is {fixed_length} characters, over its "
                    f"{template.constraints.max_chars}-character limit. Raise the limit."
                )
                budget = None
        constraints_text = format_slot_constraints(
            template.constraints, channel, budget, fixed_subject
        )
    else:
        constraints_text = format_constraints(template.constraints, channel)

    context = {
        **base_context,
        "dossier": dossier_text,
        "angles": angles_text,
        "template": template_text,
        "constraints": constraints_text,
    }
    prompt_body = prompts[int(Stage.draft)]
    if not _TEMPLATE_TOKEN.search(prompt_body):
        # A prompt that never places the template would leave the model writing
        # blind. Both blocks are identical for every row, so this stays cacheable.
        prompt_body += "\n\nTEMPLATE\n{{template}}\n\nHARD CONSTRAINTS\n{{constraints}}"
    system_text, cacheable = _split_stable(prompt_body, context)
    sections = {"angle": angles_text, "dossier": dossier_text}
    if fit is not None:
        # In the user turn, not the prompt: it differs per row.
        sections["evidence_of_fit"] = format_fit(fit, fit_evidence)
    user_text = prospect_block(identity, **sections)
    schema_model = SlotOut if slot_mode else DraftOut

    def assemble(parsed: dict) -> tuple[Draft, list[str]]:
        if slot_mode:
            out = SlotOut.model_validate(parsed)
            subject = render_copy(fixed_subject, base_context) if fixed_subject else out.subject
            built = Draft(
                subject=subject,
                body=fill_slot(slot_body, base_context, out.personalization),
                personal_line=out.personalization.strip() or None,
            )
            return built, _slot_violations(out.personalization, budget) + _subject_violations(
                subject, template.constraints
            )
        out = DraftOut.model_validate(parsed)
        built = Draft(subject=out.subject, body=out.body)
        return built, _constraint_violations(built, template.constraints)

    result = await call_stage(
        client,
        system_text=system_text,
        user_text=user_text,
        schema_model=schema_model,
        model=model_for(Stage.draft),
        effort=effort_for(Stage.draft),
        max_tokens=max_tokens,
        cacheable=cacheable,
    )
    accumulate(result, Stage.draft)
    draft, violations = assemble(result.parsed)

    # One bounded re-ask on a constraint violation, then accept and flag.
    if violations:
        metrics["retry_count"] = 1
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
            schema_model=schema_model,
            model=model_for(Stage.draft),
            effort=effort_for(Stage.draft),
            max_tokens=max_tokens,
            cacheable=cacheable,
        )
        accumulate(retry, Stage.draft)
        retried_draft, remaining = assemble(retry.parsed)

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
            usage_by_stage=usage_by_stage,
            cost_usd=cost_of(usage_total),
            template_version=template.version,
            constraint_warning=constraint_warning,
            fit_established=fit,
            fit_evidence=fit_evidence or None,
            ask_first=ask_first,
        ),
        warnings=warnings,
    )
