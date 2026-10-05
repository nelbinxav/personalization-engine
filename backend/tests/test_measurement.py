"""Per-row metrics and the batch summary used to compare configurations."""
import asyncio
import json

from app.ai import chain, measure
from app.ai.chain import run_chain
from app.ai.schemas import DossierOut
from app.models.common import Channel, Identity
from app.models.prospect import SourceResult, Usage
from app.models.settings import AppSettings, CredentialMode, OutputMode
from tests.test_line_mode import BLOG, GOOD, LINE, RESEARCH, TEMPLATE, USES, dossier


def settings(mode=OutputMode.personalized_line, compact=False):
    s = AppSettings(offer_context="We cut Databricks bills.")
    s.ai.mode = CredentialMode.claude_code
    s.ai.personalization_output_mode = mode
    s.ai.compact_research = compact
    return s


def go(first_name, finals_by_name, *, d=None, cfg=None):
    async def one():
        return await run_chain(
            identity=Identity(first_name=first_name, last_name="Doe", company="Acme"),
            raw={}, research=RESEARCH, prompts={1: "x", 2: "a", 3: "w", 4: "f"},
            template=TEMPLATE, settings=cfg or settings(), channel=Channel.email,
        )
    return one()


def install(monkeypatch, finals_by_name, d=None):
    queues = {k: list(v) for k, v in finals_by_name.items()}

    async def fake(client, *, user_text, schema_model, **kwargs):
        if issubclass(schema_model, DossierOut):
            parsed = d or dossier()
        else:
            name = next(n for n in queues if f"Name: {n} " in user_text)
            q = queues[name]
            parsed = q.pop(0) if len(q) > 1 else q[0]
            await asyncio.sleep(0)  # let the other row interleave
        return chain.StageResult(parsed=parsed, usage=Usage(output_tokens=7), cacheable=True, cache_hit=False)

    monkeypatch.setattr(chain, "call_stage", fake)


BAD_NUMBER = {**GOOD, "personalized_line": "Hiring 400 engineers on Databricks means more compute."}


def test_retry_count_belongs_to_its_own_row_when_rows_run_together(monkeypatch):
    install(monkeypatch, {"Ann": [BAD_NUMBER, GOOD], "Bob": [GOOD]})

    async def both():
        return await asyncio.gather(go("Ann", None), go("Bob", None), go("Ann", None), go("Bob", None))

    ann1, bob1, ann2, bob2 = asyncio.run(both())
    # Ann's queue is shared by her two rows: the first to ask gets the bad answer.
    assert sorted([ann1.personalization.metrics["retry_count"], ann2.personalization.metrics["retry_count"]]) == [0, 1]
    assert bob1.personalization.metrics["retry_count"] == 0 == bob2.personalization.metrics["retry_count"]


def test_a_retried_row_records_one_retry_and_a_grounding_retry(monkeypatch):
    install(monkeypatch, {"Ann": [BAD_NUMBER, GOOD]})
    m = asyncio.run(go("Ann", None)).personalization.metrics
    assert m["retry_count"] == 1 and m["grounding_retry"] is True and m["grounding_failure"] is False
    assert m["line_generated"] is True and m["sufficient"] is True and m["fit_established"] is True


def test_a_grounding_failure_that_survives_the_re_ask_is_recorded(monkeypatch):
    install(monkeypatch, {"Ann": [BAD_NUMBER, BAD_NUMBER]})
    m = asyncio.run(go("Ann", None)).personalization.metrics
    assert m["retry_count"] == 1 and m["grounding_failure"] is True and m["line_generated"] is False


def test_every_field_is_recorded_for_a_successful_row(monkeypatch):
    install(monkeypatch, {"Ann": [GOOD]})
    m = asyncio.run(go("Ann", None, cfg=settings(compact=True))).personalization.metrics
    assert m["output_mode"] == "personalized_line" and m["compact_research"] is True
    assert m["stage4_called"] and not m["stage1_stopped"] and m["line_generated"] and not m["hold"]
    assert m["total_tokens"] == m["stage1_tokens"] + m["stage4_tokens"] > 0
    assert m["retry_count"] == 0 and m["contact_issue"] is False
    assert set(m) >= {"output_mode", "compact_research", "stage1_tokens", "stage4_tokens", "total_tokens",
                      "stage1_stopped", "stage4_called", "line_generated", "hold", "contact_issue",
                      "retry_count", "grounding_failure", "sufficient", "fit_established"}


def test_stage_one_stops_and_contact_issues_are_recorded(monkeypatch):
    install(monkeypatch, {"Ann": [GOOD]}, d=dossier(signal=False))
    m = asyncio.run(go("Ann", None)).personalization.metrics
    assert m["stage1_stopped"] and not m["stage4_called"] and m["sufficient"] is None and not m["line_generated"]
    install(monkeypatch, {"Ann": [GOOD]}, d=dossier(issue="She left the company."))
    m = asyncio.run(go("Ann", None)).personalization.metrics
    assert m["hold"] and m["contact_issue"] and m["stage1_stopped"] and not m["stage4_called"]


