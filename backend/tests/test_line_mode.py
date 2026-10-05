"""ai.personalization_output_mode = "personalized_line": one line, no message."""
import asyncio
import csv
import io
import json
import logging

import pytest

from app.ai import chain, grounding
from app.ai.chain import run_chain
from app.ai.schemas import DossierOut, FinalOut, LineOut
from app.export.csv_writer import columns_for, row_for
from app.models.common import Channel, Identity, RowStatus
from app.models.prospect import Fact, Prospect, SourceResult, Usage
from app.models.settings import AppSettings, CredentialMode, OutputMode
from app.models.template import Template

TEMPLATE_TEXT = "Our founder hosts a masterclass on Thursday 15 October."
TEMPLATE = Template(
    channel=Channel.email,
    name="t",
    body=f"Subject: the Ferrari problem\n\nHi {{{{identity.first_name}}}},\n\n{{{{personalization}}}}\n\n{TEMPLATE_TEXT}\n\nBest",
    fallback_body="Subject: q\n\n{{personalization}}\n\nDo you run Databricks?",
)
USES = "Acme runs its data platform on Databricks"
BLOG = "Acme hired 40 engineers in 2026"
RESEARCH = {"website": SourceResult(key="website", ok=True, content=f"{USES}. {BLOG}. Jane Doe leads data.")}
LINE = "Running the platform on Databricks usually means compute you do not control."
GOOD = {
    "angles": [{"angle": "uses it", "evidence": USES, "source_key": "website"}],
    "sufficient": True, "reason": "", "fit_established": True, "fit_evidence": USES,
    "personalized_line": LINE,
}


def dossier(issue="", signal=True, kinds=(("tech_uses", USES),)):
    return {
        "summary": "A data company.", "contact_issue": issue, "has_signal": signal, "signal_note": "",
        "facts": [{"text": t, "source_key": "website", "kind": k} for k, t in kinds],
    }


def run(monkeypatch, finals, *, d=None, mode=OutputMode.personalized_line, compact=False, research=None):
    calls: list[tuple[str, str, str]] = []
    queue = list(finals) if isinstance(finals, list) else [finals]

    async def fake(client, *, system_text, user_text, schema_model, **kwargs):
        calls.append((schema_model.__name__, system_text, user_text))
        if issubclass(schema_model, DossierOut):
            parsed = d or dossier()
        else:
            parsed = queue.pop(0) if len(queue) > 1 else queue[0]
        return chain.StageResult(parsed=parsed, usage=Usage(output_tokens=5), cacheable=True, cache_hit=False)

    monkeypatch.setattr(chain, "call_stage", fake)
    settings = AppSettings(offer_context="We cut Databricks bills.")
    settings.ai.mode = CredentialMode.claude_code
    settings.ai.personalization_output_mode = mode
    settings.ai.compact_research = compact
    out = asyncio.run(
        run_chain(
            identity=Identity(first_name="Jane", last_name="Doe", company="Acme"),
            raw={}, research=research or RESEARCH,
            prompts={1: "extract", 2: "angle", 3: "write", 4: "final"},
            template=TEMPLATE, settings=settings, channel=Channel.email,
        )
    )
    return out, calls


def prospect_of(out, status=RowStatus.done):
    p = out.personalization
    return Prospect(upload_id="u", row_index=0, raw={"email": "j@acme.com", "first_name": "Jane"},
                    identity=Identity(first_name="Jane"), personalization=p, personalize_status=status)


def status_of(out):
    if out.hold or (out.thin_context and out.personalization.draft is None):
        return RowStatus.needs_review
    return RowStatus.thin_context if out.thin_context else RowStatus.done


# 1 ---------------------------------------------------------------------------


def test_only_the_line_is_written_and_no_template_copy_exists(monkeypatch):
    out, calls = run(monkeypatch, GOOD)
    assert [c[0] for c in calls] == ["DossierOut", "LineOut"]
    p = out.personalization
    assert p.output_mode == "personalized_line"
    assert p.draft.personal_line == LINE and p.draft.body == LINE and p.draft.subject is None
    assert p.fit_established is True and p.angles[0].source_key == "website"
    # Nothing about the template, subject, greeting or ask-first copy reaches the model or the row.
    for _, system, user in calls[1:]:
        assert "masterclass" not in system + user and "Ferrari" not in system + user
        assert "{{personalization}}" not in system
    assert "We cut Databricks bills." in calls[1][1]
    assert TEMPLATE_TEXT not in p.draft.body and not p.ask_first


# 2 ---------------------------------------------------------------------------


