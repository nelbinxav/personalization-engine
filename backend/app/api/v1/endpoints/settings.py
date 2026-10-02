import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.ai import claude_code, pricing
from app.ai.client import (
    AuthUnavailable,
    ant_available,
    api_key_is_set,
    auth_status,
    oauth_complete,
    oauth_disconnect,
    oauth_start,
)
from app.api.deps import current_operator
from app.core import settings_store
from app.core.security import mask_secret
from app.db import mongo
from app.models.settings import AppSettings, CredentialMode, SettingsIn
from app.sources import linkedin_account, registry
from app.sources.base import SourceError
from app.sources.registry import source_catalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(current_operator)])


_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


class OAuthCompleteRequest(BaseModel):
    flow_id: str
    code: str


def _redact(settings: AppSettings) -> dict:
    data = settings.model_dump(by_alias=False)
    data["provider_keys"] = {
        name: mask_secret(value)
        for name, value in settings.provider_keys.model_dump().items()
    }
    return data


@router.get("")
async def get_settings_doc() -> dict:
    settings = await settings_store.load()
    return {
        "settings": _redact(settings),
        "catalog": {
            "sources": source_catalog(),
            "models": pricing.SELECTABLE_MODELS,
            "efforts": ["low", "medium", "high", "xhigh", "max"],
            "linkedin_providers": [
                {
                    "key": "apify",
                    "label": "Apify",
                    "note": "Marketplace actors, pay per result. Profiles and company pages "
                    "only: it cannot read recent posts.",
                },
                {
                    "key": "account",
                    "label": "Your LinkedIn account (Agent Reach route)",
                    "note": "Reads profiles, company pages and recent posts through a signed-in "
                    "LinkedIn account. Automated access is against LinkedIn's terms and the "
                    "account can be restricted, so reads are paced and capped per day. Needs "
                    "the LinkedIn service running and signed in (see deploy/LINKEDIN.md).",
                },
                {
                    "key": "brightdata",
                    "label": "Bright Data (not implemented)",
                    "note": "Add a _fetch_brightdata branch in app/sources/linkedin.py.",
                },
                {
                    "key": "scrapin",
                    "label": "ScrapIn (not implemented)",
                    "note": "Closest drop-in to the retired Proxycurl API shape.",
                },
                {
                    "key": "unipile",
                    "label": "Unipile (not implemented)",
                    "note": "Account-based: uses your own LinkedIn session, so it carries "
                    "account-ban risk rather than scraping-vendor risk.",
                },
            ],
        },
    }


@router.put("")
async def update_settings(payload: SettingsIn) -> dict:
    settings = await settings_store.load()

    if payload.ai:
        for field, value in payload.ai.model_dump(exclude_none=True).items():
            setattr(settings.ai, field, value)
    if payload.enabled_sources is not None:
        settings.enabled_sources = payload.enabled_sources
    if payload.concurrency is not None:
        settings.concurrency = max(1, min(payload.concurrency, 32))
    if payload.offer_context is not None:
        settings.offer_context = payload.offer_context
    if payload.linkedin_provider is not None:
        settings.linkedin_provider = payload.linkedin_provider
    if payload.linkedin_daily_limit is not None:
        settings.linkedin_daily_limit = max(1, min(payload.linkedin_daily_limit, 1000))
    if payload.linkedin_reads_per_hour is not None:
        settings.linkedin_reads_per_hour = max(1, min(payload.linkedin_reads_per_hour, 120))

    if payload.provider_keys:
        for name, value in payload.provider_keys.items():
            if not hasattr(settings.provider_keys, name):
                continue
            # "" clears a key; absent leaves it untouched.
            setattr(settings.provider_keys, name, value or None)

    await settings_store.save(settings)
    return {"settings": _redact(settings)}


@router.get("/ai/status")
async def ai_status() -> dict:
    settings = await settings_store.load()
    status_info = await auth_status()

    warning = None
    if settings.ai.mode is CredentialMode.oauth and api_key_is_set():
        warning = (
            "ANTHROPIC_API_KEY is set in the environment. It silently overrides the OAuth "
            "profile and would bill that key's org instead. Remove it from .env and "
            "docker-compose, then restart the api and worker."
        )

    return {
        "mode": settings.ai.mode.value,
        "connected": status_info.connected,
        "detail": status_info.detail,
        "organization": status_info.organization,
        "workspace": status_info.workspace,
        "ant_installed": ant_available(),
        "claude_code_installed": claude_code.available(),
        "api_key_in_env": api_key_is_set(),
        "warning": warning,
        "model": settings.ai.model,
    }


