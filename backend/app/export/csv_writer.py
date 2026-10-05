"""Streaming CSV export.

Rows are yielded one at a time straight from the mongo cursor so a 10,000-row
upload never materializes in memory.

Every export starts with the sheet's original columns, verbatim and in their
original order, so the file can be pasted straight back into whatever tool it
came from.
"""
import csv
import io
from typing import AsyncIterator

from app.db import mongo
from app.models.prospect import Prospect, outreach_of
from app.sources.registry import ALL_SOURCES

RESEARCH_ERROR_COLUMN = "research_errors"


def research_columns() -> list[str]:
    return [f"research_{key}" for key in ALL_SOURCES] + [RESEARCH_ERROR_COLUMN]


PERSONALIZATION_COLUMNS = [
    # What to do with the row: personalised / generic / hold. Filter on this.
    "outreach",
    "channel",
    "subject",
    "message",
    "personal_line",
    "angle_used",
    "evidence",
    "evidence_source",
    "fit_evidence",
    "copy_used",
    "status",
    "status_note",
    "model",
    "cost_usd",
]


# A row written with output_mode "personalized_line" has its line in its own
# column for the sending platform; it never has a subject, message or template
# copy. Each row is exported by the mode stored on it, so changing the setting
# later cannot reinterpret rows already written.
LINE_COLUMNS = [
    "outreach",
    "channel",
    "personalized_line",
    "angle_used",
    "evidence",
    "evidence_source",
    "fit_evidence",
    "status",
    "status_note",
    "model",
    "cost_usd",
]
_LINE_ONLY = "personalized_line"
LINE_MODE = "personalized_line"


def personalization_columns(has_full: bool = True, has_line: bool = False) -> list[str]:
    """The columns for an upload, by the modes its rows were written in. Rows of
    one mode only get that mode's columns; a mixed upload gets both sets, and
    each row leaves the other mode's columns blank."""
    if has_line and not has_full:
        return LINE_COLUMNS
    if has_line:
        at = PERSONALIZATION_COLUMNS.index("personal_line") + 1
        return PERSONALIZATION_COLUMNS[:at] + [_LINE_ONLY] + PERSONALIZATION_COLUMNS[at:]
    return PERSONALIZATION_COLUMNS


def columns_for(
    kind: str, headers: list[str], has_full: bool = True, has_line: bool = False
) -> list[str]:
    mine = personalization_columns(has_full, has_line)
    if kind == "research":
        return headers + research_columns()
    if kind == "personalized":
        return headers + mine
    return headers + research_columns() + mine


def row_for(kind: str, prospect: Prospect, headers: list[str]) -> dict[str, str]:
    # Original columns first, exactly as uploaded.
    row: dict[str, str] = {header: prospect.raw.get(header, "") for header in headers}

    if kind in ("research", "combined"):
        errors: list[str] = []
        for key in ALL_SOURCES:
            result = prospect.research.get(key)
            if result is None:
                row[f"research_{key}"] = ""
            elif result.ok:
                row[f"research_{key}"] = result.content or ""
            else:
                row[f"research_{key}"] = ""
                errors.append(f"{key}: {result.error}")
        row[RESEARCH_ERROR_COLUMN] = "; ".join(errors)

    if kind in ("personalized", "combined"):
        personalization = prospect.personalization
        draft = personalization.draft
        angle = personalization.angles[0] if personalization.angles else None

        row["outreach"] = outreach_of(prospect)
        row["channel"] = personalization.channel.value if personalization.channel else ""
        # Just the line the model wrote, for a sending tool's custom variable.
        line = (draft.personal_line or "") if draft else ""
        # This row's own mode decides, not the current setting.
        line_mode = personalization.output_mode == LINE_MODE
        if line_mode:
            row["personalized_line"] = line
        else:
            row["subject"] = (draft.subject or "") if draft else ""
            row["message"] = (draft.body or "") if draft else ""
            row["personal_line"] = line
        row["angle_used"] = angle.angle if angle else ""
        row["evidence"] = angle.evidence if angle else ""
        row["evidence_source"] = angle.source_key if angle else ""
        # What showed the prospect has the problem we solve, and which copy the
        # row got: "ask_first" asks whether they do instead of assuming it.
        row["fit_evidence"] = personalization.fit_evidence or ""
        if not line_mode:
            row["copy_used"] = (
                ("ask_first" if personalization.ask_first else "main") if draft else ""
            )
        row["status"] = prospect.personalize_status.value
        # Carries the thin-context reason and any surviving constraint violation,
        # so a reviewer can see why a row needs attention without opening the app.
        note = prospect.personalize_error or ""
        if personalization.constraint_warning:
            note = f"{note} | {personalization.constraint_warning}".strip(" |")
        row["status_note"] = note
        row["model"] = personalization.model or ""
        row["cost_usd"] = f"{personalization.cost_usd:.5f}" if personalization.cost_usd else ""

    return row


async def _modes_in(upload_id: str) -> tuple[bool, bool]:
    """(has_full, has_line) among the rows already personalized."""
    done = {"upload_id": upload_id, "personalization.generated_at": {"$ne": None}}
    has_line = bool(
        await mongo.prospects().count_documents(
            {**done, "personalization.output_mode": LINE_MODE}, limit=1
        )
    )
    # Rows written before output_mode existed have none, and are full messages.
    has_full = bool(
        await mongo.prospects().count_documents(
            {**done, "personalization.output_mode": {"$ne": LINE_MODE}}, limit=1
        )
    )
    # Nothing personalized yet: the usual full-message columns, as before.
    return (has_full or not has_line), has_line


async def stream_csv(upload_id: str, kind: str, headers: list[str]) -> AsyncIterator[str]:
    has_full, has_line = await _modes_in(upload_id)
    fieldnames = columns_for(kind, headers, has_full, has_line)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")

    def flush() -> str:
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return value

    # Excel needs the BOM to read UTF-8 CSV without mangling accented names.
    yield "﻿"
    writer.writeheader()
    yield flush()

    cursor = mongo.prospects().find({"upload_id": upload_id}).sort("row_index", 1)
    async for doc in cursor:
        prospect = Prospect.model_validate(doc)
        writer.writerow(row_for(kind, prospect, headers))
        yield flush()
