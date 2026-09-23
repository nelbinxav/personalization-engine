import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.ai import pricing
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
from app.models.settings import AppSettings, CredentialMode, SettingsIn
from app.sources.registry import source_catalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(current_operator)])


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
                    "label": "Apify (implemented)",
                    "note": "Marketplace actors, pay per result.",
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
