"""Load and persist the singleton AppSettings document.

Provider keys are Fernet-encrypted at rest. `load()` returns them decrypted for
internal use; the API layer is responsible for masking before responding.
"""
import logging

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.db import mongo
from app.models.settings import SETTINGS_ID, AppSettings, ProviderKeys

logger = logging.getLogger(__name__)

_SECRET_FIELDS = tuple(ProviderKeys.model_fields.keys())


def _decrypt_keys(raw: dict) -> dict:
    out = {}
    for field in _SECRET_FIELDS:
        value = raw.get(field)
        if not value:
            out[field] = None
            continue
        try:
            out[field] = decrypt_secret(value)
        except ValueError:
            # A rotated APP_SECRET_KEY shouldn't take the whole app down; drop the
            # unreadable key and let the operator re-enter it.
            logger.warning("Could not decrypt provider key '%s'; treating as unset", field)
            out[field] = None
    return out


async def load() -> AppSettings:
    doc = await mongo.app_settings().find_one({"_id": SETTINGS_ID})
    if not doc:
        return AppSettings()

    doc = dict(doc)
    doc["provider_keys"] = _decrypt_keys(doc.get("provider_keys") or {})
    return AppSettings.model_validate(doc)


async def save(settings: AppSettings) -> AppSettings:
    doc = settings.model_dump(by_alias=True)
    doc["provider_keys"] = {
        field: (encrypt_secret(value) if value else None)
        for field, value in (settings.provider_keys.model_dump()).items()
    }
    await mongo.app_settings().replace_one({"_id": SETTINGS_ID}, doc, upsert=True)
    return settings


async def provider_key(name: str) -> str | None:
    """UI-managed key wins; the .env value is a fallback for bootstrapping."""
    settings = await load()
    stored = getattr(settings.provider_keys, name, None)
    if stored:
        return stored

    env = get_settings()
    return {
        "jina": env.jina_api_key,
        "serper": env.serper_api_key,
        "apify": env.apify_token,
        "exa": env.exa_api_key,
        "google_service_account_json": env.google_service_account_json,
        "anthropic": env.anthropic_api_key,
        "openai": env.openai_api_key,
    }.get(name)
