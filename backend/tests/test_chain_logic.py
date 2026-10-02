"""Chain logic that does not need the network: rendering, cacheability,
constraint checking and schema shaping.
"""
import asyncio

from app.ai.chain import (
    _constraint_violations,
    _slot_violations,
    _split_stable,
    compact_source_text,
    copy_for,
    fill_slot,
    fixed_draft,
    format_fit,
    format_research,
    generic_draft,
    has_usable_research,
    render,
    run_chain,
    split_subject,
    stage_model,
)
from app.ai.schemas import AnglesOut, DossierOut, DraftOut, strict_schema
from app.models.prompt import Stage
from app.models.prospect import Draft, SourceResult
from app.models.settings import AppSettings
from app.models.common import Channel, Identity
from app.models.template import Constraints, Template


def test_render_substitutes_known_tokens_and_leaves_typos_visible():
    out = render(
        "Hi {{identity.first_name}} at {{identity.company}} / {{identity.nope}}",
        {"identity.first_name": "Ada", "identity.company": "Analytical"},
    )
    assert out == "Hi Ada at Analytical / {{identity.nope}}"


def test_render_does_not_recurse_into_substituted_text():
    # The template is injected into the stage-3 prompt carrying its own
    # placeholders; a second pass would resolve them and break caching.
    out = render("{{template}}", {"template": "Hi {{identity.first_name}}"})
    assert out == "Hi {{identity.first_name}}"


def test_prompt_without_per_prospect_tokens_is_cacheable():
    body = "You are an analyst.\n\nWHAT WE SELL\n{{offer_context}}"
    text, cacheable = _split_stable(body, {"offer_context": "Databricks cost reduction"})
    assert cacheable is True
    assert "Databricks cost reduction" in text


def test_prompt_with_a_per_prospect_token_is_not_cacheable():
    for body in (
        "Research {{identity.company}}",
        "Here is the data: {{research}}",
        "Dossier: {{dossier}}",
        "Angles: {{angles}}",
        "Sector: {{raw.Industry}}",
    ):
        _, cacheable = _split_stable(body, {})
        assert cacheable is False, body


def test_linkedin_length_limit_is_enforced():
    constraints = Constraints(max_chars=300)
    violations = _constraint_violations(Draft(body="x" * 301), constraints)
    assert any("301 characters" in v for v in violations)

    assert _constraint_violations(Draft(body="x" * 300), constraints) == []


def test_email_requires_a_subject_within_its_limit():
    constraints = Constraints(max_chars=1200, has_subject=True, subject_max_chars=78)

    assert any(
        "subject" in v.lower() for v in _constraint_violations(Draft(body="hi"), constraints)
    )
    assert any(
        "78" in v
        for v in _constraint_violations(Draft(subject="s" * 79, body="hi"), constraints)
    )
    assert _constraint_violations(Draft(subject="Short one", body="hi"), constraints) == []


def test_unresolved_placeholder_is_a_violation():
    # An unfilled {{...}} reaching a real prospect is worse than a long message.
    violations = _constraint_violations(Draft(body="Hi {{identity.first_name}}"), Constraints())
    assert any("Unresolved placeholders" in v for v in violations)


def test_non_email_channel_must_not_demand_a_subject():
    assert _constraint_violations(Draft(body="hi"), Constraints(max_chars=300)) == []


SLOT_TEMPLATE = """Subject: the Ferrari-to-the-grocery-store problem

Hi {{firstName|there}},

{{personalization}}

You're running data engineering at {{companyName|your company}}.

{{sendingAccountFirstName}}
Data Engineering, BigHammer.ai
"""


def test_split_subject_peels_a_leading_subject_line():
    subject, body = split_subject(SLOT_TEMPLATE)
    assert subject == "the Ferrari-to-the-grocery-store problem"
    assert body.startswith("Hi {{firstName|there}},")

    assert split_subject("Hi there") == (None, "Hi there")


