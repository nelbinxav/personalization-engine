"""ai.compact_research: paragraph selection and the stricter stage 1 signal."""
import asyncio
import json
import logging

import pytest

from app.ai import chain
from app.ai.chain import format_research, research_texts, run_chain, strict_signal
from app.ai.research_select import select_paragraphs
from app.ai.schemas import DossierOut, DossierStrictOut, FinalOut
from app.models.common import Channel, Identity
from app.models.prospect import Fact, SourceResult, Usage
from app.models.settings import AppSettings, CredentialMode
from app.models.template import Template

ANCHORS = ["Doe", "Acme"]


def para(text: str, n: int = 6) -> str:
    return " ".join([text] * n)


# --- selection ---------------------------------------------------------------


def test_a_source_shorter_than_the_cap_is_untouched():
    text = "Acme builds things.\n\nJane Doe leads data."
    assert select_paragraphs(text, 3000, ANCHORS) == text


def test_a_longer_source_is_cut_to_the_budget_in_original_order():
    paragraphs = [f"Paragraph {i} about Acme and its data platform work in 2026." for i in range(120)]
    out = select_paragraphs("\n\n".join(paragraphs), 1000, ANCHORS)
    assert len(out) <= 1000
    kept = [int(p.split()[1]) for p in out.split("\n\n")]
    assert kept == sorted(kept)


def test_a_relevant_paragraph_at_the_end_beats_filler_at_the_start():
    filler = [f"Our values guide everything we do, number {i}, for every team." for i in range(60)]
    key = "Acme migrated its warehouse to Databricks in March 2026, said Jane Doe."
    text = "\n\n".join(filler + [key])
    assert key in select_paragraphs(text, 600, ANCHORS, ["Databricks"])
    # Truncation would never have reached it.
    assert key not in text[:600]


def test_cookie_and_navigation_text_is_dropped_first():
    cookies = "\n\n".join(
        f"We use cookies. Cookie {i} lasts one year. Accept all cookies to give consent." for i in range(40)
    )
    news = "Acme launched a new analytics product in 2026 and hired Jane Doe as head of data."
    out = select_paragraphs(cookies + "\n\n" + news, 400, ANCHORS)
    assert news in out
    assert "Accept all" not in out and "cookies" not in out


def test_each_source_is_selected_on_its_own_and_keeps_its_key():
    research = {
        "website": SourceResult(key="website", ok=True, content=para("Acme sells widgets in 2026.", 200)),
        "news": SourceResult(key="news", ok=True, content=para("Acme raised money in 2026.", 200)),
        "linkedin_posts": SourceResult(key="linkedin_posts", ok=True, content=para("Jane Doe posted.", 400)),
        "rss": SourceResult(key="rss", ok=False, error="HTTP 500"),
    }
    texts = research_texts(research, 6000, select=lambda t: select_paragraphs(t, 500, ANCHORS))
    assert set(texts) == {"website", "news", "linkedin_posts"}
    assert len(texts["website"]) <= 500 and len(texts["news"]) <= 500
    # Recent posts are never trimmed, as before.
    assert len(texts["linkedin_posts"]) == len(research["linkedin_posts"].content.strip())
    rendered = format_research(research, 6000, select=lambda t: select_paragraphs(t, 500, ANCHORS))
    assert "### source: website" in rendered and "### source: news" in rendered
    assert "### source: rss\n(unavailable: HTTP 500)" in rendered


def test_configured_terms_decide_which_paragraph_survives():
    a = "The team adopted Kubernetes across all its services during the winter."
    b = "The team adopted Snowflake across all its services during the winter."
    text = "\n\n".join([para(a, 1)] * 1 + [para(b, 1)] + [para("Filler words that say very little at all.", 3)] * 30)
    assert b in select_paragraphs(text, 200, [], ["Snowflake"])
    assert a in select_paragraphs(text, 200, [], ["Kubernetes"])


