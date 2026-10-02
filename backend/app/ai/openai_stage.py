"""Run one chain stage on an OpenAI model.

A stage can be given to an OpenAI model in Settings (per-stage models), which
is how a cheap, high-volume model does the fact gathering while Claude writes.
It is always an API-key call: there is no OpenAI equivalent of the Claude
subscription mode, so a GPT stage is billed per token whatever the Claude
credential mode is.

Uses the Responses API over plain HTTP, with the same strict JSON schema the
Claude path uses, so the chain cannot tell which provider answered.
"""
import json
import logging

import httpx

from app.ai.client import AuthUnavailable
from app.core import settings_store
from app.models.prospect import Usage

logger = logging.getLogger(__name__)

RESPONSES_URL = "https://api.openai.com/v1/responses"
_TIMEOUT = 300
# Keywords pydantic emits that strict structured outputs does not accept.
_UNSUPPORTED_KEYWORDS = ("default", "title", "examples")


class OpenAIError(Exception):
    """The stage failed in a way that should mark the row failed."""


class OpenAIRefusal(OpenAIError):
    pass


class OpenAIBusy(Exception):
    """Rate-limited, overloaded or unreachable: worth trying again later."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def is_openai_model(model: str) -> bool:
    return model.startswith("gpt-")


def openai_schema(node):
    """The strict schema minus the keywords OpenAI's strict mode rejects."""
    if isinstance(node, list):
        return [openai_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            # Property names are data, not keywords: a field called "title" stays.
            out[key] = {name: openai_schema(sub) for name, sub in value.items()}
        elif key not in _UNSUPPORTED_KEYWORDS:
            out[key] = openai_schema(value)
    return out


def build_request(
    *, model: str, system_text: str, user_text: str, schema: dict, effort: str, max_tokens: int
) -> dict:
    return {
        "model": model,
        "input": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "stage_output",
                "schema": openai_schema(schema),
                "strict": True,
            }
        },
        "reasoning": {"effort": effort},
        "max_output_tokens": max_tokens,
        # Nothing about a prospect needs to be kept on OpenAI's side.
        "store": False,
    }


def parse_response(data: dict) -> tuple[dict, Usage]:
    """Turn a Responses API body into (parsed, usage). Pulled out of
    `run_stage` so it is testable without the network."""
    if data.get("status") == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason") or "unknown"
        raise OpenAIError(
            f"The response was cut off ({reason}). Raise max tokens in Settings or shorten "
            "the template."
        )

    text = None
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if block.get("type") == "refusal":
                raise OpenAIRefusal(f"The model declined this request: {block.get('refusal', '')}")
            if block.get("type") == "output_text" and text is None:
                text = block.get("text")
    if not text:
        raise OpenAIError("The model returned no text content")

    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise OpenAIError(f"The model returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise OpenAIError("The model returned JSON that is not an object")

    raw = data.get("usage") or {}
    cached = (raw.get("input_tokens_details") or {}).get("cached_tokens") or 0
    usage = Usage(
        # Reported the way the Claude path reports it: fresh input and cache
        # reads separately, so pricing applies the right rate to each.
        input_tokens=max((raw.get("input_tokens") or 0) - cached, 0),
        output_tokens=raw.get("output_tokens") or 0,
        cache_read_input_tokens=cached,
    )
    return parsed, usage


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def _error_message(response: httpx.Response) -> tuple[str, str]:
    try:
        error = response.json().get("error") or {}
        return str(error.get("message") or response.text[:300]), str(error.get("code") or "")
    except ValueError:
        return response.text[:300], ""


async def run_stage(
    *, system_text: str, user_text: str, schema: dict, model: str, effort: str, max_tokens: int
) -> tuple[dict, Usage]:
    key = await settings_store.provider_key("openai")
    if not key:
        raise AuthUnavailable(
            f"A stage is set to {model}, but no OpenAI API key is saved. Add one under "
            "Settings, Keys, or give that stage a Claude model."
        )

    payload = build_request(
        model=model,
        system_text=system_text,
        user_text=user_text,
        schema=schema,
        effort=effort,
        max_tokens=max_tokens,
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                RESPONSES_URL, json=payload, headers={"Authorization": f"Bearer {key}"}
            )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise OpenAIBusy(f"Could not reach the OpenAI API: {exc}") from exc

    if response.status_code >= 400:
        message, code = _error_message(response)
        if response.status_code == 401:
            raise AuthUnavailable(f"OpenAI rejected the API key: {message}")
        if response.status_code == 429 and code == "insufficient_quota":
            # Not a rate limit: the account has no credit, and waiting will not fix it.
            raise AuthUnavailable(f"The OpenAI account is out of credit: {message}")
        if response.status_code == 429 or response.status_code >= 500:
            raise OpenAIBusy(
                f"OpenAI is rate-limiting or unavailable ({response.status_code}): {message}",
                _retry_after(response),
            )
        raise OpenAIError(f"OpenAI API error {response.status_code}: {message}")

    return parse_response(response.json())
