import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import current_operator
from app.db import mongo
from app.models.operator import Operator
from app.models.prompt import STAGE_LABELS, Prompt, PromptIn, PromptOut, Stage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prompts", tags=["prompts"], dependencies=[Depends(current_operator)])


class StageInfo(BaseModel):
    stage: int
    label: str


@router.get("/stages", response_model=list[StageInfo])
async def stages() -> list[StageInfo]:
    return [StageInfo(stage=int(stage), label=label) for stage, label in STAGE_LABELS.items()]


def _out(doc: dict) -> PromptOut:
    prompt = Prompt.model_validate(doc)
    return PromptOut(
        id=prompt.id,
        stage=prompt.stage,
        name=prompt.name,
        body=prompt.body,
        version=prompt.version,
        is_active=prompt.is_active,
        created_at=prompt.created_at,
    )


@router.get("", response_model=list[PromptOut])
async def list_prompts(stage: int | None = None, active_only: bool = False) -> list[PromptOut]:
    query: dict = {}
    if stage is not None:
        query["stage"] = stage
    if active_only:
        query["is_active"] = True

    cursor = mongo.prompts().find(query).sort([("stage", 1), ("version", -1)])
    return [_out(doc) async for doc in cursor]


@router.post("", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    payload: PromptIn, operator: Operator = Depends(current_operator)
) -> PromptOut:
    """Saving a prompt always creates a new version.

    Nothing is edited in place, so an export generated last week can always be
    traced back to the exact prompt text that produced it.
    """
    latest = await mongo.prompts().find_one({"stage": int(payload.stage)}, sort=[("version", -1)])
    version = (latest or {}).get("version", 0) + 1

    prompt = Prompt(
        stage=payload.stage,
        name=payload.name,
        body=payload.body,
        version=version,
        is_active=payload.activate,
        created_by=operator.email,
    )
    if payload.activate:
        await mongo.prompts().update_many(
            {"stage": int(payload.stage)}, {"$set": {"is_active": False}}
        )

    await mongo.prompts().insert_one(prompt.to_mongo())
    logger.info("Created prompt v%d for stage %d", version, int(payload.stage))
    return _out(prompt.to_mongo())


@router.post("/{prompt_id}/activate", response_model=PromptOut)
async def activate_prompt(prompt_id: str) -> PromptOut:
    doc = await mongo.prompts().find_one({"_id": prompt_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prompt not found")

    await mongo.prompts().update_many({"stage": doc["stage"]}, {"$set": {"is_active": False}})
    await mongo.prompts().update_one({"_id": prompt_id}, {"$set": {"is_active": True}})

    doc["is_active"] = True
    return _out(doc)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(prompt_id: str) -> None:
    doc = await mongo.prompts().find_one({"_id": prompt_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prompt not found")
    if doc.get("is_active"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot delete the active prompt. Activate another version first.",
        )
    await mongo.prompts().delete_one({"_id": prompt_id})
