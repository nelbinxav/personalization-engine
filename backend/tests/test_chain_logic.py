"""Chain logic that does not need the network: rendering, cacheability,
constraint checking and schema shaping.
"""
from app.ai.chain import (
    _constraint_violations,
    _slot_violations,
    _split_stable,
    fill_slot,
    generic_draft,
    render,
    split_subject,
)
from app.ai.schemas import AnglesOut, DossierOut, DraftOut, strict_schema
from app.models.prospect import Draft
from app.models.template import Constraints


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