def test_the_default_is_still_the_full_message(monkeypatch):
    assert AppSettings().ai.personalization_output_mode is OutputMode.full_message
    final = {
        "angles": [{"angle": "a", "evidence": USES, "source_key": "website"}], "sufficient": True,
        "reason": "", "fit_established": True, "fit_evidence": USES, "personalization": LINE, "subject": None,
    }
    out, calls = run(monkeypatch, final, mode=OutputMode.full_message)
    assert [c[0] for c in calls] == ["DossierOut", "FinalOut"]
    body = out.personalization.draft.body
    assert TEMPLATE_TEXT in body and LINE in body and out.personalization.output_mode == "full_message"
    assert out.personalization.draft.subject == "the Ferrari problem"


# 3 + 10 ----------------------------------------------------------------------


def test_the_line_goes_to_its_own_csv_column_and_the_template_is_not_exported(monkeypatch):
    out, _ = run(monkeypatch, {**GOOD, "personalized_line": 'Moved to Databricks, and the "platform" is growing.'})
    prospect = prospect_of(out)
    headers = ["email", "first_name"]
    columns = columns_for("personalized", headers, has_full=False, has_line=True)
    assert columns[:2] == headers and "personalized_line" in columns
    assert not {"subject", "message", "personal_line", "copy_used"} & set(columns)
    row = row_for("personalized", prospect, headers)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerow(row)
    cell = list(csv.DictReader(io.StringIO(buffer.getvalue())))[0]["personalized_line"]
    assert cell == 'Moved to Databricks, and the "platform" is growing.'  # no JSON, no markdown
    assert TEMPLATE_TEXT not in buffer.getvalue() and "Ferrari" not in buffer.getvalue()
    assert row["outreach"] == "personalised"


def test_full_message_export_is_unchanged():
    assert "message" in columns_for("personalized", ["a"]) and "personalized_line" not in columns_for("personalized", ["a"])
    assert columns_for("personalized", ["a"]) == ["a"] + __import__("app.export.csv_writer", fromlist=["x"]).PERSONALIZATION_COLUMNS


# 4 ---------------------------------------------------------------------------


def test_insufficient_evidence_gives_a_blank_line_not_filler(monkeypatch):
    final = {**GOOD, "angles": [], "sufficient": False, "reason": "Only generic news.", "fit_established": False,
             "fit_evidence": "", "personalized_line": ""}
    out, _ = run(monkeypatch, final)
    p = out.personalization
    assert out.thin_context and out.reason == "Only generic news."
    assert p.draft.body == "" and p.draft.personal_line is None and p.fit_established is False
    row = row_for("personalized", prospect_of(out, RowStatus.thin_context), ["email"])
    assert row["personalized_line"] == "" and row["outreach"] == "generic"
    assert status_of(out) is RowStatus.thin_context


def test_a_model_that_sends_a_line_with_no_valid_angle_still_gets_a_blank(monkeypatch):
    final = {**GOOD, "angles": [{"angle": "x", "evidence": "Acme opened a Lisbon office", "source_key": "website"}]}
    out, _ = run(monkeypatch, final)
    assert out.personalization.draft.personal_line is None and out.thin_context


def test_no_signal_stops_before_stage_four_with_a_blank_line(monkeypatch):
    out, calls = run(monkeypatch, GOOD, d=dossier(signal=False))
    assert [c[0] for c in calls] == ["DossierOut"]
    assert out.personalization.draft.personal_line is None and out.thin_context


def test_no_research_at_all_calls_nothing_and_writes_no_copy(monkeypatch):
    out, calls = run(monkeypatch, GOOD, research={"website": SourceResult(key="website", ok=False, error="x")})
    assert calls == [] and out.personalization.draft.body == "" and out.thin_context


# 5 + 6 -----------------------------------------------------------------------


def test_a_line_naming_something_the_dossier_lacks_is_dropped_after_one_re_ask(monkeypatch):
    bad = {**GOOD, "personalized_line": "Running Databricks and Snowflake together usually costs compute."}
    out, calls = run(monkeypatch, [bad, bad])
    assert [c[0] for c in calls] == ["DossierOut", "LineOut", "LineOut"]
    assert out.personalization.draft.personal_line is None and out.thin_context
    assert "snowflake" in out.reason.lower() and out.warnings


def test_an_invented_number_is_corrected_on_the_re_ask(monkeypatch):
    bad = {**GOOD, "personalized_line": "Hiring 400 engineers on Databricks means more compute."}
    out, calls = run(monkeypatch, [bad, GOOD])
    assert [c[0] for c in calls][-2:] == ["LineOut", "LineOut"]
    assert out.personalization.draft.personal_line == LINE


RESEARCH_TEXT = {"website": "Acme runs on Databricks and AWS and hired 40 engineers in 2026. Jane Doe leads data."}


def check(line, dossier="Acme runs on Databricks", prospect="Jane Doe Head of Data Acme", research=None):
    return grounding.unsupported_in_line(
        line, prospect=prospect, dossier=dossier, research=RESEARCH_TEXT if research is None else research
    )


