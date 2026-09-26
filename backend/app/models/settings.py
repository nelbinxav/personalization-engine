from enum import Enum

from pydantic import BaseModel, Field

from app.models.prompt import Stage

SETTINGS_ID = "singleton"


class CredentialMode(str, Enum):
    oauth = "oauth"
    api_key = "api_key"
    # The operator's own Claude subscription, via the unmodified Claude Code
    # binary. See app/ai/claude_code.py for why it has to be done this way.
    claude_code = "claude_code"


class AIConfig(BaseModel):
    # Explicit, never inferred -- silently falling back to a key that bills the
    # wrong org is exactly the failure this avoids.
    mode: CredentialMode = CredentialMode.oauth
    model: str = "claude-opus-5"
    effort: dict[str, str] = Field(
        default_factory=lambda: {
            str(int(Stage.dossier)): "medium",
            str(int(Stage.angle)): "high",
            str(int(Stage.draft)): "high",
        }
    )
    # Stages 1 and 2 can be switched off if the chain proves to be overkill.
    enabled_stages: list[int] = Field(default_factory=lambda: [1, 2, 3])
    max_tokens: int = 8000


class ProviderKeys(BaseModel):
    """Stored Fernet-encrypted; the API only ever returns masked values."""

    jina: str | None = None
    serper: str | None = None
    apify: str | None = None
    google_service_account_json: str | None = None
    # The API-key fallback credential. Stored here rather than in the process
    # environment so the api and worker containers both pick it up without a
    # restart -- and so it is never confused with the ANTHROPIC_API_KEY env var,
    # whose mere presence silently breaks OAuth mode.
    anthropic: str | None = None


class AppSettings(BaseModel):
    id: str = Field(default=SETTINGS_ID, alias="_id")
    ai: AIConfig = Field(default_factory=AIConfig)
    provider_keys: ProviderKeys = Field(default_factory=ProviderKeys)
    enabled_sources: list[str] = Field(
        default_factory=lambda: ["website", "rss", "news", "linkedin_profile", "linkedin_company"]
    )
    concurrency: int = 4
    # What we're selling. Stage 2 needs this to judge whether an angle is
    # actually relevant rather than merely true.
    offer_context: str = ""
    linkedin_provider: str = "apify"

    model_config = {"populate_by_name": True}


class AIConfigIn(BaseModel):
    mode: CredentialMode | None = None
    model: str | None = None
    effort: dict[str, str] | None = None
    enabled_stages: list[int] | None = None
    max_tokens: int | None = None


class SettingsIn(BaseModel):
    ai: AIConfigIn | None = None
    enabled_sources: list[str] | None = None
    concurrency: int | None = None
    offer_context: str | None = None
    linkedin_provider: str | None = None
    # Plaintext on the way in, encrypted at rest, masked on the way out.
    provider_keys: dict[str, str | None] | None = None
    anthropic_api_key: str | None = None
