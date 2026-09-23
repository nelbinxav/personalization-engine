"""Claude credential resolution and the operator OAuth connect flow.

Two modes, chosen explicitly in Settings -- never inferred:

  oauth    The operator runs a one-time device flow. `ant auth login` stores a
           profile under ANTHROPIC_CONFIG_DIR (a shared docker volume), and the
           SDK picks it up from a bare AsyncAnthropic() and refreshes the
           short-lived token itself.

  api_key  A plain ANTHROPIC_API_KEY.

THE TRAP THIS MODULE EXISTS TO PREVENT: a set ANTHROPIC_API_KEY silently
outranks the OAuth profile in the SDK's credential chain -- even an empty
string wins its slot. Requests would then bill whatever org that key belongs
to, with no error and no visible symptom. `assert_credentials` refuses to
proceed in that state rather than quietly doing the wrong thing.

Caveat worth remembering: Anthropic documents `ant auth login` as a
development-machine flow and points servers at Workload Identity Federation or
an API key. It works here, but refresh tokens do expire, which is why a dead
connection parks jobs in `blocked_auth` instead of burning through rows.
"""
import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import anthropic

from app.core.config import get_settings
from app.core.settings_store import load as load_settings
from app.models.common import new_id, utcnow
from app.models.settings import CredentialMode

logger = logging.getLogger(__name__)

# `ant auth login --no-browser` prints a URL then blocks on stdin for the code.
_URL_PATTERN = re.compile(r"https://\S*(?:claude\.ai|anthropic\.com)\S*")
_FLOW_TIMEOUT = timedelta(minutes=15)


class AuthUnavailable(Exception):
    """No usable Claude credential. Jobs park rather than fail row by row."""


def _apply_config_dir() -> str:
    """Point both the `ant` CLI and the SDK at the shared profile volume."""
    config_dir = get_settings().anthropic_config_dir
    os.environ["ANTHROPIC_CONFIG_DIR"] = config_dir
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def api_key_is_set() -> bool:
    """True if ANTHROPIC_API_KEY exists in the environment at all.

    Deliberately treats "" as set -- an empty key still wins its precedence slot
    and authenticates as an empty key.
    """
    return "ANTHROPIC_API_KEY" in os.environ


async def assert_credentials() -> None:
    """Fail loudly at startup rather than subtly at row 200."""
    settings = await load_settings()

    if settings.ai.mode is CredentialMode.oauth:
        if api_key_is_set():
            raise AuthUnavailable(
                "Credential mode is OAuth but ANTHROPIC_API_KEY is set in the environment. "
                "The SDK would use the key and silently bill the wrong org. Unset it "
                "(remove it from .env and docker-compose) or switch Settings to API key mode."
            )
        status = await auth_status()
        if not status.connected:
            raise AuthUnavailable(
                f"Claude is not connected: {status.detail}. Connect it in Settings."
            )
        return

    if not await resolve_api_key():
        raise AuthUnavailable(
            "Credential mode is API key but no key is configured. Add one in Settings."
        )


async def resolve_api_key() -> str | None:
    """The stored key wins; the env var is a bootstrap fallback."""
    from app.core.settings_store import provider_key

    return await provider_key("anthropic") or os.environ.get("ANTHROPIC_API_KEY")


async def get_client() -> anthropic.AsyncAnthropic:
    settings = await load_settings()

    if settings.ai.mode is CredentialMode.oauth:
        _apply_config_dir()
        if api_key_is_set():
            raise AuthUnavailable(
                "ANTHROPIC_API_KEY is set while in OAuth mode; refusing to run so the "
                "wrong org is not billed."
            )
        os.environ["ANTHROPIC_PROFILE"] = get_settings().anthropic_oauth_profile
        # Bare constructor: the SDK resolves the profile from ANTHROPIC_CONFIG_DIR
        # and handles token refresh. No manual token plumbing.
        return anthropic.AsyncAnthropic(max_retries=3)

    key = await resolve_api_key()
    if not key:
        raise AuthUnavailable("No Anthropic API key configured. Add one in Settings.")
    return anthropic.AsyncAnthropic(api_key=key, max_retries=3)


# --------------------------------------------------------------------------
# `ant` CLI wrappers
# --------------------------------------------------------------------------


@dataclass
class AuthStatus:
    connected: bool
    mode: str = "oauth"
    detail: str = ""
    organization: str | None = None
    workspace: str | None = None
    raw: str = ""


def ant_available() -> bool:
    return shutil.which("ant") is not None


