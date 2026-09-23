from enum import Enum

from pydantic import BaseModel, Field

from app.models.common import Doc, Identity


class UploadSource(str, Enum):
    csv = "csv"
    gsheet = "gsheet"


class Upload(Doc):
    name: str
    source: UploadSource
    sheet_url: str | None = None
    # Sheet tab; None means the first worksheet.
    sheet_tab: str | None = None
    headers: list[str] = Field(default_factory=list)
    # identity field name -> source column header. Missing key == unmapped.
    column_mapping: dict[str, str] = Field(default_factory=dict)
    row_count: int = 0


class UploadPreview(BaseModel):
    """Returned before an upload is committed, so the operator can map columns."""

    headers: list[str]
    sample_rows: list[dict[str, str]]
    row_count: int
    suggested_mapping: dict[str, str]
    # Server-side handle for the parsed rows awaiting commit.
    staging_id: str


class CommitUploadRequest(BaseModel):
    staging_id: str
    name: str
    column_mapping: dict[str, str]


class UploadOut(BaseModel):
    id: str
    name: str
    source: UploadSource
    row_count: int
    headers: list[str]
    column_mapping: dict[str, str]
    created_at: object
    # Rollup so the list view doesn't need a second call per upload.
    scraped: int = 0
    personalized: int = 0


class SheetRequest(BaseModel):
    sheet_url: str
    sheet_tab: str | None = None


def identity_from_row(row: dict[str, str], mapping: dict[str, str]) -> Identity:
    """Project a raw sheet row onto the canonical Identity via the mapping."""
    values: dict[str, str] = {}
    for field, column in mapping.items():
        if not column:
            continue
        raw = (row.get(column) or "").strip()
        if raw:
            values[field] = raw
    return Identity(**values)
