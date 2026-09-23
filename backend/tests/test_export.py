from app.export.csv_writer import columns_for, row_for
from app.models.common import Channel, Identity, RowStatus
from app.models.prospect import Angle, Draft, Personalization, Prospect, SourceResult

HEADERS = ["Full Name", "Company", "Website"]


def _prospect(**overrides) -> Prospect:
    base = dict(
        upload_id="u1",
        row_index=0,
        raw={"Full Name": "Ada Lovelace", "Company": "Analytical", "Website": "example.com"},
        identity=Identity(full_name="Ada Lovelace", company="Analytical"),
    )
    base.update(overrides)
    return Prospect(**base)


def test_original_columns_come_first_and_unchanged():
    columns = columns_for("combined", HEADERS)
    assert columns[:3] == HEADERS

    row = row_for("combined", _prospect(), HEADERS)
    assert row["Full Name"] == "Ada Lovelace"
    assert row["Website"] == "example.com"


def test_research_export_separates_content_from_errors():
    prospect = _prospect(
        research={
            "website": SourceResult(key="website", ok=True, content="About Analytical"),
            "news": SourceResult(key="news", ok=False, error="No recent news found"),
        }
    )
    row = row_for("research", prospect, HEADERS)

    assert row["research_website"] == "About Analytical"
    assert row["research_news"] == ""
    assert "news: No recent news found" in row["research_errors"]


def test_a_source_that_never_ran_is_blank_not_an_error():
    row = row_for("research", _prospect(), HEADERS)
    assert row["research_linkedin_profile"] == ""
    assert row["research_errors"] == ""


def test_personalized_export_carries_the_message_and_its_evidence():
    prospect = _prospect(
        personalize_status=RowStatus.done,
        personalization=Personalization(
            channel=Channel.email,
            draft=Draft(subject="Databricks spend", body="Hi Ada,"),
            angles=[
                Angle(angle="They just migrated", evidence="Blog post about migration", source_key="rss")
            ],
            model="claude-opus-5",
            cost_usd=0.0123,
        ),
    )
    row = row_for("personalized", prospect, HEADERS)

    assert row["subject"] == "Databricks spend"
    assert row["message"] == "Hi Ada,"
    assert row["angle_used"] == "They just migrated"
    assert row["evidence_source"] == "rss"
    assert row["status"] == "done"
    assert row["cost_usd"] == "0.01230"


def test_thin_context_reason_reaches_the_reviewer_in_the_csv():
    prospect = _prospect(
        personalize_status=RowStatus.thin_context,
        personalize_error="Website was a parked domain",
    )
    row = row_for("personalized", prospect, HEADERS)

    assert row["status"] == "thin_context"
    assert row["status_note"] == "Website was a parked domain"
    assert row["message"] == ""


def test_constraint_warning_is_appended_to_the_note():
    prospect = _prospect(
        personalize_status=RowStatus.done,
        personalize_error=None,
        personalization=Personalization(
            channel=Channel.linkedin,
            draft=Draft(body="x" * 320),
            constraint_warning="Body is 320 characters; the limit is 300.",
        ),
    )
    row = row_for("personalized", prospect, HEADERS)
    assert "320 characters" in row["status_note"]


def test_combined_export_has_both_column_families():
    columns = columns_for("combined", HEADERS)
    assert "research_website" in columns
    assert "message" in columns
