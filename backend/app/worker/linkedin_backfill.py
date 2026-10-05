"""The background check for sources research did not wait for.

Research never waits (see `registry.run_funnel`): a lead whose LinkedIn turn
has not come, or whose web search hit the free daily allowance, is researched
from its other sources straight away and flagged `linkedin_pending` with the
sources still owed. This loop works through those leads one at a time, as each
source becomes available, and adds what it finds to the row. Nothing is paused while
it does: jobs finish, messages can be written, and a recent post that turns up
later sends just that lead back for a new message.
"""
import asyncio
import logging
import time
from datetime import timedelta

import httpx

from app.core import settings_store
from app.db import mongo
from app.models.common import Identity, RowStatus, utcnow
from app.sources import exa, registry

logger = logging.getLogger(__name__)

IDLE_SECONDS = 20
# When LinkedIn cannot be used at all for a while: today's cap is spent, the
# account is signed out, the service is down, or LinkedIn asked us to slow down.
BLOCKED_SECONDS = 10 * 60
NEW_HOOK_NOTE = (
    "A recent LinkedIn post or a podcast was found after this message was written. "
    "Personalize again to use it."
)
_WRITTEN = [RowStatus.done.value, RowStatus.thin_context.value, RowStatus.needs_review.value]
_UNAVAILABLE = ("not signed in", "not running", "rate-limiting")


# Until when LinkedIn is known to be unusable (today's cap spent, signed out,
# service down). While it is, leads owed only other sources are still served.
_linkedin_closed_until = 0.0


def _note_linkedin(fetched: list) -> None:
    global _linkedin_closed_until
    for result in fetched:
        if result is None or result.key not in _LINKEDIN_KEYS or not not_yet(result):
            continue
        if result.meta.get("daily_limit"):
            tomorrow = (utcnow() + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
            _linkedin_closed_until = tomorrow.timestamp()
        else:
            _linkedin_closed_until = time.time() + BLOCKED_SECONDS
        return


_LINKEDIN_KEYS = {"linkedin_posts", "linkedin_profile", "linkedin_company"}
_SEARCH_KEYS = {"podcasts", "news"}
# A hook that arrives after the message was written sends the lead back.
_HOOKS = ("linkedin_posts", "podcasts")


def not_yet(result) -> bool:
    """True when the fetch did not happen for a reason that will pass: keep the
    source pending rather than store "LinkedIn is not signed in" as research."""
    if result.ok:
        return False
    if registry.for_later(result):
        return True
    return any(marker in (result.error or "") for marker in _UNAVAILABLE)


async def check_next() -> str:
    """Fetch what the lead that has waited longest is still missing.
    Returns "idle", "blocked" or "done"."""
    settings = await settings_store.load()
    closed: set[str] = set()
    if settings.linkedin_provider != "account" or time.time() < _linkedin_closed_until:
        closed |= _LINKEDIN_KEYS
    if exa.blocked() and not await settings_store.provider_key("exa"):
        closed |= _SEARCH_KEYS

    doc = await mongo.prospects().find_one(
        {"linkedin_pending": True, "linkedin_pending_keys": {"$elemMatch": {"$nin": sorted(closed)}}},
        sort=[("linkedin_pending_at", 1), ("row_index", 1)],
    )
    if not doc:
        return "idle"

    waiting: list[str] = doc.get("linkedin_pending_keys") or []
    keys = [key for key in waiting if key not in closed]
    identity = Identity.model_validate(doc.get("identity") or {})
    cfg = await registry.build_config(settings)  # linkedin_wait stays True: this is the waiter

    async with httpx.AsyncClient(follow_redirects=True, timeout=cfg.timeout) as client:
        fetched = await asyncio.gather(
            *(registry.run_one(key, identity, cfg, client, use_cache=True) for key in keys)
        )
    _note_linkedin(fetched)
    answered = {r.key: r for r in fetched if r is not None and not not_yet(r)}
    # A source with nothing to fetch for this lead returns None: that is an answer too.
    settled = set(answered) | {key for key, r in zip(keys, fetched) if r is None}
    if not settled:
        return "blocked"

    remaining = [key for key in waiting if key not in settled]
    update: dict = {
        "linkedin_pending": bool(remaining),
        "linkedin_pending_keys": remaining,
        "linkedin_checked_at": utcnow(),
    }
    for key, result in answered.items():
        update[f"research.{key}"] = result.model_dump(mode="json")

    found_hook = any(key in answered and answered[key].ok for key in _HOOKS)
    if found_hook and doc.get("personalize_status") in _WRITTEN:
        # A better opener arrived late. Hand the lead back so the next
        # personalize run writes it again; the old message stays until then.
        update["personalize_status"] = RowStatus.pending.value
        update["personalize_error"] = NEW_HOOK_NOTE

    await mongo.prospects().update_one({"_id": doc["_id"]}, {"$set": update})
    return "done"


async def run_forever() -> None:
    while True:
        try:
            outcome = await check_next()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must outlive any one lead
            logger.exception("LinkedIn background check failed")
            outcome = "blocked"
        if outcome == "done":
            continue  # the pacing inside the read spaces the next one
        await asyncio.sleep(IDLE_SECONDS)
