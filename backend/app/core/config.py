from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment configuration.

    Note: unlike gc-website-backend (pydantic v1 BaseSettings), this project is on
    pydantic v2 + pydantic-settings.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- storage -------------------------------------------------------
    mongodb_url: str = "mongodb://mongo:27017"
    mongodb_db: str = "personalization"
    redis_url: str = "redis://redis:6379"

    # --- app -----------------------------------------------------------
    # Used to encrypt provider API keys at rest and to sign session cookies.
    app_secret_key: str = ""
    session_ttl_hours: int = 24 * 14
    allowed_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = False

    # --- anthropic -------------------------------------------------------
    # Persisted OAuth profile lives here; mounted as a shared docker volume so
    # the api and worker containers see the same credential.
    anthropic_config_dir: str = "/var/lib/anthropic"
    anthropic_oauth_profile: str = "app"
    anthropic_api_key: Optional[str] = None
    # Bootstrap fallback for stages given to an OpenAI model; Settings wins.
    openai_api_key: Optional[str] = None

    # --- scraping providers ------------------------------------------------
    # Fallbacks only; the UI-managed values in the `settings` collection win.
    jina_api_key: Optional[str] = None
    serper_api_key: Optional[str] = None
    apify_token: Optional[str] = None
    exa_api_key: Optional[str] = None
    # The LinkedIn browser service (docker compose profile "linkedin"), used by
    # the `account` LinkedIn provider.
    linkedin_mcp_url: str = "http://linkedin:8080/mcp"
    # Shared with the linkedin service: how Settings asks it to open a sign-in.
    linkedin_control_dir: str = "/var/lib/linkedin-control"

    # --- google sheets ------------------------------------------------------
    google_service_account_json: Optional[str] = None

    @property
    def effective_secret_key(self) -> str:
        if not self.app_secret_key:
            raise ValueError(
                "APP_SECRET_KEY is not set. Generate one with:\n"
                "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        return self.app_secret_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