def test_without_terms_generic_signals_still_pick_dated_named_paragraphs():
    dull = "Quality and trust are at the heart of what we do for our customers every day."
    news = "On 4 March 2026 Acme announced a partnership and appointed Jane Doe as chief data officer."
    text = "\n\n".join([dull] * 30 + [news])
    assert news in select_paragraphs(text, 300, ANCHORS, [])
    assert news in select_paragraphs(text, 300, ANCHORS, None)


def test_identical_input_gives_identical_output():
    text = "\n\n".join(f"Acme item {i % 7} shipped in 2026 with Jane Doe." for i in range(80))
    first = select_paragraphs(text, 700, ANCHORS, ["shipped"])
    assert all(select_paragraphs(text, 700, ANCHORS, ["shipped"]) == first for _ in range(5))


# --- stage 1 signal ----------------------------------------------------------

TEMPLATE = Template(
    channel=Channel.email,
    name="t",
    body="Subject: s\n\nHi {{identity.first_name}},\n\n{{personalization}}\n\nBest",
    fallback_body="Subject: q\n\n{{personalization}}\n\nDo you run Databricks?",
)
FACTS = {
    "funding": "Acme raised $20M in a Series B round",
    "award": "Acme won the Best Workplaces award for 2026",
    "earnings": "Acme reported second quarter revenue of $50M",
    "partnership": "Acme announced a partnership with Globex",
    "customer_stack": "Acme's client Initech runs its stack on Snowflake",
    "certification": "Jane Doe earned the AWS Solutions Architect certification",
    "own_post": "Jane Doe posted that her team migrated its pipelines to Delta Lake",
    "tech_uses": "Acme runs its data platform on Databricks",
    "event": "Acme announced a migration to a new data platform",
    "repost": "Jane Doe reposted a post by Sam about Databricks",
    "tech_sells": "Acme is a Databricks reseller",
    "tech_talks": "Acme wrote a blog post about Snowflake",
}
RESEARCH = {"website": SourceResult(key="website", ok=True, content=". ".join(FACTS.values()) + ".")}
FINAL = {
    "angles": [{"angle": "a", "evidence": FACTS["tech_uses"], "source_key": "website"}],
    "sufficient": True, "reason": "", "fit_established": True, "fit_evidence": FACTS["tech_uses"],
    "personalization": "Running the platform on Databricks usually means compute you do not control.",
    "subject": None,
}


def run(monkeypatch, kinds, *, compact=True, issue="", model_signal=True):
    calls: list[tuple[str, str]] = []

    async def fake(client, *, system_text, schema_model, **kwargs):
        calls.append((schema_model.__name__, system_text))
        if issubclass(schema_model, DossierOut):
            parsed = {
                "summary": "A company.", "contact_issue": issue, "has_signal": model_signal,
                "signal_note": "", "facts": [{"text": FACTS[k], "source_key": "website", "kind": k} for k in kinds],
            }
        else:
            parsed = FINAL
        return chain.StageResult(parsed=parsed, usage=Usage(output_tokens=5), cacheable=True, cache_hit=False)

    monkeypatch.setattr(chain, "call_stage", fake)
    settings = AppSettings(offer_context="We cut Databricks bills.")
    settings.ai.mode = CredentialMode.claude_code
    settings.ai.compact_research = compact
    out = asyncio.run(
        run_chain(
            identity=Identity(first_name="Jane", last_name="Doe", company="Acme"),
            raw={}, research=RESEARCH,
            prompts={1: "extract", 2: "angle", 3: "write", 4: "final"},
            template=TEMPLATE, settings=settings, channel=Channel.email,
        )
    )
    return out, calls


@pytest.mark.parametrize(
    "kind", ["funding", "award", "earnings", "partnership", "customer_stack", "certification"]
)
def test_a_weak_item_alone_is_no_signal_but_stays_in_the_dossier(monkeypatch, kind):
    out, calls = run(monkeypatch, [kind])
    assert [name for name, _ in calls] == ["DossierStrictOut"]  # no stage 4 call
    dossier = out.personalization.dossier
    assert dossier.has_signal is False and kind in dossier.signal_note
    assert [f.kind for f in dossier.facts] == [kind]  # kept, not deleted
    assert out.thin_context and out.personalization.ask_first