PROSPECT = {"identity.first_name": "Ada", "identity.company": "Analytical"}


def test_fill_slot_fills_merge_tags_and_leaves_the_sender_for_the_sending_tool():
    _, body = split_subject(SLOT_TEMPLATE)
    out = fill_slot(body, PROSPECT, "  The ICE Mortgage Monitor never stops.  ")
    assert out == (
        "Hi Ada,\n\n"
        "The ICE Mortgage Monitor never stops.\n\n"
        "You're running data engineering at Analytical.\n\n"
        "{{sendingAccountFirstName}}\nData Engineering, BigHammer.ai\n"
    )


def test_merge_tags_fall_back_when_the_prospect_field_is_empty():
    _, body = split_subject(SLOT_TEMPLATE)
    out = fill_slot(body, {"identity.first_name": "", "identity.company": None}, "x")
    assert out.startswith("Hi there,")
    assert "at your company." in out


def test_first_name_falls_back_to_the_full_name():
    out = fill_slot("Hi {{firstName|there}}", {"identity.full_name": "Grace Hopper"}, "")
    assert out == "Hi Grace"


def test_render_fallback_leaves_unknown_tokens_visible():
    assert render("{{nope|x}}", {}) == "{{nope|x}}"
    assert render("{{known|x}}", {"known": "  "}) == "x"


def test_fill_slot_renders_the_apps_own_tokens():
    out = fill_slot("Hi {{identity.first_name}},\n{{ personalisation }}", {"identity.first_name": "Ada"}, "x")
    assert out == "Hi Ada,\nx"


def test_generic_draft_drops_the_slot_line_and_keeps_the_rest():
    draft = generic_draft(SLOT_TEMPLATE, PROSPECT)
    assert draft.subject == "the Ferrari-to-the-grocery-store problem"
    assert draft.body == (
        "Hi Ada,\n\n"
        "You're running data engineering at Analytical.\n\n"
        "{{sendingAccountFirstName}}\nData Engineering, BigHammer.ai\n"
    )


def test_generic_draft_handles_an_inline_slot_and_a_slotless_template():
    assert generic_draft("Hi Ada - {{personalization}}", {}).body == "Hi Ada - "
    # Without a slot the whole message is model-written, so there is no safe copy.
    assert generic_draft("Hi {{identity.first_name}}", {}) is None


def test_slot_violations():
    assert _slot_violations("A specific line.", budget=100) == []
    assert any("empty" in v for v in _slot_violations("  ", budget=100))
    assert any("limit is 5" in v for v in _slot_violations("too long", budget=5))
    assert any("Placeholders" in v for v in _slot_violations("Hi {{firstName}}", budget=None))


def test_strict_schema_inlines_refs_and_closes_objects():
    schema = strict_schema(DossierOut)

    assert "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())

    # FactOut was a $ref before inlining.
    fact = schema["properties"]["facts"]["items"]
    assert fact["additionalProperties"] is False
    assert set(fact["required"]) == {"text", "source_key"}


def test_strict_schema_handles_optional_fields():
    schema = strict_schema(DraftOut)
    # Strict schemas require every property, including the nullable one.
    assert set(schema["required"]) == {"subject", "body"}


def test_angles_schema_exposes_the_sufficiency_flag():
    schema = strict_schema(AnglesOut)
    assert "sufficient" in schema["properties"]
    assert "sufficient" in schema["required"]


def test_angles_schema_requires_a_fit_decision_with_its_evidence():
    schema = strict_schema(AnglesOut)
    assert {"fit_established", "fit_evidence"} <= set(schema["required"])


ASK_FIRST = "Subject: do you run Databricks?\n\nHi {{firstName|there}},\n\n{{personalization}}\n\nDoes {{companyName|your team}} run Databricks?\n"


def _template(**overrides) -> Template:
    return Template(channel=Channel.email, name="t", body=SLOT_TEMPLATE, **overrides)


