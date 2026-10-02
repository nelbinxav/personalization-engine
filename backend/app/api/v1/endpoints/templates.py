import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import current_operator
from app.db import mongo
from app.models.common import Channel
from app.models.template import CHANNEL_DEFAULTS, Template, TemplateIn, TemplateOut

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/templates", tags=["templates"], dependencies=[Depends(current_operator)]
)


@router.get("/channels")
async def channels() -> dict:
    return {
        "channels": [
            {
                "key": channel.value,
                "constraints": CHANNEL_DEFAULTS[channel].model_dump(),
            }
            for channel in Channel
        ]
    }


def _out(doc: dict) -> TemplateOut:
    template = Template.model_validate(doc)
    return TemplateOut(
        id=template.id,
        channel=template.channel,
        name=template.name,
        body=template.body,
        fallback_body=template.fallback_body,
        constraints=template.constraints,
        version=template.version,
        is_active=template.is_active,
        created_at=template.created_at,
    )


@router.get("", response_model=list[TemplateOut])
async def list_templates(channel: Channel | None = None) -> list[TemplateOut]:
    query = {"channel": channel.value} if channel else {}
    cursor = mongo.templates().find(query).sort([("channel", 1), ("version", -1)])
    return [_out(doc) async for doc in cursor]


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(payload: TemplateIn) -> TemplateOut:
    latest = await mongo.templates().find_one(
        {"channel": payload.channel.value}, sort=[("version", -1)]
    )
    version = (latest or {}).get("version", 0) + 1

    template = Template(
        channel=payload.channel,
        name=payload.name,
        body=payload.body,
        fallback_body=payload.fallback_body,
        constraints=payload.constraints or CHANNEL_DEFAULTS[payload.channel],
        version=version,
        is_active=payload.activate,
    )
    if payload.activate:
        await mongo.templates().update_many(
            {"channel": payload.channel.value}, {"$set": {"is_active": False}}
        )

    await mongo.templates().insert_one(template.to_mongo())
    logger.info("Created template v%d for %s", version, payload.channel.value)
    return _out(template.to_mongo())


@router.post("/{template_id}/activate", response_model=TemplateOut)
async def activate_template(template_id: str) -> TemplateOut:
    doc = await mongo.templates().find_one({"_id": template_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")

    await mongo.templates().update_many({"channel": doc["channel"]}, {"$set": {"is_active": False}})
    await mongo.templates().update_one({"_id": template_id}, {"$set": {"is_active": True}})

    doc["is_active"] = True
    return _out(doc)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str) -> None:
    doc = await mongo.templates().find_one({"_id": template_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    if doc.get("is_active"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot delete the active template. Activate another version first.",
        )
    await mongo.templates().delete_one({"_id": template_id})