@pytest.mark.parametrize("kind", ["own_post", "tech_uses", "event"])
def test_a_strong_item_is_a_signal_and_reaches_stage_four(monkeypatch, kind):
    out, calls = run(monkeypatch, [kind])
    assert [name for name, _ in calls] == ["DossierStrictOut", "FinalOut"]
    assert out.personalization.dossier.has_signal is True


def test_weak_items_mixed_with_a_strong_one_still_signal(monkeypatch):
    out, calls = run(monkeypatch, ["funding", "award", "tech_uses"])
    assert [name for name, _ in calls] == ["DossierStrictOut", "FinalOut"]
    assert len(out.personalization.dossier.facts) == 3


def test_a_contact_issue_still_comes_first(monkeypatch):
    out, calls = run(monkeypatch, ["funding"], issue="The sources call her the late founder.")
    assert out.hold and out.personalization.draft is None and "late founder" in out.reason
    assert [name for name, _ in calls] == ["DossierStrictOut"]


@pytest.mark.parametrize("kind", ["repost", "tech_sells", "tech_talks"])
def test_the_repost_and_technology_kinds_are_unchanged(monkeypatch, kind):
    out, calls = run(monkeypatch, [kind])
    # Not weak kinds: the model's has_signal stands, as before the switch existed.
    assert out.personalization.dossier.has_signal is True
    assert [f.kind for f in out.personalization.dossier.facts] == [kind]


def test_selling_or_writing_about_a_platform_still_cannot_establish_fit(monkeypatch):
    out, _ = run(monkeypatch, ["tech_sells"])
    assert out.personalization.fit_established is False


def test_the_model_saying_no_signal_is_respected(monkeypatch):
    out, calls = run(monkeypatch, ["tech_uses"], model_signal=False)
    assert [name for name, _ in calls] == ["DossierStrictOut"] and out.thin_context


def test_strict_signal_leaves_an_empty_dossier_to_the_model():
    assert strict_signal(True, []) == (True, "")
    assert strict_signal(False, [Fact(text="x", source_key="s", kind="funding")]) == (False, "")


# --- the switch --------------------------------------------------------------


def test_it_is_off_by_default():
    assert AppSettings().ai.compact_research is False
    assert AppSettings().ai.relevance_terms == []


def test_off_means_the_old_schema_prompt_and_signal(monkeypatch):
    out, calls = run(monkeypatch, ["event"], compact=False)
    assert [name for name, _ in calls] == ["DossierOut", "FinalOut"]
    assert "EXTRA KINDS" not in calls[0][1]


def test_on_adds_the_note_after_the_prompt(monkeypatch):
    _, calls = run(monkeypatch, ["tech_uses"])
    assert calls[0][1].startswith("extract") and "EXTRA KINDS" in calls[0][1]
    assert issubclass(DossierStrictOut, DossierOut)


def test_the_measurement_line_has_sizes_and_tokens_but_no_research_text(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="app.ai.chain"):
        run(monkeypatch, ["funding"])
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("compact_research"))
    data = json.loads(line.split(" ", 1)[1])
    assert data["sources"] == 1 and data["stage1_stopped"] is True and data["stage4_called"] is False
    assert data["selected_chars"] <= data["baseline_chars"] <= data["original_chars"]
    assert data["stage1_tokens"] > 0 and data["total_tokens"] == data["stage1_tokens"]
    assert "Series B" not in line


def test_a_model_that_writes_none_as_a_contact_issue_does_not_hold_the_row(monkeypatch):
    from app.ai.chain import clean_issue

    assert clean_issue('""') == "" and clean_issue(" None ") == "" and clean_issue("n/a") == ""
    assert clean_issue("She left the company in June.") == "She left the company in June."
    out, calls = run(monkeypatch, ["tech_uses"], issue='""')
    assert not out.hold and [name for name, _ in calls] == ["DossierStrictOut", "FinalOut"]
