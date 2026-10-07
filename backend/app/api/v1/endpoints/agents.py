import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.ai.trainer import TrainRequest, chat_events
from app.api.deps import current_operator
from app.core import settings_store
from app.db import mongo
from app.models.agent import Agent, AgentIn, AgentOut
from app.models.common import new_id
from app.models.operator import Operator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(current_operator)])


def _out(doc: dict) -> AgentOut:
    agent = Agent.model_validate(doc)
    return AgentOut(
        id=agent.id,
        lineage_id=agent.lineage_id,
        name=agent.name,
        profile=agent.profile,
        version=agent.version,
        is_active=agent.is_active,
        created_at=agent.created_at,
    )


@router.get("", response_model=list[AgentOut])
async def list_agents(active_only: bool = False) -> list[AgentOut]:
    query: dict = {"is_active": True} if active_only else {}
    cursor = mongo.agents().find(query).sort([("lineage_id", 1), ("version", -1)])
    return [_out(doc) async for doc in cursor]


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentIn, operator: Operator = Depends(current_operator)
) -> AgentOut:
    """Saving always creates a new version; a new agent starts a new lineage."""
    lineage_id = payload.lineage_id or new_id()
    latest = await mongo.agents().find_one({"lineage_id": lineage_id}, sort=[("version", -1)])
    if payload.lineage_id and not latest:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    version = (latest or {}).get("version", 0) + 1

    agent = Agent(
        lineage_id=lineage_id,
        name=payload.name,
        profile=payload.profile,
        version=version,
        is_active=payload.activate,
        created_by=operator.email,
    )
    if payload.activate:
        await mongo.agents().update_many({"lineage_id": lineage_id}, {"$set": {"is_active": False}})

    await mongo.agents().insert_one(agent.to_mongo())
    logger.info("Created agent %s v%d", lineage_id, version)
    return _out(agent.to_mongo())


@router.post("/chat")
async def chat_agent(payload: TrainRequest) -> StreamingResponse:
    """One chat turn as server-sent events: `delta`, `reply_done`, `profile`, `done`."""
    settings = await settings_store.load()

    async def events():
        async for event in chat_events(payload, settings):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # No buffering anywhere on the way: the point is to see words as they come.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/{agent_id}/activate", response_model=AgentOut)
async def activate_agent(agent_id: str) -> AgentOut:
    doc = await mongo.agents().find_one({"_id": agent_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

    await mongo.agents().update_many({"lineage_id": doc["lineage_id"]}, {"$set": {"is_active": False}})
    await mongo.agents().update_one({"_id": agent_id}, {"$set": {"is_active": True}})
    doc["is_active"] = True
    return _out(doc)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str) -> None:
    doc = await mongo.agents().find_one({"_id": agent_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    if doc.get("is_active"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot delete the active version. Activate another version first.",
        )
    await mongo.agents().delete_one({"_id": agent_id})