def test_main_copy_only_goes_to_rows_whose_research_showed_fit():
    template = _template(fallback_body=ASK_FIRST)
    assert copy_for(template, True) == (SLOT_TEMPLATE, False)
    # On the list but nothing shows they have the problem: ask, do not assume.
    assert copy_for(template, False) == (ASK_FIRST, True)
    # Stage 2 off: no decision was made, so nothing changes.
    assert copy_for(template, None) == (SLOT_TEMPLATE, False)


def test_a_template_without_ask_first_copy_keeps_its_main_copy():
    assert copy_for(_template(), False) == (SLOT_TEMPLATE, False)
    assert copy_for(_template(fallback_body="  \n"), False) == (SLOT_TEMPLATE, False)


def test_fixed_draft_renders_ask_first_copy_with_no_model_text():
    draft = fixed_draft(ASK_FIRST, PROSPECT)
    assert draft.subject == "do you run Databricks?"
    assert draft.body == "Hi Ada,\n\nDoes Analytical run Databricks?\n"
    # Unlike generic_draft, copy with no slot is still approved copy.
    assert fixed_draft("Does {{companyName|your team}} run Databricks?", {}).body == (
        "Does your team run Databricks?"
    )


def test_fit_note_tells_the_writer_not_to_assume():
    assert "Do not state or imply" in format_fit(False, "")
    assert format_fit(True, "runs Databricks on AWS").endswith("runs Databricks on AWS")


def test_compaction_drops_link_targets_and_images_but_keeps_the_words():
    page = (
        "![logo](https://cdn.example.com/a/very/long/logo.png)\n"
        "*   [Pricing](https://example.com/pricing?utm=nav)\n"
        "*   [](https://example.com/empty)\n\n\n\n"
        "We run our lakehouse on [Databricks](https://databricks.com) (since 2024)."
    )
    text = compact_source_text(page)
    assert "http" not in text and "logo" not in text
    assert "*   Pricing" in text
    assert "We run our lakehouse on Databricks (since 2024)." in text
    assert "\n\n\n" not in text


def test_research_is_capped_per_source_except_recent_posts():
    research = {
        "website": SourceResult(key="website", ok=True, content="w" * 9000),
        "linkedin_posts": SourceResult(key="linkedin_posts", ok=True, content="p" * 9000),
    }
    text = format_research(research, max_chars=1000)
    assert "w" * 1000 + "\n[trimmed]" in text and "w" * 1001 not in text
    assert "p" * 9000 in text
    # Posts come first whatever order they were stored in.
    assert text.index("linkedin_posts") < text.index("website")
    assert "w" * 9000 in format_research(research)


def test_a_row_with_no_usable_research_never_calls_claude():
    research = {
        "website": SourceResult(key="website", ok=False, error="HTTP 422"),
        "news": SourceResult(key="news", ok=True, content="   "),
    }
    assert not has_usable_research(research)
    # Default settings have no credential at all, so reaching Claude would raise.
    out = asyncio.run(
        run_chain(
            identity=Identity(first_name="Ada", company="Analytical"),
            raw={},
            research=research,
            prompts={},
            template=_template(fallback_body=ASK_FIRST),
            settings=AppSettings(),
            channel=Channel.email,
        )
    )
    assert out.thin_context and out.personalization.ask_first
    assert out.personalization.draft.body == "Hi Ada,\n\nDoes Analytical run Databricks?\n"
    assert out.personalization.usage.output_tokens == 0


def test_each_stage_can_run_on_its_own_model():
    settings = AppSettings()
    settings.ai.model = "claude-sonnet-5-5"
    settings.ai.stage_models = {"1": "gpt-6-luna", "3": ""}
    assert stage_model(settings, Stage.dossier) == "gpt-6-luna"
    # Not listed, or cleared: the default model.
    assert stage_model(settings, Stage.angle) == "claude-sonnet-5-5"
    assert stage_model(settings, Stage.draft) == "claude-sonnet-5-5"