def test_a_technology_in_the_dossier_is_accepted():
    assert check("Acme runs its platform on Databricks.") == []


def test_a_technology_the_dossier_left_out_but_the_research_has_is_accepted():
    assert "aws" not in grounding.normalise("Acme runs on Databricks")
    assert check("Acme runs part of its platform on AWS.") == []


def test_a_technology_found_nowhere_is_rejected():
    problems = check("Acme runs part of its platform on Snowflake.")
    assert problems and "snowflake" in problems[0].lower()
    # Not rescued by being in some other tier's neighbour text either.
    assert check("Acme uses Kubernetes.", research={"website": "Acme uses Databricks."})


def test_the_prospects_own_details_support_their_name_and_company():
    assert check("Jane Doe at Acme leads the team.", dossier="", research={}) == []


def test_a_number_in_the_research_is_accepted_and_one_that_is_not_is_rejected():
    assert check("Acme hired 40 engineers.") == []
    problems = check("Acme hired 400 engineers.")
    assert any("400" in p for p in problems)
    # A number the dossier has but no source does is still rejected.
    assert check("Acme hired 90 engineers.", dossier="Acme hired 90 engineers")


def test_sentence_starts_and_everyday_acronyms_are_not_flagged_as_names():
    research = {"news": "Cognite will be integrated with AVEVA once approvals clear. Machine learning grows."}
    line = "Cognite will join AVEVA once approvals clear. That's a lot of platform change. ML workloads grow."
    assert check(line, dossier="Cognite AVEVA", research=research) == []
    # Platform names are claims: AWS must be found somewhere.
    assert any("aws" in p.lower() for p in check("Cognite runs on AWS.", dossier="Cognite", research=research))


def test_the_pipeline_accepts_a_line_whose_technology_only_the_research_has(monkeypatch):
    research = {"website": SourceResult(
        key="website", ok=True, content=f"{USES}. {BLOG}. Acme also runs workloads on AWS. Jane Doe leads data.")}
    line = {**GOOD, "personalized_line": "Running Databricks and AWS together usually means compute you do not control."}
    out, calls = run(monkeypatch, line, research=research)
    assert out.personalization.draft.personal_line == line["personalized_line"]
    assert [c[0] for c in calls] == ["DossierOut", "LineOut"]  # no re-ask needed


def test_style_slips_are_flagged_but_the_grounded_line_is_kept(monkeypatch):
    slip = {**GOOD, "personalized_line": "Running the platform on Databricks is impressive."}
    out, _ = run(monkeypatch, [slip, slip])
    assert out.personalization.draft.personal_line == slip["personalized_line"]
    assert "banned" in out.personalization.constraint_warning


# 7 ---------------------------------------------------------------------------


@pytest.mark.parametrize("sentinel", ['""', "none", "None", "n/a", "N/A", "  ", ""])
@pytest.mark.parametrize("mode", [OutputMode.full_message, OutputMode.personalized_line])
def test_an_empty_looking_contact_issue_never_holds_a_row(monkeypatch, sentinel, mode):
    final = GOOD if mode is OutputMode.personalized_line else {
        **GOOD, "personalization": LINE, "subject": None}
    out, _ = run(monkeypatch, final, d=dossier(issue=sentinel), mode=mode)
    assert not out.hold and out.personalization.dossier.contact_issue == ""


def test_a_real_contact_issue_still_holds_the_row_with_no_line(monkeypatch):
    out, calls = run(monkeypatch, GOOD, d=dossier(issue="She left the company in June."))
    assert out.hold and [c[0] for c in calls] == ["DossierOut"]
    assert out.personalization.draft is None and status_of(out) is RowStatus.needs_review
    assert row_for("personalized", prospect_of(out, RowStatus.needs_review), ["email"])["outreach"] == "hold"


# 8 ---------------------------------------------------------------------------


def test_it_works_with_compact_research_on_and_off(monkeypatch):
    for compact in (False, True):
        out, calls = run(monkeypatch, GOOD, compact=compact)
        assert out.personalization.draft.personal_line == LINE
        assert calls[0][0] == ("DossierStrictOut" if compact else "DossierOut")


def test_repost_use_sells_talks_distinctions_still_hold(monkeypatch):
    # An item that only talks about or sells around the platform cannot establish fit.
    talks = "Acme wrote a post about Databricks"
    research = {"website": SourceResult(key="website", ok=True, content=talks + ". Jane Doe leads data.")}
    final = {**GOOD, "angles": [{"angle": "x", "evidence": talks, "source_key": "website"}],
             "fit_evidence": talks, "personalized_line": "Acme writes about Databricks."}
    out, _ = run(monkeypatch, final, d=dossier(kinds=(("tech_talks", talks),)), research=research)
    assert out.personalization.fit_established is False


