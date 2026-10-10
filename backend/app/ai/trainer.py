"""Chat that trains an Agent: a conversation that keeps its profile up to date.

Each turn is two calls. The first is the conversation itself, plain text,
streamed to the operator word by word where the provider allows it. The second
reads the conversation and returns the updated profile, so the talk stays
natural and the profile stays structured.

Both system prompts are fixed. The conversation, the profile so far and any
attached text go in the user turn, so the prefix is the same for every agent and
prompt caching works. `claude_code` and OpenAI models cannot stream plain text
through the stage path, so they send the reply in one piece.
"""
import logging
from collections.abc import AsyncIterator
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.ai import openai_stage
from app.ai.chain import ChainError, RateLimited, call_stage
from app.ai.client import AuthUnavailable, get_client
from app.ai.schemas import ChatSchema, ProfileUpdateSchema
from app.models.agent import AgentProfile
from app.models.settings import AppSettings, CredentialMode

logger = logging.getLogger(__name__)

CHAT_PROMPT = """You are a colleague helping an operator set up a sales agent that writes outreach for one offer. You talk with them like a person: short, warm, direct. Behind the scenes a profile is kept up to date from what they tell you.

THE PROFILE
offer (what we sell, in a sentence or two), what_we_do, icp (who it is for and the problem it solves), proof_points (facts, numbers and customers we may cite), voice (tone and style), sample_messages (examples in our voice), objections (each with the response we want), qualification (what makes a prospect a good fit), booking_link, never_claim (things the agent must never say or promise), relevance_terms (the platforms, costs, changes and other words that make a paragraph of research worth reading for this offer).

HOW TO TALK
- The operator can paste text, attach documents or just talk. Anything they give you is material: read it, take what it clearly says, and do not make them repeat it.
- Say briefly what you took from their message, then move on. Do not recite the whole profile back.
- Ask for what is missing in plain conversation. One or two related questions at a time is fine; never a numbered form. Skip what the material already answered.
- The operator may change anything at any time ("drop the second proof point", "make the voice less formal", "never mention pricing"). Do it, confirm in a line, carry on.
- Never invent proof points, numbers, customers or claims. If you are unsure, ask.
- When the offer, what we do, who it is for, the voice and at least one proof point are covered, say the profile is ready to save, and keep helping if they want more.
- With no messages yet: if the profile is empty, greet briefly, ask what they sell, and say they can paste or attach anything they already have. If the profile already has content, say in a line what it covers and ask what they want to change or add.
- Plain text only: no headings, no markdown tables, no JSON."""

UPDATE_PROMPT = """You keep the structured profile of a sales agent up to date from a conversation between an operator and their assistant.

PROFILE FIELDS
offer, what_we_do, icp, proof_points, voice, sample_messages, objections (each with the response we want), qualification, booking_link, never_claim, relevance_terms (short lowercase words such as platform names, cost and migration; suggest them from the offer, the operator can edit).

RULES
- Start from PROFILE SO FAR. Keep what is filled unless the operator changed or removed it in the conversation.
- Record the operator's facts as they gave them, tidied but not embellished. Never invent proof points, numbers, customers or claims. Attached text counts as the operator's material: fill what it clearly states.
- Apply edits the operator asked for (remove, reword, replace).
- `missing` lists the field names still empty or thin.
- Set `done` true only when offer, what_we_do, icp, voice and at least one proof point are filled."""

MAX_ATTACHMENT_CHARS = 12000


class Attachment(BaseModel):
    name: str = ""
    text: str = ""


class Message(BaseModel):
    role: Literal["user", "assistant"]
    text: str = ""
    attachments: list[Attachment] = Field(default_factory=list)


class TrainRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    profile: AgentProfile = Field(default_factory=AgentProfile)


