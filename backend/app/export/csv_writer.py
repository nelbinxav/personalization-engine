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


def columns_for(kind: str, headers: list[str]) -> list[str]:
    if kind == "research":
        return headers + research_columns()
    if kind == "personalized":
        return headers + PERSONALIZATION_COLUMNS
    return headers + research_columns() + PERSONALIZATION_COLUMNS


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
        row["subject"] = (draft.subject or "") if draft else ""
        row["message"] = (draft.body or "") if draft else ""
        # Just the line the model wrote, for a sending tool's custom variable.
        row["personal_line"] = (draft.personal_line or "") if draft else ""
        row["angle_used"] = angle.angle if angle else ""
        row["evidence"] = angle.evidence if angle else ""
        row["evidence_source"] = angle.source_key if angle else ""
        # What showed the prospect has the problem we solve, and which copy the
        # row got: "ask_first" asks whether they do instead of assuming it.
        row["fit_evidence"] = personalization.fit_evidence or ""
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


async def stream_csv(upload_id: str, kind: str, headers: list[str]) -> AsyncIterator[str]:
    fieldnames = columns_for(kind, headers)

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
