"""LinkedIn through a signed-in LinkedIn account: the `account` provider.

This is the route Agent Reach uses. A separate container runs
stickerdaniel/linkedin-mcp-server, which drives a real browser signed in to one
LinkedIn account and exposes it as MCP tools. It is the only provider here that
can read what LinkedIn gates behind a login, above all a person's recent posts.

What that costs:

  * LinkedIn's User Agreement prohibits automated access, and an account used
    this way can be restricted. So this module is deliberately slow: one read
    at a time, spread over the day at an hourly rate with a randomised gap
    between reads, and a daily cap. Do not remove
    the pacing to make a job faster; the account is what it protects.
  * Someone signs in once, in the service's own login browser. This app never
    sees the password or the session.

The service returns each page as raw text (it does not parse LinkedIn's
markup), so the post-age filter below reads LinkedIn's own "3d", "1w" markers.
"""
import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.db import mongo
from app.sources.base import SourceConfig, SourceDailyLimit, SourceError, SourceRateLimited
from app.sources.mcp_http import ToolFailed, call_tool, tool_text

logger = logging.getLogger(__name__)

# Opening a profile and scrolling its activity page takes a while.
TOOL_TIMEOUT = 240
# Never closer together than this, whatever the hourly rate is set to.
MIN_GAP = 8.0


def read_gap(reads_per_hour: int) -> tuple[float, float]:
    """(shortest, longest) wait between two LinkedIn reads for an hourly rate.

    The gap is randomised around the even spacing, by 40% either way, so the
    rhythm is not mechanical. 20 an hour gives 108 to 252 seconds.
    """
    even = 3600 / max(reads_per_hour, 1)
    return max(MIN_GAP, even * 0.6), max(MIN_GAP, even * 1.4)
MAX_POSTS = 5
MAX_POST_CHARS = 1500

LOGIN_HELP = "Connect it under Settings, Research, LinkedIn account."

_gate = asyncio.Lock()
_last_read = 0.0
_inflight: dict[tuple[str, str], asyncio.Future] = {}


async def _spend_daily_budget(limit: int) -> None:
    """Count one read against today's cap, atomically. Raises when it is spent."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        await mongo.counters().find_one_and_update(
            {"_id": f"linkedin:{day}", "n": {"$lt": limit}},
            {
                "$inc": {"n": 1},
                "$setOnInsert": {"expires_at": datetime.now(timezone.utc) + timedelta(days=3)},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        # Today's counter exists and is at the limit, so the upsert collided.
        raise SourceDailyLimit(
            f"Today's LinkedIn limit of {limit} reads is used up. The job waits and carries on "
            "tomorrow; the limit protects the LinkedIn account and can be changed in Settings."
        ) from None


async def _refund_daily_budget() -> None:
    """Give a read back when no LinkedIn page was actually loaded."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await mongo.counters().update_one(
        {"_id": f"linkedin:{day}", "n": {"$gt": 0}}, {"$inc": {"n": -1}}
    )


class _NotSignedIn(SourceError):
    pass