async def _run_ant(*args: str, timeout: float = 30) -> tuple[int, str]:
    _apply_config_dir()
    process = await asyncio.create_subprocess_exec(
        "ant",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=os.environ.copy(),
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        raise AuthUnavailable(f"`ant {' '.join(args)}` timed out after {timeout}s")
    return process.returncode or 0, stdout.decode("utf-8", errors="replace")


async def auth_status() -> AuthStatus:
    settings = await load_settings()

    if settings.ai.mode is CredentialMode.api_key:
        has_key = bool(await resolve_api_key())
        return AuthStatus(
            connected=has_key,
            mode="api_key",
            detail="API key configured" if has_key else "No API key configured",
        )

    if not ant_available():
        return AuthStatus(
            connected=False,
            detail="The `ant` CLI is not installed in this container, so OAuth is unavailable. "
            "Rebuild the image or switch to API key mode.",
        )

    try:
        code, output = await _run_ant("auth", "status")
    except AuthUnavailable as exc:
        return AuthStatus(connected=False, detail=str(exc))

    if code != 0:
        return AuthStatus(connected=False, detail=output.strip()[:400] or "Not signed in", raw=output)

    # Parse loosely -- the CLI's exact output format is not a stable contract.
    lowered = output.lower()
    connected = "not signed in" not in lowered and "no active" not in lowered

    def field_value(*names: str) -> str | None:
        for name in names:
            match = re.search(rf"{name}[^\S\n]*[:=][^\S\n]*(\S.*)", output, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    if api_key_is_set():
        return AuthStatus(
            connected=False,
            detail="ANTHROPIC_API_KEY is set and overrides the OAuth profile. Unset it.",
            raw=output,
        )

    return AuthStatus(
        connected=connected,
        detail="Connected" if connected else "Not signed in",
        organization=field_value("organization", "org"),
        workspace=field_value("workspace"),
        raw=output.strip()[:2000],
    )


# --------------------------------------------------------------------------
# Device flow. `ant auth login --no-browser` prints an authorize URL and then
# waits on stdin, so the process must stay alive between two HTTP requests.
# This keeps it in memory -- which means the API must run with a single worker.
# --------------------------------------------------------------------------


@dataclass
class _Flow:
    process: asyncio.subprocess.Process
    url: str
    started_at: datetime = field(default_factory=utcnow)


_flows: dict[str, _Flow] = {}


def _reap_expired() -> None:
    for flow_id, flow in list(_flows.items()):
        if utcnow() - flow.started_at > _FLOW_TIMEOUT:
            try:
                flow.process.kill()
            except ProcessLookupError:
                pass
            _flows.pop(flow_id, None)


async def oauth_start() -> dict:
    if not ant_available():
        raise AuthUnavailable(
            "The `ant` CLI is not installed in this container. Rebuild the image with it, "
            "or use API key mode."
        )
    if api_key_is_set():
        raise AuthUnavailable(
            "ANTHROPIC_API_KEY is set in the environment. Connecting via OAuth would have no "
            "effect because the key takes precedence. Unset it first."
        )

    _reap_expired()
    _apply_config_dir()
    profile = get_settings().anthropic_oauth_profile

    process = await asyncio.create_subprocess_exec(
        "ant",
        "auth",
        "login",
        "--no-browser",
        "--profile",
        profile,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=os.environ.copy(),
    )

    # Read until the authorize URL appears; the process then blocks on stdin.
    url = ""
    buffered: list[str] = []
    try:
        async with asyncio.timeout(45):
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                buffered.append(text)
                match = _URL_PATTERN.search(text)
                if match:
                    url = match.group(0).rstrip(".,)")
                    break
    except asyncio.TimeoutError:
        process.kill()
        raise AuthUnavailable(
            "Timed out waiting for the authorize URL from `ant auth login`. Output so far:\n"
            + "".join(buffered)[-500:]
        )

    if not url:
        process.kill()
        raise AuthUnavailable(
            "`ant auth login` did not print an authorize URL. Output:\n"
            + "".join(buffered)[-500:]
        )

    flow_id = new_id()
    _flows[flow_id] = _Flow(process=process, url=url)
    logger.info("Started Claude OAuth flow %s", flow_id)
    return {"flow_id": flow_id, "authorize_url": url, "profile": profile}


async def oauth_complete(flow_id: str, code: str) -> AuthStatus:
    _reap_expired()
    flow = _flows.pop(flow_id, None)
    if not flow:
        raise AuthUnavailable(
            "That connection attempt expired or was already used. Start a new one."
        )

    process = flow.process
    try:
        process.stdin.write((code.strip() + "\n").encode())
        await process.stdin.drain()
        process.stdin.close()
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise AuthUnavailable(f"The login process exited before the code was sent: {exc}") from exc

    try:
        stdout = await asyncio.wait_for(process.stdout.read(), timeout=60)
        await process.wait()
    except asyncio.TimeoutError:
        process.kill()
        raise AuthUnavailable("Timed out completing the login.")

    output = stdout.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise AuthUnavailable(f"Login failed: {output.strip()[:400]}")

    status = await auth_status()
    if not status.connected:
        raise AuthUnavailable(
            f"Login reported success but the profile is not active: {status.detail}"
        )
    logger.info("Claude OAuth connected (org=%s workspace=%s)", status.organization, status.workspace)
    return status


async def oauth_disconnect() -> None:
    if ant_available():
        await _run_ant("auth", "logout", "--profile", get_settings().anthropic_oauth_profile)
