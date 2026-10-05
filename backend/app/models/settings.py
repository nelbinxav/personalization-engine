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


class OutputMode(str, Enum):
    # The message is written from the approved template, as always.
    full_message = "full_message"
    # Temporary: only the personalised line is written, for a template that
    # lives in the sending platform. Nothing here assembles a message.
    personalized_line = "personalized_line"


class AIConfig(BaseModel):
    # Explicit, never inferred -- silently falling back to a key that bills the
    # wrong org is exactly the failure this avoids.
    mode: CredentialMode = CredentialMode.oauth
    model: str = "claude-sonnet-5-5"
    # Per-stage override, keyed by stage number: {"1": "gpt-6-luna"}. A stage
    # not listed uses `model`. A "gpt-" model always runs on the OpenAI API key,
    # whatever the Claude credential mode is.
    stage_models: dict[str, str] = Field(default_factory=dict)
    effort: dict[str, str] = Field(
        default_factory=lambda: {
            str(int(Stage.dossier)): "medium",
            str(int(Stage.angle)): "high",
            str(int(Stage.draft)): "high",
        }
    )
    # Stages 1 and 2 can be switched off if the chain proves to be overkill.
    enabled_stages: list[int] = Field(default_factory=lambda: [1, 2, 3])
    # Run stages 2 and 3 as one call (the stage 4 prompt) for slot templates.
    # False restores the three-call chain exactly as it was.
    combined_final: bool = True
    # "full_message" (default) or "personalized_line". Read per row, so changing
    # it in Settings applies to the next row without a restart.
    personalization_output_mode: OutputMode = OutputMode.full_message
    max_tokens: int = 8000
    # How much of each research source the model reads, after link targets and
    # images are stripped. Past the first screen a page is mostly navigation,
    # and every character here is paid for on every row. The full text is still
    # stored and exported. 0 means no cap.
    research_chars_per_source: int = 6000
    # ONE switch for two token savings, off by default (nothing below changes
    # until it is on):
    #   * research: each source is cut to `compact_chars_per_source` by choosing
    #     its most relevant paragraphs (app/ai/research_select.py) instead of
    #     taking the first `research_chars_per_source` characters;
    #   * stage 1: items such as funding, awards and certifications are kept but
    #     cannot on their own make has_signal true, so those rows stop before
    #     the expensive stage 4 call.
    # Turning it off restores the previous behaviour for new rows.
    compact_research: bool = False
    compact_chars_per_source: int = 3000
    # The campaign's own vocabulary (platform names, cost words, ...) that makes
    # a paragraph worth keeping. Empty: only generic signals are used.
    relevance_terms: list[str] = Field(default_factory=list)


class ProviderKeys(BaseModel):
    """Stored Fernet-encrypted; the API only ever returns masked values."""

    jina: str | None = None
    serper: str | None = None
    apify: str | None = None
    # Web search for podcasts and news. Optional: without it the free endpoint
    # is used, which allows only a few hundred searches a day.
    exa: str | None = None
    google_service_account_json: str | None = None
    # The API-key fallback credential. Stored here rather than in the process
    # environment so the api and worker containers both pick it up without a
    # restart -- and so it is never confused with the ANTHROPIC_API_KEY env var,
    # whose mere presence silently breaks OAuth mode.
    anthropic: str | None = None
    # Only used by stages set to an OpenAI model.
    openai: str | None = None


class AppSettings(BaseModel):
    id: str = Field(default=SETTINGS_ID, alias="_id")
    ai: AIConfig = Field(default_factory=AIConfig)
    provider_keys: ProviderKeys = Field(default_factory=ProviderKeys)
    enabled_sources: list[str] = Field(
        default_factory=lambda: [
            "linkedin_posts",
            "podcasts",
            "linkedin_profile",
            "linkedin_company",
            "news",
            "website",
            "rss",
        ]
    )
    concurrency: int = 4
    # What we're selling. Stage 2 needs this to judge whether an angle is
    # actually relevant rather than merely true.
    offer_context: str = ""
    linkedin_provider: str = "apify"
    # LinkedIn page reads allowed per day with the `account` provider. A row
    # costs about two (the person, and the company unless it is cached). It is
    # there to protect the LinkedIn account, not to save money.
    linkedin_daily_limit: int = 150
    # How fast those reads happen. Spreading them over the day looks less like
    # automation than a burst: 20 an hour is one read about every three minutes.
    linkedin_reads_per_hour: int = 20

    model_config = {"populate_by_name": True}


class AIConfigIn(BaseModel):
    mode: CredentialMode | None = None
    model: str | None = None
    stage_models: dict[str, str] | None = None
    effort: dict[str, str] | None = None
    enabled_stages: list[int] | None = None
    combined_final: bool | None = None
    personalization_output_mode: OutputMode | None = None
    compact_research: bool | None = None
    compact_chars_per_source: int | None = None
    relevance_terms: list[str] | None = None
    max_tokens: int | None = None
    research_chars_per_source: int | None = None


class SettingsIn(BaseModel):
    ai: AIConfigIn | None = None
    enabled_sources: list[str] | None = None
    concurrency: int | None = None
    offer_context: str | None = None
    linkedin_provider: str | None = None
    linkedin_daily_limit: int | None = None
    linkedin_reads_per_hour: int | None = None
    # Plaintext on the way in, encrypted at rest, masked on the way out.
    provider_keys: dict[str, str | None] | None = None
    anthropic_api_key: str | None = None
