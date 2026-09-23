"""Load rows from a Google Sheet URL.

Two paths, tried in order:
  1. Service account via the Sheets API -- works for private sheets shared with
     the service account's email. This is the intended production path.
  2. The public CSV export endpoint -- works for "anyone with the link" sheets
     and needs no credentials at all.

A service account avoids a consent screen and refresh-token handling entirely,
which is why it's preferred over user OAuth here.
"""
import json
import re

import httpx

from app.ingest.csv_loader import IngestError, parse_csv

_SHEET_ID = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_GID = re.compile(r"[#&?]gid=([0-9]+)")


def parse_sheet_url(url: str) -> tuple[str, str | None]:
    """Extract (spreadsheet_id, gid) from any Google Sheets URL form."""
    match = _SHEET_ID.search(url)
    if not match:
        raise IngestError(
            "That does not look like a Google Sheets URL. Expected something like "
            "https://docs.google.com/spreadsheets/d/<id>/edit"
        )
    gid_match = _GID.search(url)
    return match.group(1), gid_match.group(1) if gid_match else None


async def _load_public(sheet_id: str, gid: str | None) -> tuple[list[str], list[dict[str, str]]]:
    export = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        export += f"&gid={gid}"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(export)

    if response.status_code in (401, 403):
        raise IngestError(
            "That sheet is private. Either set link sharing to 'Anyone with the link "
            "(Viewer)', or share it with the service account email configured in Settings."
        )
    if response.status_code == 404:
        raise IngestError("Sheet not found. Check the URL.")
    response.raise_for_status()

    # Google serves an HTML sign-in page rather than a 403 in some sharing states.
    if response.content[:100].lstrip().lower().startswith(b"<!doctype html"):
        raise IngestError(
            "Google returned a sign-in page instead of the sheet. Share the sheet with "
            "the service account, or enable link sharing."
        )

    return parse_csv(response.content)


def _load_via_service_account(
    sheet_id: str, credentials_json: str, tab: str | None
) -> tuple[list[str], list[dict[str, str]]]:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(credentials_json)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_range = f"{tab}!A1:ZZ" if tab else "A1:ZZ"
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=sheet_range)
        .execute()
    )
    values: list[list[str]] = result.get("values", [])
    if not values:
        raise IngestError("The sheet is empty.")

    headers = [str(h).strip() for h in values[0]]
    rows: list[dict[str, str]] = []
    for raw in values[1:]:
        # The API truncates trailing empty cells, so pad short rows.
        padded = list(raw) + [""] * (len(headers) - len(raw))
        row = {h: str(v).strip() for h, v in zip(headers, padded) if h}
        if any(row.values()):
            rows.append(row)

    if not rows:
        raise IngestError("The sheet has a header but no data rows.")

    return headers, rows


async def load_sheet(
    url: str, tab: str | None = None, credentials_json: str | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    sheet_id, gid = parse_sheet_url(url)

    if credentials_json:
        try:
            return _load_via_service_account(sheet_id, credentials_json, tab)
        except IngestError:
            raise
        except Exception as exc:  # noqa: BLE001 - fall back to the public path
            last_error = exc
        else:
            last_error = None
        if last_error is not None:
            try:
                return await _load_public(sheet_id, gid)
            except IngestError as public_exc:
                raise IngestError(
                    f"Service account read failed ({last_error}); public export also "
                    f"failed: {public_exc}"
                ) from last_error

    return await _load_public(sheet_id, gid)