def _run_with_fake_stages(monkeypatch, dossier: dict, prompts: dict | None = None):
    """Run the chain with Claude replaced by canned stage outputs, recording
    which schema (stage) was asked for and the system prompt it got."""
    from app.ai import chain
    from app.ai.schemas import AnglesOut as Angles, DossierOut as DossierSchema
    from app.models.prospect import Usage
    from app.models.settings import CredentialMode

    calls: list[tuple[str, str]] = []

    async def fake_call_stage(client, *, system_text, schema_model, **kwargs):
        calls.append((schema_model.__name__, system_text))
        if schema_model is DossierSchema:
            parsed = dossier
        elif schema_model is Angles:
            parsed = {"angles": [], "sufficient": False, "reason": "nothing", "fit_established": False, "fit_evidence": ""}
        else:
            parsed = {"personalization": "x", "subject": None}
        return chain.StageResult(parsed=parsed, usage=Usage(output_tokens=10), cacheable=True, cache_hit=False)

    monkeypatch.setattr(chain, "call_stage", fake_call_stage)
    settings = AppSettings(offer_context="We cut Databricks bills.")
    settings.ai.mode = CredentialMode.claude_code
    out = asyncio.run(
        run_chain(
            identity=Identity(first_name="Ada", company="Analytical"),
            raw={},
            research={"website": SourceResult(key="website", ok=True, content="About us.")},
            prompts=prompts or {1: "extract", 2: "pick angles", 3: "write"},
            template=_template(fallback_body=ASK_FIRST),
            settings=settings,
            channel=Channel.email,
        )
    )
    return out, calls


def test_no_signal_in_the_dossier_skips_the_angle_stage(monkeypatch):
    dossier = {"summary": "A bakery.", "facts": [], "recent_events": [], "tech_signals": [],
               "has_signal": False, "signal_note": "Only company history."}
    out, calls = _run_with_fake_stages(monkeypatch, dossier)
    assert [name for name, _ in calls] == ["DossierOut"]
    assert out.thin_context and out.reason == "Only company history."
    # No evidence of fit either, so the row gets the copy that asks.
    assert out.personalization.ask_first and out.personalization.fit_established is False


def test_a_dossier_with_signal_still_goes_to_the_angle_stage(monkeypatch):
    dossier = {"summary": "A data company.", "facts": [], "recent_events": [],
               "tech_signals": [{"text": "Runs Databricks", "source_key": "website"}],
               "has_signal": True, "signal_note": "Stack signal."}
    _, calls = _run_with_fake_stages(monkeypatch, dossier)
    assert [name for name, _ in calls] == ["DossierOut", "AnglesOut"]


def test_the_angle_stage_always_sees_the_offer(monkeypatch):
    dossier = {"summary": "s", "facts": [], "recent_events": [], "tech_signals": [], "has_signal": True, "signal_note": ""}
    # A prompt that never places the offer gets it appended...
    _, calls = _run_with_fake_stages(monkeypatch, dossier)
    assert calls[1][1].endswith("WHAT WE SELL\nWe cut Databricks bills.")
    # ...and one that places it is left alone.
    _, calls = _run_with_fake_stages(monkeypatch, dossier, {1: "x", 2: "Offer: {{offer_context}}. Pick.", 3: "w"})
    assert calls[1][1] == "Offer: We cut Databricks bills.. Pick."


def test_a_contact_issue_stops_the_row_with_no_copy_at_all(monkeypatch):
    dossier = {"summary": "s", "facts": [], "recent_events": [], "tech_signals": [], "has_signal": True,
               "signal_note": "", "contact_issue": "The sources call her the company's late founder."}
    out, calls = _run_with_fake_stages(monkeypatch, dossier)
    assert [name for name, _ in calls] == ["DossierOut"]
    assert out.hold and out.personalization.draft is None
    assert "late founder" in out.reason
