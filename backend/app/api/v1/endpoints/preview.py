"""Run the chain against a single prospect without saving anything.

This is the tight loop for prompt work: edit a prompt, see what it produces on
a real researched row, adjust. Draft prompt bodies can be passed inline, so a
prompt does not have to be saved as a new version just to try it.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.ai.agent_context import apply_profile, settings_with_agent
from app.ai.chain import ChainError, RateLimited, run_chain
from app.ai.client import AuthUnavailable
from app.api.deps import current_operator
from app.core import settings_store
from app.db import mongo
from app.models.agent import AgentProfile
from app.models.common import Channel
from app.models.prospect import Prospect
from app.models.template import Template

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/preview", tags=["preview"], dependencies=[Depends(current_operator)])


class PreviewRequest(BaseModel):
    prospect_id: str | None = None
    upload_id: str | None = None
    channel: Channel = Channel.email
    template_id: str | None = None
    agent_id: str | None = None
    # An agent profile that is not saved yet, to try a draft. Wins over agent_id.
    agent_profile: AgentProfile | None = None
    # With upload_id: skip this many researched rows, wrapping round at the end.
    offset: int = 0
    # Unsaved drafts, keyed by stage number as a string: {"1": "...", "3": "..."}
    prompt_bodies: dict[str, str] = {}
    template_body: str | None = None
    fallback_body: str | None = None


@router.post("")
async def preview(payload: PreviewRequest) -> dict:
    prospect = await _pick_prospect(payload)
    settings = await settings_store.load()
    if payload.agent_profile is not None:
        settings = apply_profile(settings, payload.agent_profile)
    else:
        settings = await settings_with_agent(settings, payload.agent_id)

    template = await _pick_template(payload)
    if payload.template_body is not None:
        template = template.model_copy(update={"body": payload.template_body})
    if payload.fallback_body is not None:
        template = template.model_copy(update={"fallback_body": payload.fallback_body})

    prompts: dict[int, str] = {}
    for stage in (1, 2, 3, 4):
        override = payload.prompt_bodies.get(str(stage))
        if override:
            prompts[stage] = override
            continue
        doc = await mongo.prompts().find_one({"stage": stage, "is_active": True})
        if not doc and stage == 4:
            continue
        if not doc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"No active prompt for stage {stage}."
            )
        prompts[stage] = doc["body"]

    try:
        output = await run_chain(
            identity=prospect.identity,
            raw=prospect.raw,
            research=prospect.research,
            prompts=prompts,
            template=template,
            settings=settings,
            channel=payload.channel,
        )
    except AuthUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except RateLimited as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"{exc} Try again in a minute."
        ) from exc
    except ChainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    personalization = output.personalization
    return {
        "prospect": {
            "id": prospect.id,
            "row_index": prospect.row_index,
            "name": prospect.identity.display_name,
            "company": prospect.identity.company,
            "sources": {key: result.ok for key, result in prospect.research.items()},
        },
        "dossier": personalization.dossier.model_dump() if personalization.dossier else None,
        "angles": [angle.model_dump() for angle in personalization.angles],
        "draft": personalization.draft.model_dump() if personalization.draft else None,
        "fit_established": personalization.fit_established,
        "fit_evidence": personalization.fit_evidence,
        "ask_first": personalization.ask_first,
        "thin_context": output.thin_context,
        "hold": output.hold,
        "reason": output.reason,
        "warnings": sorted(set(output.warnings)),
        "constraint_warning": personalization.constraint_warning,
        "usage": personalization.usage.model_dump(),
        "cost_usd": personalization.cost_usd,
    }


async def _pick_prospect(payload: PreviewRequest) -> Prospect:
    if payload.prospect_id:
        doc = await mongo.prospects().find_one({"_id": payload.prospect_id})
        if not doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found")
        prospect = Prospect.model_validate(doc)
        if not prospect.research:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "That row has no research yet. Run a scrape job on it first.",
            )
        return prospect

    if not payload.upload_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Provide either prospect_id or upload_id."
        )

    # Pick the first row that actually has research, so the preview is meaningful.
    query = {"upload_id": payload.upload_id, "scrape_status": "done"}
    total = await mongo.prospects().count_documents(query)
    doc = await mongo.prospects().find_one(
        query, sort=[("row_index", 1)], skip=payload.offset % total if total else 0
    )
    if not doc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No researched rows in this upload yet. Run a scrape job first.",
        )
    return Prospect.model_validate(doc)


async def _pick_template(payload: PreviewRequest) -> Template:
    doc = None
    if payload.template_id:
        doc = await mongo.templates().find_one({"_id": payload.template_id})
    if not doc:
        doc = await mongo.templates().find_one(
            {"channel": payload.channel.value, "is_active": True}
        )
    if not doc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No active template for channel '{payload.channel.value}'.",
        )
    return Template.model_validate(doc)
