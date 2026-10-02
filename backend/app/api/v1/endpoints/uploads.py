import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import current_operator
from app.core import settings_store
from app.db import mongo
from app.ingest.csv_loader import IngestError, parse_csv, sample
from app.ingest.gsheet_loader import load_sheet
from app.ingest.mapping import IDENTITY_FIELDS, suggest_mapping, validate_mapping
from app.models.common import new_id, utcnow
from app.models.prospect import Prospect
from app.models.upload import (
    CommitUploadRequest,
    SheetRequest,
    Upload,
    UploadOut,
    UploadPreview,
    UploadSource,
    identity_from_row,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(current_operator)])

STAGING_TTL_MINUTES = 60
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
INSERT_CHUNK = 1000


async def _stage(
    headers: list[str],
    rows: list[dict[str, str]],
    source: UploadSource,
    name: str,
    sheet_url: str | None = None,
    sheet_tab: str | None = None,
) -> UploadPreview:
    staging_id = new_id()
    await mongo.staging().insert_one(
        {
            "_id": staging_id,
            "headers": headers,
            "rows": rows,
            "source": source.value,
            "name": name,
            "sheet_url": sheet_url,
            "sheet_tab": sheet_tab,
            "expires_at": utcnow() + timedelta(minutes=STAGING_TTL_MINUTES),
        }
    )

    # Re-offer the mapping the operator confirmed last time for an identical
    # header set; sheets from the same source tend to keep their shape.
    previous = await mongo.uploads().find_one({"headers": headers}, sort=[("created_at", -1)])
    mapping = (previous or {}).get("column_mapping") or suggest_mapping(headers)

    return UploadPreview(
        headers=headers,
        sample_rows=sample(rows),
        row_count=len(rows),
        suggested_mapping=mapping,
        staging_id=staging_id,
    )


@router.get("/identity-fields")
async def identity_fields() -> dict:
    return {"fields": IDENTITY_FIELDS}


@router.post("/preview/csv", response_model=UploadPreview)
async def preview_csv(file: UploadFile = File(...)) -> UploadPreview:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
        )
    try:
        headers, rows = parse_csv(data)
    except IngestError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return await _stage(headers, rows, UploadSource.csv, file.filename or "upload.csv")


@router.post("/preview/sheet", response_model=UploadPreview)
async def preview_sheet(payload: SheetRequest) -> UploadPreview:
    credentials = await settings_store.provider_key("google_service_account_json")
    try:
        headers, rows = await load_sheet(payload.sheet_url, payload.sheet_tab, credentials)
    except IngestError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    name = payload.sheet_tab or "Google Sheet"
    return await _stage(
        headers, rows, UploadSource.gsheet, name, payload.sheet_url, payload.sheet_tab
    )


@router.post("/commit", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def commit(payload: CommitUploadRequest) -> UploadOut:
    staged = await mongo.staging().find_one({"_id": payload.staging_id})
    if not staged:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This upload expired before it was committed. Re-upload the file.",
        )

    headers: list[str] = staged["headers"]
    rows: list[dict[str, str]] = staged["rows"]

    # Drop unmapped fields so a blank select in the UI does not persist as "".
    mapping = {field: column for field, column in payload.column_mapping.items() if column}
    problems = validate_mapping(mapping, headers)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "; ".join(problems))

    upload = Upload(
        name=payload.name or staged["name"],
        source=UploadSource(staged["source"]),
        sheet_url=staged.get("sheet_url"),
        sheet_tab=staged.get("sheet_tab"),
        headers=headers,
        column_mapping=mapping,
        row_count=len(rows),
    )
    await mongo.uploads().insert_one(upload.to_mongo())

    docs = [
        Prospect(
            upload_id=upload.id,
            row_index=index,
            raw=row,
            identity=identity_from_row(row, mapping),
        ).to_mongo()
        for index, row in enumerate(rows)
    ]
    # Chunked so a large sheet cannot exceed mongo's 16MB per-write limit.
    for start in range(0, len(docs), INSERT_CHUNK):
        await mongo.prospects().insert_many(docs[start : start + INSERT_CHUNK])

    await mongo.staging().delete_one({"_id": payload.staging_id})
    logger.info("Committed upload %s (%s) with %d rows", upload.id, upload.name, len(docs))

    return await upload_out(upload.to_mongo())


async def upload_out(doc: dict) -> UploadOut:
    upload_id = doc["_id"]
    scraped = await mongo.prospects().count_documents(
        {"upload_id": upload_id, "scrape_status": "done"}
    )
    personalized = await mongo.prospects().count_documents(
        {"upload_id": upload_id, "personalize_status": {"$in": ["done", "thin_context", "needs_review"]}}
    )
    return UploadOut(
        id=upload_id,
        name=doc["name"],
        source=doc["source"],
        row_count=doc.get("row_count", 0),
        headers=doc.get("headers", []),
        column_mapping=doc.get("column_mapping", {}),
        created_at=doc.get("created_at"),
        scraped=scraped,
        personalized=personalized,
    )


@router.get("", response_model=list[UploadOut])
async def list_uploads(limit: int = 50) -> list[UploadOut]:
    cursor = mongo.uploads().find().sort("created_at", -1).limit(limit)
    return [await upload_out(doc) async for doc in cursor]


@router.get("/{upload_id}", response_model=UploadOut)
async def get_upload(upload_id: str) -> UploadOut:
    doc = await mongo.uploads().find_one({"_id": upload_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    return await upload_out(doc)


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(upload_id: str) -> None:
    result = await mongo.uploads().delete_one({"_id": upload_id})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    await mongo.prospects().delete_many({"upload_id": upload_id})
    await mongo.jobs().delete_many({"upload_id": upload_id})