@router.post("/ai/oauth/start")
async def start_oauth() -> dict:
    """Begin the device flow.

    Returns an authorize URL. The `ant auth login` process stays alive in this
    API process waiting on stdin, so the API must run with a single worker.
    """
    try:
        return await oauth_start()
    except AuthUnavailable as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/ai/oauth/complete")
async def complete_oauth(payload: OAuthCompleteRequest) -> dict:
    try:
        result = await oauth_complete(payload.flow_id, payload.code)
    except AuthUnavailable as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return {
        "connected": result.connected,
        "organization": result.organization,
        "workspace": result.workspace,
        "detail": result.detail,
    }


@router.post("/ai/oauth/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_oauth() -> None:
    await oauth_disconnect()


@router.put("/ai/api-key")
async def set_api_key(payload: dict) -> dict:
    """Store an API key as the fallback credential.

    Kept separate from the general settings write so the key never travels in
    the same payload as the rest of the form.
    """
    key = (payload.get("api_key") or "").strip()
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "api_key is required")
    if not key.startswith("sk-ant-"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That does not look like an Anthropic API key (expected it to start with 'sk-ant-').",
        )

    # Persisted Fernet-encrypted rather than set in os.environ: the worker is a
    # separate process and would never see an environment mutation made here.
    settings = await settings_store.load()
    settings.provider_keys.anthropic = key
    settings.ai.mode = CredentialMode.api_key
    await settings_store.save(settings)

    return {"mode": "api_key", "connected": True}



@router.get("/linkedin")
async def linkedin_status() -> dict:
    """The LinkedIn account connection, for the Settings page."""
    cfg = await registry.build_config()
    async with httpx.AsyncClient() as client:
        return await linkedin_account.status(client, cfg)


@router.post("/linkedin/connect")
async def linkedin_connect() -> dict:
    """Open the LinkedIn service's sign-in browser. The link appears in the
    status a few seconds later; the operator signs in there, not here."""
    try:
        linkedin_account.request_login()
    except (SourceError, OSError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"login_state": "starting"}


@router.post("/linkedin/test")
async def linkedin_test() -> dict:
    """Read the connected account's own profile once, to prove it works. Counts
    as one of the day's LinkedIn reads."""
    cfg = await registry.build_config()
    try:
        async with httpx.AsyncClient() as client:
            who = await linkedin_account.test_connection(client, cfg)
    except SourceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"signed_in": True, "account": who[:120]}


@router.get("/usage")
async def usage() -> dict:
    """What personalization is consuming: the Claude plan's usage windows as
    Claude Code last reported them, and the tokens this app has used."""
    limits = await mongo.counters().find_one({"_id": "claude:limits"}) or {}
    limits.pop("_id", None)

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    def total(u: dict) -> int:
        return sum(int(u.get(k) or 0) for k in _USAGE_FIELDS)

    today = {"rows": 0, "tokens": 0}
    week = {"rows": 0, "tokens": 0}
    by_stage: dict[str, int] = {}
    cursor = mongo.prospects().find(
        {"personalization.generated_at": {"$ne": None}},
        {"personalization.generated_at": 1, "personalization.usage": 1, "personalization.usage_by_stage": 1},
    )
    async for doc in cursor:
        p = doc.get("personalization") or {}
        try:
            at = datetime.fromisoformat(str(p.get("generated_at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at < week_start:
            continue
        tokens = total(p.get("usage") or {})
        week["rows"] += 1
        week["tokens"] += tokens
        for stage, stage_usage in (p.get("usage_by_stage") or {}).items():
            by_stage[stage] = by_stage.get(stage, 0) + total(stage_usage)
        if at >= day_start:
            today["rows"] += 1
            today["tokens"] += tokens

    settings = await settings_store.load()
    return {
        "mode": settings.ai.mode.value,
        "limits": limits or None,
        "today": today,
        "last_7_days": week,
        "by_stage_7_days": by_stage,
        "tokens_per_row": round(week["tokens"] / week["rows"]) if week["rows"] else None,
    }
