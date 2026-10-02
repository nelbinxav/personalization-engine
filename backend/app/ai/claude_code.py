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
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ai.client import AuthUnavailable
from app.db import mongo
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

    A subclass of AuthUnavailable only so callers that do not care about the
    difference still stop instead of failing rows. It is NOT a credential
    problem -- waiting fixes it, reconnecting does not -- and the message says
    so. `resume_at` is when Claude Code said the limit resets, when it said.
    """

    def __init__(self, message: str, resume_at: datetime | None = None) -> None:
        super().__init__(message)
        self.resume_at = resume_at


# "Claude AI usage limit reached|1759000000"
_RESET_EPOCH = re.compile(r"\|(\d{10}|\d{13})\b")
# "resets 3pm", "resets at 3:30pm (America/New_York)", "reset at 15:00 (UTC)"
_RESET_CLOCK = re.compile(
    r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([\w/+-]+)\))?",
    re.IGNORECASE,
)
# A reset further out than this is a misread, not a usage window.
_MAX_RESET_AHEAD = timedelta(days=8)


def parse_reset_time(message: str, now: datetime | None = None) -> datetime | None:
    """Pull the limit's reset time out of Claude Code's message, as UTC.

    The wording has changed between releases, so this recognises the forms seen
    so far and returns None for anything else; the caller then probes on a
    fixed interval instead of trusting a guess.
    """
    now = now or datetime.now(timezone.utc)

    epoch = _RESET_EPOCH.search(message)
    if epoch:
        seconds = int(epoch.group(1))
        if seconds > 10**12:
            seconds //= 1000
        when = datetime.fromtimestamp(seconds, timezone.utc)
        return when if now < when <= now + _MAX_RESET_AHEAD else None

    clock = _RESET_CLOCK.search(message)
    if not clock:
        return None
    hour, minute, meridiem, zone = clock.groups()
    hour, minute = int(hour), int(minute or 0)
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    if hour > 23 or minute > 59:
        return None

    tz = datetime.now().astimezone().tzinfo
    if zone:
        try:
            tz = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            return None
    local_now = now.astimezone(tz)
    when = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= local_now:
        when += timedelta(days=1)
    return when.astimezone(timezone.utc)


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


def _attach_reset(failure: Exception, limits: dict | None) -> None:
    """When the message did not say when the limit resets, the limit event does."""
    if isinstance(failure, UsageLimitReached) and failure.resume_at is None and limits:
        resets = limits.get("resetsAt")
        if resets:
            failure.resume_at = datetime.fromtimestamp(resets, timezone.utc)


def _classify_failure(message: str) -> Exception:
    lowered = message.lower()
    if any(marker in lowered for marker in _LIMIT_MARKERS):
        return UsageLimitReached(
            f"Your Claude plan's usage limit was reached ({message.strip()[:200]}). "
            "Waiting fixes this, reconnecting does not. Jobs resume by themselves once "
            "the limit resets.",
            resume_at=parse_reset_time(message),
        )
    if any(marker in lowered for marker in _AUTH_MARKERS):
        return AuthUnavailable(
            f"Claude Code is not signed in ({message.strip()[:200]}). Run "
            "`docker compose exec -it worker claude auth login`, then resume the job."
        )
    return ClaudeCodeError(f"Claude Code failed: {message.strip()[:400]}")


def split_stream(out: str) -> tuple[dict | None, dict | None]:
    """(final result, plan-limit info) from Claude Code's output.

    With `--output-format stream-json` the output is one JSON event per line:
    the `result` event is what `--output-format json` would have printed, and a
    `rate_limit_event` says how much of the plan's usage windows is spent. A
    single JSON object (the older format) is accepted too.
    """
    try:
        whole = json.loads(out)
        if isinstance(whole, dict):
            return whole, None
    except json.JSONDecodeError:
        pass

    result: dict | None = None
    limits: dict | None = None
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
        elif event.get("type") == "rate_limit_event":
            limits = event.get("rate_limit_info") or limits
    return result, limits


def limits_summary(info: dict) -> dict:
    """The plan-limit event reduced to what the app shows and stores."""
    windows = {}
    for name, window in (info.get("unifiedWindows") or {}).items():
        resets = window.get("resetsAt")
        windows[name] = {
            "utilization": window.get("utilization"),
            "resets_at": datetime.fromtimestamp(resets, timezone.utc) if resets else None,
        }
    resets = info.get("resetsAt")
    return {
        "status": info.get("status"),
        "limit_type": info.get("rateLimitType"),
        "resets_at": datetime.fromtimestamp(resets, timezone.utc) if resets else None,
        "windows": windows,
        "checked_at": datetime.now(timezone.utc),
    }


def parse_result(out: str, err: str, returncode: int) -> tuple[dict, Usage]:
    """Turn `claude -p` output into (parsed, usage).

    Pulled out of `run_stage` so the parsing is testable without the binary.
    """
    data, limits = split_stream(out)
    if data is None:
        failure = _classify_failure(err or out or f"exit code {returncode}")
        _attach_reset(failure, limits)
        raise failure

    if data.get("is_error") or data.get("subtype") != "success":
        failure = _classify_failure(str(data.get("result") or data.get("subtype") or err))
        _attach_reset(failure, limits)
        raise failure

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
        # stream-json rather than json: same result, plus the event that says
        # how much of the plan's usage windows is spent.
        "--output-format", "stream-json",
        "--verbose",
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
    _, limits = split_stream(out)
    if limits:
        await _remember_limits(limits)
    return parse_result(out, err, returncode)


async def _remember_limits(info: dict) -> None:
    """Keep the latest plan-limit reading for the app to show. Never fatal."""
    try:
        await mongo.counters().update_one(
            {"_id": "claude:limits"}, {"$set": limits_summary(info)}, upsert=True
        )
    except Exception:  # noqa: BLE001 - a status display must not fail a row
        logger.debug("Could not store plan limits", exc_info=True)