async def _remember(signed_in: bool) -> None:
    """Record what the last read showed, for the Settings page."""
    await mongo.counters().update_one(
        {"_id": "linkedin:state"},
        {"$set": {"signed_in": signed_in, "checked_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


def _classify(message: str) -> SourceError:
    lowered = message.lower()
    if "rate limit" in lowered or "rate-limit" in lowered or "too many" in lowered:
        return SourceRateLimited(f"LinkedIn is rate-limiting the account: {message[:200]}")
    if any(word in lowered for word in ("session", "login", "log in", "sign in", "authenticat")):
        return _NotSignedIn(f"The LinkedIn account is not signed in. {LOGIN_HELP}")
    return SourceError(f"LinkedIn read failed: {message[:300]}")


async def _read(client: httpx.AsyncClient, cfg: SourceConfig, tool: str, arguments: dict) -> dict:
    global _last_read
    async with _gate:
        await _spend_daily_budget(cfg.linkedin_daily_limit)
        loop = asyncio.get_running_loop()
        wait = _last_read + random.uniform(*read_gap(cfg.linkedin_reads_per_hour)) - loop.time()
        if _last_read and wait > 0:
            await asyncio.sleep(wait)
        try:
            result = await call_tool(
                client, cfg.linkedin_mcp_url, tool, arguments, timeout=TOOL_TIMEOUT
            )
        except ToolFailed as exc:
            problem = _classify(str(exc))
            if isinstance(problem, _NotSignedIn):
                await _refund_daily_budget()
                await _remember(False)
            raise problem from exc
        except SourceRateLimited:
            raise
        except SourceError as exc:
            if "Could not reach" in str(exc):
                await _refund_daily_budget()
                raise SourceError(
                    "The LinkedIn service is not running. Start it with: "
                    "docker compose --profile linkedin up -d"
                ) from exc
            raise
        finally:
            _last_read = loop.time()

    await _remember(True)
    data = result.get("structuredContent")
    if not isinstance(data, dict):
        try:
            data = json.loads(tool_text(result))
        except ValueError as exc:
            raise SourceError("LinkedIn service returned an unreadable result") from exc
    if not isinstance(data, dict):
        raise SourceError("LinkedIn service returned an unexpected result")
    return data


async def _shared(key: tuple[str, str], make) -> dict:
    """One read per page even when two sources ask for it at the same moment
    (a person's profile and their posts come from the same call)."""
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(make())
        _inflight[key] = task
        task.add_done_callback(lambda _: _inflight.pop(key, None))
    return await asyncio.shield(task)


async def person(client: httpx.AsyncClient, cfg: SourceConfig, url: str) -> dict:
    return await _shared(
        ("person", url),
        lambda: _read(
            client, cfg, "get_person_profile", {"linkedin_username": url, "sections": "posts"}
        ),
    )


async def company(client: httpx.AsyncClient, cfg: SourceConfig, url: str) -> dict:
    return await _shared(
        ("company", url),
        lambda: _read(
            client, cfg, "get_company_profile", {"company_name": url, "sections": "posts"}
        ),
    )


def sections_of(data: dict) -> dict[str, str]:
    sections = data.get("sections")
    return {k: v for k, v in sections.items() if isinstance(v, str)} if isinstance(sections, dict) else {}


def section_error(data: dict, name: str) -> str | None:
    errors = data.get("section_errors")
    if isinstance(errors, dict) and name in errors:
        return json.dumps(errors[name])[:200]
    return None


# --------------------------------------------------------------------------
# Recent posts
# --------------------------------------------------------------------------

# LinkedIn stamps a post "5h", "3d", "1w", "2mo" or "1yr", next to a bullet.
_AGE = re.compile(r"(?<![\w.])(\d{1,3})\s?(mo|yr|h|d|w|m)\b(?=\s*[•·])|[•·]\s*(\d{1,3})\s?(mo|yr|h|d|w|m)\b")
_POST_START = re.compile(r"^Feed post number \d+\s*$", re.MULTILINE)
_UNIT_DAYS = {"m": 0.0, "h": 1 / 24, "d": 1.0, "w": 7.0, "mo": 30.0, "yr": 365.0}


@dataclass
class Post:
    age: str
    days: float
    text: str


def split_posts(raw: str) -> list[Post]:
    """Cut an activity page's text into posts, each with LinkedIn's age stamp.

    Blocks are taken from LinkedIn's "Feed post number N" lines when present,
    otherwise from one age stamp to the next. A block with no stamp is dropped:
    without an age it cannot be called recent.
    """
    starts = [m.start() for m in _POST_START.finditer(raw)]
    if starts:
        blocks = [raw[a:b] for a, b in zip(starts, starts[1:] + [len(raw)])]
    else:
        stamps = [m.start() for m in _AGE.finditer(raw)]
        # Back each block up to the start of its line so the author stays with it.
        stamps = [raw.rfind("\n", 0, s) + 1 for s in stamps]
        blocks = [raw[a:b] for a, b in zip(stamps, stamps[1:] + [len(raw)])]

    posts: list[Post] = []
    for block in blocks:
        match = _AGE.search(block)
        if not match:
            continue
        number, unit = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        text = _POST_START.sub("", block).strip()
        if text:
            posts.append(Post(age=f"{number}{unit}", days=int(number) * _UNIT_DAYS[unit], text=text))
    return posts


def recent_posts(raw: str, window_days: int) -> tuple[list[Post], int]:
    """(posts inside the window, how many posts were found at all).

    LinkedIn rounds to whole weeks after six days, so "1w" covers 7 to 13 days
    and is kept; "2w" and older are out.
    """
    posts = split_posts(raw)
    return [p for p in posts if p.days <= max(window_days, 7)][:MAX_POSTS], len(posts)


def render_posts(posts: list[Post], owner: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"Recent posts from {owner}'s LinkedIn activity, newest first. An entry that says "
        "someone \"reposted this\" is another person's post they shared, not their own words."
    ]
    for post in posts:
        when = (now - timedelta(days=post.days)).strftime("%d %B %Y")
        approx = "between 7 and 13 days ago" if post.age.endswith("w") else f"about {when}"
        text = post.text if len(post.text) <= MAX_POST_CHARS else post.text[:MAX_POST_CHARS] + " [...]"
        lines.append(f"--- Post, LinkedIn age stamp {post.age} ({approx}) ---\n{text}")
    return "\n\n".join(lines)



# --------------------------------------------------------------------------
# Connecting an account from Settings
# --------------------------------------------------------------------------


def _control_dir() -> Path:
    return Path(get_settings().linkedin_control_dir)


def request_login() -> None:
    """Ask the linkedin service to open its sign-in browser (see
    deploy/linkedin-run.sh). The link it publishes is read by `status`."""
    control = _control_dir()
    if not control.is_dir():
        raise SourceError(
            "The LinkedIn service is not set up on this installation. Start it with: "
            "docker compose --profile linkedin up -d"
        )
    # The service runs as an unprivileged user and has to write its answer here.
    control.chmod(0o777)
    for name in ("login-url", "login-state"):
        (control / name).unlink(missing_ok=True)
    (control / "login-requested").write_text("1")


def _read_control(name: str) -> str | None:
    try:
        return (_control_dir() / name).read_text().strip() or None
    except OSError:
        return None


async def status(client: httpx.AsyncClient, cfg: SourceConfig) -> dict:
    """What Settings shows: is the service up, is an account connected, and how
    much of today's allowance is used. Makes no LinkedIn page read."""
    try:
        response = await client.post(
            cfg.linkedin_mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "personalization-engine", "version": "1"},
                },
            },
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            timeout=5,
        )
        running = response.status_code < 400
    except httpx.HTTPError:
        running = False

    login_state = _read_control("login-state")
    pending = (_control_dir() / "login-requested").exists()
    state = await mongo.counters().find_one({"_id": "linkedin:state"}) or {}
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used = (await mongo.counters().find_one({"_id": f"linkedin:{day}"}) or {}).get("n", 0)

    return {
        "available": _control_dir().is_dir(),
        "service_running": running,
        "login_state": "starting" if pending else login_state,
        # Our own viewer page: the image's cannot paste into the sign-in browser.
        "login_url": (_read_control("login-url") or "").replace("/vnc_lite.html", "/pe.html") or None,
        "signed_in": state.get("signed_in"),
        "checked_at": state.get("checked_at"),
        "reads_today": used,
        "daily_limit": cfg.linkedin_daily_limit,
    }


async def test_connection(client: httpx.AsyncClient, cfg: SourceConfig) -> str:
    """One real read of the connected account's own profile. Returns who it is."""
    data = await _read(client, cfg, "get_my_profile", {})
    text = next(iter(sections_of(data).values()), "")
    return next((line.strip() for line in text.splitlines() if line.strip()), "Connected")