# logging ---------------------------------------------------------------------


def test_the_measurement_line_has_counts_and_no_research_text(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="app.ai.chain"):
        run(monkeypatch, GOOD)
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("personalization_output"))
    data = json.loads(line.split(" ", 1)[1])
    assert data["output_mode"] == "personalized_line" and data["line_generated"] is True
    assert data["stage4_called"] is True and data["stage1_stopped"] is False and data["hold"] is False
    assert data["total_tokens"] == data["stage1_tokens"] + data["stage4_tokens"] > 0
    assert "Databricks" not in line and "Jane" not in line


def test_full_message_mode_logs_nothing_extra(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="app.ai.chain"):
        run(monkeypatch, {**GOOD, "personalization": LINE, "subject": None}, mode=OutputMode.full_message)
    assert not [r for r in caplog.records if r.getMessage().startswith("personalization_output")]


# --- mixed batches: each row is exported by its own stored mode ------------------


def full_prospect(status=RowStatus.done):
    from app.models.prospect import Draft, Personalization

    p = Personalization(
        channel=Channel.email, draft=Draft(subject="the Ferrari problem", body=f"Hi Jane,\n\n{LINE}\n\n{TEMPLATE_TEXT}",
                                          personal_line=LINE),
        model="m", output_mode="full_message",
    )
    return Prospect(upload_id="u", row_index=1, raw={"email": "f@acme.com"}, identity=Identity(first_name="Fay"),
                    personalization=p, personalize_status=status)


def line_prospect(monkeypatch):
    out, _ = run(monkeypatch, GOOD)
    return prospect_of(out)


def test_a_mixed_batch_exports_each_row_by_its_own_mode(monkeypatch):
    from app.export.csv_writer import personalization_columns

    full, line = full_prospect(), line_prospect(monkeypatch)
    columns = personalization_columns(has_full=True, has_line=True)
    assert {"subject", "message", "personal_line", "copy_used", "personalized_line"} <= set(columns)

    f = row_for("personalized", full, ["email"])
    assert f["subject"] == "the Ferrari problem" and TEMPLATE_TEXT in f["message"]
    assert f["personal_line"] == LINE and f["copy_used"] == "main"
    assert f["outreach"] == "personalised" and "personalized_line" not in f  # nothing claimed for a full row

    l = row_for("personalized", line, ["email"])
    assert l["personalized_line"] == LINE and l["outreach"] == "personalised"
    for field in ("subject", "message", "personal_line", "copy_used"):
        assert field not in l  # a line row never carries message fields
    assert TEMPLATE_TEXT not in " ".join(l.values())


def test_the_setting_never_reinterprets_rows_already_written(monkeypatch):
    # row_for takes no setting at all: the stored mode is the only input.
    import inspect
    from app.export import csv_writer

    assert "line_mode" not in inspect.signature(csv_writer.row_for).parameters
    line = line_prospect(monkeypatch)
    assert row_for("combined", line, ["email"])["personalized_line"] == LINE
    old = full_prospect().model_copy(deep=True)
    old.personalization.output_mode = "full_message"
    assert "message" in row_for("personalized", old, ["email"])


def test_columns_follow_the_modes_present_in_the_upload():
    from app.export.csv_writer import LINE_COLUMNS, PERSONALIZATION_COLUMNS, personalization_columns

    assert personalization_columns(True, False) == PERSONALIZATION_COLUMNS
    assert personalization_columns(False, True) == LINE_COLUMNS
    mixed = personalization_columns(True, True)
    assert mixed.index("personalized_line") == mixed.index("personal_line") + 1
    assert [c for c in mixed if c != "personalized_line"] == PERSONALIZATION_COLUMNS


def test_modes_in_reads_the_stored_modes_not_the_setting(monkeypatch):
    from app.export import csv_writer

    class Fake:
        def __init__(self, docs): self.docs = docs
        async def count_documents(self, query, limit=0):
            mode = query["personalization.output_mode"]
            def ok(d):
                if not d.get("generated"): return False
                m = d.get("mode")
                return m == "personalized_line" if mode == "personalized_line" else m != "personalized_line"
            return sum(1 for d in self.docs if ok(d))

    def modes(docs):
        monkeypatch.setattr(csv_writer.mongo, "prospects", lambda: Fake(docs))
        return asyncio.run(csv_writer._modes_in("u"))

    assert modes([]) == (True, False)  # nothing personalized yet: the usual columns
    assert modes([{"generated": True, "mode": "personalized_line"}]) == (False, True)
    assert modes([{"generated": True}]) == (True, False)  # written before output_mode existed
    assert modes([{"generated": True}, {"generated": True, "mode": "personalized_line"}]) == (True, True)
    assert modes([{"generated": False}, {"generated": True, "mode": "personalized_line"}]) == (False, True)
