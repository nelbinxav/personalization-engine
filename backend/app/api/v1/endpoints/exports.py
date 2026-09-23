import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import current_operator
from app.db import mongo
from app.export.csv_writer import stream_csv

router = APIRouter(prefix="/exports", tags=["exports"], dependencies=[Depends(current_operator)])

KINDS = ("research", "personalized", "combined")


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "export"
    return stem[:60]


@router.get("/{upload_id}")
async def export_upload(
    upload_id: str,
    kind: str = Query("combined", pattern="^(research|personalized|combined)$"),
):
    upload = await mongo.uploads().find_one({"_id": upload_id})
    if not upload:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")

    headers: list[str] = upload.get("headers", [])
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"{_safe_filename(upload['name'])}-{kind}-{stamp}.csv"

    return StreamingResponse(
        stream_csv(upload_id, kind, headers),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