def build_user_text(request: TrainRequest, *, ask: str) -> str:
    lines = []
    for m in request.messages:
        who = "OPERATOR" if m.role == "user" else "ASSISTANT"
        lines.append(f"{who}: {m.text}".rstrip())
        for a in m.attachments:
            body = a.text.strip()[:MAX_ATTACHMENT_CHARS]
            if body:
                lines.append(f"[Attached: {a.name or 'untitled'}]\n{body}\n[End of attachment]")
    return (
        "PROFILE SO FAR\n"
        + request.profile.model_dump_json(indent=2)
        + "\n\nCONVERSATION\n"
        + ("\n".join(lines) or "(none yet)")
        + f"\n\n{ask}"
    )


class ProfileUpdate(BaseModel):
    profile: AgentProfile
    missing: list[str]
    done: bool


def _model_and_client_mode(settings: AppSettings) -> tuple[str, bool, bool]:
    model = settings.ai.model
    subscription = settings.ai.mode is CredentialMode.claude_code
    needs_claude = not openai_stage.is_openai_model(model)
    return model, subscription, needs_claude


async def _stream_reply(request: TrainRequest, settings: AppSettings) -> AsyncIterator[str]:
    model, subscription, needs_claude = _model_and_client_mode(settings)
    user_text = build_user_text(
        request, ask="Write your next message to the operator, as the ASSISTANT."
    )

    if subscription or not needs_claude:
        # No plain-text streaming through the CLI or OpenAI stage: one piece.
        result = await call_stage(
            None,
            system_text=CHAT_PROMPT,
            user_text=user_text,
            schema_model=ChatSchema,
            model=model,
            effort="low",
            max_tokens=2000,
            cacheable=True,
        )
        yield ChatSchema.model_validate(result.parsed).reply
        return

    client = await get_client()
    try:
        async with client.messages.stream(
            model=model,
            max_tokens=2000,
            system=[
                {"type": "text", "text": CHAT_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
            ],
            messages=[{"role": "user", "content": user_text}],
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except anthropic.AuthenticationError as exc:
        raise AuthUnavailable(f"Claude rejected the credential: {exc}") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AuthUnavailable(f"Claude credential lacks permission: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise RateLimited(f"Claude rate limit reached: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise ChainError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RateLimited(f"Could not reach the Claude API: {exc}") from exc


async def update_profile(request: TrainRequest, settings: AppSettings) -> ProfileUpdate:
    model, subscription, needs_claude = _model_and_client_mode(settings)
    client = None if subscription or not needs_claude else await get_client()
    result = await call_stage(
        client,
        system_text=UPDATE_PROMPT,
        user_text=build_user_text(request, ask="Return the updated profile."),
        schema_model=ProfileUpdateSchema,
        model=model,
        effort="low",
        max_tokens=4000,
        cacheable=True,
    )
    parsed = ProfileUpdateSchema.model_validate(result.parsed)
    return ProfileUpdate(
        # The trainer owns the profile text; the writing switches stay as set.
        profile=AgentProfile.model_validate(
            {**request.profile.model_dump(), **parsed.profile.model_dump()}
        ),
        missing=parsed.missing,
        done=parsed.done,
    )


async def chat_events(request: TrainRequest, settings: AppSettings) -> AsyncIterator[dict]:
    """One turn as events: `delta` text as it arrives, `reply_done`, then `profile`, then `done`.

    A failure is an `error` event rather than an exception, because the response
    has already started by then.
    """
    reply = ""
    try:
        async for text in _stream_reply(request, settings):
            reply += text
            yield {"type": "delta", "text": text}
        yield {"type": "reply_done"}

        # The profile is updated from the conversation including this reply.
        full = request.model_copy(
            update={"messages": [*request.messages, Message(role="assistant", text=reply)]}
        )
        update = await update_profile(full, settings)
        yield {"type": "profile", **update.model_dump(mode="json")}
        yield {"type": "done"}
    except AuthUnavailable as exc:
        yield {"type": "error", "message": str(exc)}
    except RateLimited as exc:
        yield {"type": "error", "message": f"{exc} Try again in a minute."}
    except ChainError as exc:
        yield {"type": "error", "message": str(exc)}
    except Exception:  # noqa: BLE001 - the stream is open; report, never raise
        logger.exception("Agent chat turn failed")
        yield {"type": "error", "message": "Something went wrong. Try sending that again."}