def test_insufficient_evidence_is_recorded_as_not_sufficient(monkeypatch):
    install(monkeypatch, {"Ann": [{**GOOD, "angles": [], "sufficient": False, "reason": "thin",
                                    "fit_established": False, "fit_evidence": "", "personalized_line": ""}]})
    m = asyncio.run(go("Ann", None)).personalization.metrics
    assert m["sufficient"] is False and m["stage4_called"] and not m["line_generated"]
    assert m["fit_established"] is False


def test_metrics_hold_no_text_or_names(monkeypatch):
    install(monkeypatch, {"Ann": [GOOD]})
    text = json.dumps(asyncio.run(go("Ann", None)).personalization.metrics)
    for sensitive in ("Ann", "Doe", "Acme", "Databricks", LINE, USES, BLOG):
        assert sensitive not in text


def test_a_plain_full_message_row_gets_no_metrics(monkeypatch):
    install(monkeypatch, {"Ann": [{**GOOD, "personalization": LINE, "subject": None}]})
    out = asyncio.run(go("Ann", None, cfg=settings(mode=OutputMode.full_message)))
    assert out.personalization.metrics == {}


def test_full_message_retries_are_counted_too(monkeypatch):
    bad = {"angles": GOOD["angles"], "sufficient": True, "reason": "", "fit_established": True,
           "fit_evidence": USES, "personalization": "Hiring 400 engineers on Databricks.", "subject": None}
    good = {**bad, "personalization": LINE}
    install(monkeypatch, {"Ann": [bad, good]})
    out = asyncio.run(go("Ann", None, cfg=settings(mode=OutputMode.full_message, compact=True)))
    assert out.personalization.metrics["retry_count"] == 1


# --- the batch summary --------------------------------------------------------


def row(compact, *, line=True, total=10000, s1=6000, s4=4000, called=True, retry=0, ground=False, issue=False,
        stopped=False, hold=False):
    return dict(output_mode="personalized_line", compact_research=compact, line_generated=line,
                total_tokens=total, stage1_tokens=s1, stage4_tokens=s4 if called else 0, stage4_called=called,
                stage1_stopped=stopped, retry_count=retry, grounding_failure=ground, contact_issue=issue, hold=hold)


def test_tokens_per_line_divides_everything_spent_by_what_it_produced():
    rows = [row(False), row(False, line=False, called=False, total=6000, stopped=True), row(False, retry=1, total=14000)]
    s = measure.summarize(rows)
    assert s["rows"] == 3 and s["lines"] == 2 and s["line_pct"] == 66.7
    assert s["avg_tokens_per_row"] == 10000 and s["tokens_per_line"] == 15000
    assert s["stage1_stop_pct"] == 33.3 and s["stage4_call_pct"] == 66.7
    assert s["retry_rate_pct"] == 50.0 and s["blank_pct"] == 33.3
    assert s["avg_stage4_tokens_per_call"] == 4000 and s["avg_stage4_tokens_per_row"] == 2667


def test_a_cheaper_row_can_still_be_a_more_expensive_line():
    cheap = [row(True, total=5000, called=False, line=False, stopped=True)] * 3 + [row(True, total=12000)]
    steady = [row(False, total=11000)] * 3 + [row(False, total=9000, line=False)]
    report = measure.by_config(cheap + steady)
    a, b = report["A  line, compact OFF"], report["B  line, compact ON"]
    assert b["avg_tokens_per_row"] < a["avg_tokens_per_row"]
    assert (a["avg_tokens_per_row"], b["avg_tokens_per_row"]) == (10500, 6750)
    assert (a["tokens_per_line"], b["tokens_per_line"]) == (14000, 27000)  # ON is dearer per line here
    assert b["lines"] < a["lines"]


def test_configurations_are_kept_apart_and_unknowns_are_labelled():
    rows = [row(False), row(True), {**row(False), "output_mode": "full_message"}, {"total_tokens": 5}]
    report = measure.by_config(rows)
    assert report["A  line, compact OFF"]["rows"] == 1 and report["B  line, compact ON"]["rows"] == 1
    assert any(k.startswith("other: full_message") for k in report)
    text = measure.render(report)
    assert "TOTAL TOKENS / SUCCESSFUL LINE" in text and "line generation %" in text


def test_an_empty_group_reports_nothing_rather_than_dividing_by_zero():
    s = measure.summarize([])
    assert s["rows"] == 0 and s["tokens_per_line"] is None and s["line_pct"] is None
