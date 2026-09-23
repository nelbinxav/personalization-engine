import csv
import io

MAX_SAMPLE_ROWS = 5


class IngestError(Exception):
    """Raised when a file or sheet cannot be turned into rows."""


def _decode(data: bytes) -> str:
    # utf-8-sig strips the BOM Excel loves to add; cp1252 catches the rest.
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("Could not decode the file as text. Save it as UTF-8 CSV and retry.")


def parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Parse CSV/TSV bytes into (headers, rows). Blank rows are dropped."""
    text = _decode(data)
    if not text.strip():
        raise IngestError("The file is empty.")

    # Sniff the delimiter so tab- and semicolon-separated exports work too.
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise IngestError("The file has no header row.")

    headers = [(h or "").strip() for h in reader.fieldnames]
    if not any(headers):
        raise IngestError("The header row is blank.")

    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            (k or "").strip(): (v or "").strip()
            for k, v in raw.items()
            if k is not None
        }
        if any(row.values()):
            rows.append(row)

    if not rows:
        raise IngestError("The file has a header but no data rows.")

    return headers, rows


def sample(rows: list[dict[str, str]], n: int = MAX_SAMPLE_ROWS) -> list[dict[str, str]]:
    return rows[:n]
