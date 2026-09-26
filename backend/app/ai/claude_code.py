"""The `claude_code` credential mode: run each stage through the operator's own
Claude subscription, via the unmodified Claude Code binary.

Why it is built this way rather than as an OAuth flow in the app: Anthropic
does not permit third-party apps to offer Claude.ai login or to hold
subscription tokens. What it does permit is a user signing in to the
*unmodified* Claude Code binary with their own subscription. So:

  * the operator signs in themselves, in a terminal, with Claude Code's own
    login (`docker compose exec -it worker claude auth login`);
  * the credential lives in CLAUDE_CONFIG_DIR, written and read only by
    `claude` -- nothing in this app opens, copies or forwards it;
  * each stage is one `claude -p` call with tools off and the stage's system
    prompt, so it behaves like a plain Messages call.

Do not "optimise" this by reading the stored token and calling the API
directly. That is precisely the pattern that is not allowed.

Trade-offs to keep in mind: plan usage limits apply (a 500-row job can exhaust
them, which parks the job rather than failing rows), each call carries a
process start, and there is no prompt-cache control from here.
"""
import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass

from app.ai.client import AuthUnavailable
from app.models.prospect import Usage

logger = logging.getLogger(__name__)

_STAGE_TIMEOUT = 300

# Removed from the child environment. Either one outranks the subscription
# sign-in in Claude Code's credential order, which would quietly bill an API org.
_OVERRIDING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

_AUTH_MARKERS = ("not logged in", "/login", "invalid api key", "authentication", "oauth token")
_LIMIT_MARKERS = ("usage limit", "hit your limit", "limit reached", "rate limit")


class ClaudeCodeError(Exception):
    """A stage failed inside Claude Code; the row should be marked failed."""


class UsageLimitReached(AuthUnavailable):
    """The subscription's usage window is exhausted.

    A subclass of AuthUnavailable only so the worker parks the job instead of
    failing every remaining row. It is NOT a credential problem -- waiting fixes
    it, reconnecting does not -- and the message says so.
    """


@dataclass
class CodeStatus:
    installed: bool
    connected: bool
    detail: str
    account: str | None = None
    plan: str | None = None


def available() -> bool:
    return shutil.which("claude") is not None


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _OVERRIDING_ENV}
    env.setdefault("CLAUDE_CONFIG_DIR", "/var/lib/claude-code")
    return env


async def _exec(args: list[str], stdin: bytes | None, timeout: float) -> tuple[int, str, str]:
    # Empty working directory: nothing for Claude Code to pick up as project
    # context (CLAUDE.md, settings), so the stage prompt is the whole prompt.
    with tempfile.TemporaryDirectory(prefix="pe-claude-") as cwd:
        process = await asyncio.create_subprocess_exec(
            "claude",
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_child_env(),
            cwd=cwd,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(stdin), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            raise ClaudeCodeError(f"Claude Code did not finish within {timeout:.0f}s")
    return (
        process.returncode or 0,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


async def status() -> CodeStatus:
    if not available():
        return CodeStatus(
            installed=False,
            connected=False,
            detail="Claude Code is not installed in this container. Rebuild the image.",
        )
    try:
        _, out, err = await _exec(["auth", "status", "--json"], None, timeout=30)
    except ClaudeCodeError as exc:
        return CodeStatus(installed=True, connected=False, detail=str(exc))

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return CodeStatus(
            installed=True,
            connected=False,
            detail=(out or err).strip()[:400] or "Could not read Claude Code's sign-in status",
        )

    connected = bool(data.get("loggedIn"))
    if not connected:
        return CodeStatus(installed=True, connected=False, detail="Not signed in")
    return CodeStatus(
        installed=True,
        connected=connected,
        detail="Signed in" if connected else "Not signed in",
        account=data.get("email") or data.get("account") or None,
        plan=data.get("subscriptionType") or data.get("authMethod") or None,
    )


def _classify_failure(message: str) -> Exception:
    lowered = message.lower()
    if any(marker in lowered for marker in _LIMIT_MARKERS):
        return UsageLimitReached(
            f"Your Claude plan's usage limit was reached ({message.strip()[:200]}). "
            "Waiting fixes this, reconnecting does not: resume the job once the limit resets."
        )
    if any(marker in lowered for marker in _AUTH_MARKERS):
        return AuthUnavailable(
            f"Claude Code is not signed in ({message.strip()[:200]}). Run "
            "`docker compose exec -it worker claude auth login`, then resume the job."
        )
    return ClaudeCodeError(f"Claude Code failed: {message.strip()[:400]}")


def parse_result(out: str, err: str, returncode: int) -> tuple[dict, Usage]:
    """Turn `claude -p --output-format json` output into (parsed, usage).

    Pulled out of `run_stage` so the parsing is testable without the binary.
    """
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise _classify_failure(err or out or f"exit code {returncode}")

    if data.get("is_error") or data.get("subtype") != "success":
        raise _classify_failure(str(data.get("result") or data.get("subtype") or err))

    parsed = data.get("structured_output")
    if parsed is None:
        # Older builds return the JSON as text in `result`.
        try:
            parsed = json.loads(data.get("result") or "")
        except json.JSONDecodeError as exc:
            raise ClaudeCodeError(f"Claude Code returned no structured output: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ClaudeCodeError("Claude Code returned structured output that is not an object")

    raw = data.get("usage") or {}
    usage = Usage(
        input_tokens=raw.get("input_tokens") or 0,
        output_tokens=raw.get("output_tokens") or 0,
        cache_read_input_tokens=raw.get("cache_read_input_tokens") or 0,
        cache_creation_input_tokens=raw.get("cache_creation_input_tokens") or 0,
    )
    return parsed, usage


async def run_stage(
    *,
    system_text: str,
    user_text: str,
    schema: dict,
    model: str,
    effort: str,
) -> tuple[dict, Usage]:
    if not available():
        raise AuthUnavailable("Claude Code is not installed in the worker container. Rebuild the image.")

    args = [
        "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--system-prompt", system_text,
        "--model", model,
        "--effort", effort,
        # A text-in, JSON-out call: no tools, no MCP, no skills, nothing saved.
        "--tools", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    returncode, out, err = await _exec(args, user_text.encode("utf-8"), timeout=_STAGE_TIMEOUT)
    return parse_result(out, err, returncode)
