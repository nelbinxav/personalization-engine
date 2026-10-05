"""Source logic that does not need the network: the LinkedIn recent-post
filter, MCP reply parsing and what each source will fetch."""
from datetime import datetime, timezone

import httpx
import pytest

from app.models.common import Identity
from app.sources import registry
from app.sources.base import SourceError
from app.sources.exa import PodcastSource, matching_results
from app.sources.linkedin_account import has_no_activity, read_gap, recent_posts, render_posts, split_posts
from app.sources.mcp_http import _read_reply, tool_text

# The two layouts LinkedIn's activity page has had: numbered posts, and plain
# blocks where only the age stamp marks a new post.
NUMBERED = """Feed post number 1
Ada Lovelace
• 2nd
VP Data at Analytical
3d • Edited •
Back from Big Data London. Three talks on lakehouse cost stood out.
Like
Comment

Feed post number 2
Ada Lovelace reposted this
Grace Hopper
• 3rd+
1w •
We are hiring data engineers.

Feed post number 3
Ada Lovelace
2mo •
Old thoughts on Spark tuning.
"""

PLAIN = """Ada Lovelace posted this • 5h
Shipping our new pipeline today.
Ada Lovelace posted this • 2w
Something from a fortnight ago.
Ada Lovelace posted this • 1yr
Ancient history.
"""


def test_numbered_posts_are_split_and_aged():
    posts = split_posts(NUMBERED)
    assert [p.age for p in posts] == ["3d", "1w", "2mo"]
    assert "Big Data London" in posts[0].text
    assert "Feed post number" not in posts[0].text
    # "2nd" and "3rd+" are connection degrees, not ages.
    assert posts[1].days == 7


def test_only_posts_inside_the_window_are_kept():
    recent, found = recent_posts(NUMBERED, 10)
    assert found == 3
    # 1w covers 7 to 13 days, so it stays; two months does not.
    assert [p.age for p in recent] == ["3d", "1w"]

    recent, found = recent_posts(PLAIN, 10)
    assert found == 3 and [p.age for p in recent] == ["5h"]


def test_text_without_age_stamps_yields_no_posts():
    assert recent_posts("Ada has not posted lately.", 10) == ([], 0)


def test_rendered_posts_carry_an_approximate_date():
    recent, _ = recent_posts(NUMBERED, 10)
    text = render_posts(recent, "Ada Lovelace", now=datetime(2026, 10, 2, tzinfo=timezone.utc))
    assert "about 29 September 2026" in text
    assert "between 7 and 13 days ago" in text
    assert "reposted this" in text  # the warning and the repost itself


def _response(body: str, content_type: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=body,
        headers={"content-type": content_type},
        request=httpx.Request("POST", "https://mcp.example/mcp"),
    )


def test_reply_is_read_from_json_or_an_event_stream():
    assert _read_reply(_response('{"id": 1, "result": {"ok": true}}', "application/json"), 1)["result"]
    stream = (
        'event: message\ndata: {"method": "notifications/progress", "params": {}}\n\n'
        'event: message\ndata: {"id": 1, "result": {"content": [{"type": "text", "text": "hi"}]}}\n\n'
    )
    reply = _read_reply(_response(stream, "text/event-stream"), 1)
    assert tool_text(reply["result"]) == "hi"


def test_a_stream_without_the_answer_is_an_error():
    with pytest.raises(SourceError):
        _read_reply(_response('data: {"method": "x"}\n\n', "text/event-stream"), 1)


def test_podcast_search_needs_a_full_name_and_a_company():
    source = PodcastSource()
    assert source.target(Identity(full_name="Ada Lovelace", company="Analytical")) == (
        "Ada Lovelace | Analytical"
    )
    assert source.target(Identity(first_name="Ada", last_name="Lovelace", company="Analytical"))
    # A first name alone, or no company, would match the wrong people.
    assert source.target(Identity(first_name="Ada", company="Analytical")) is None
    assert source.target(Identity(full_name="Ada Lovelace")) is None


def test_sources_are_registered_in_priority_order():
    assert list(registry.ALL_SOURCES) == [
        "linkedin_posts",
        "podcasts",
        "linkedin_profile",
        "linkedin_company",
        "news",
        "website",
        "rss",
    ]


def test_linkedin_reads_are_spread_at_the_hourly_rate():
    shortest, longest = read_gap(20)
    # 20 an hour is one every 180 seconds, give or take 40%.
    assert (round(shortest), round(longest)) == (108, 252)
    # However high the rate is set, reads never come closer than a few seconds.
    assert read_gap(100_000) == (8.0, 8.0)
    assert read_gap(0)[0] > 0


# What a person's activity page really looks like (from the first live run):
# "Feed post" with no number, and the age on a line of its own.
LIVE_ACTIVITY = """Ada Lovelace
VP Data at Analytical
Followers
2,152
Message
Follow
All activity
Posts
Feed post
Ada Lovelace reposted this
Grace Hopper
 • 3rd+
Senior Software Engineer at Nebius
2yr
Follow
Exploring new job opportunities.
… more
15
1
Feed post
Ada Lovelace
 • 2nd
VP Data at Analytical
4d
Three talks on lakehouse cost stood out at Big Data London.
… more
40
Load more
People you may know
Charles Babbage
· 3rd
5d of travel ahead
Connect
"""


def test_live_activity_page_format_is_parsed():
    posts = split_posts(LIVE_ACTIVITY)
    assert [p.age for p in posts] == ["2yr", "4d"]
    recent, found = recent_posts(LIVE_ACTIVITY, 10)
    assert found == 2 and [p.age for p in recent] == ["4d"]
    text = recent[0].text
    assert "Big Data London" in text
    # Buttons, counters and LinkedIn's suggestions below the feed are not post text.
    assert "… more" not in text and "\n40" not in text and "Babbage" not in text


def test_a_profile_with_no_posts_is_recognised():
    empty = "Ada Lovelace\nVP Data\nFollowers\n282\nAll activity\nReactions\nNothing to see for now\nPeople you may know\nSomeone\n· 3rd\n"
    assert has_no_activity(empty)
    assert not has_no_activity(LIVE_ACTIVITY)


# --- The research funnel -------------------------------------------------


class _Fake:
    """A source that returns a canned outcome and records that it was asked."""

    def __init__(self, key: str, ok: bool, calls: list[str], delay: float = 0.0):
        self.key, self.label, self._ok, self._calls, self._delay = key, key, ok, calls, delay

    def target(self, identity):
        return f"{self.key}:{identity.full_name}"

    async def fetch(self, identity, cfg, client):
        import asyncio as aio

        self._calls.append(self.key)
        await aio.sleep(self._delay)
        from app.models.prospect import SourceResult

        return SourceResult(key=self.key, ok=self._ok, content="found" if self._ok else None,
                            error=None if self._ok else "nothing")


def _funnel(monkeypatch, outcomes: dict[str, bool], keys: list[str] | None = None, delays: dict | None = None):
    import asyncio as aio

    from app.sources.base import SourceConfig

    calls: list[str] = []
    order = ["linkedin_posts", "podcasts", "linkedin_profile", "linkedin_company", "news", "website", "rss"]
    fakes = {k: _Fake(k, outcomes.get(k, False), calls, (delays or {}).get(k, 0.0)) for k in order}
    monkeypatch.setattr(registry, "ALL_SOURCES", fakes)

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(registry, "_cache_put", no_cache)
    results, pending = aio.run(
        registry.run_funnel(Identity(full_name="Ada"), keys or order, SourceConfig(), use_cache=False)
    )
    _funnel.pending = pending
    return results, calls


def test_a_recent_post_ends_the_research(monkeypatch):
    results, calls = _funnel(monkeypatch, {"linkedin_posts": True, "linkedin_profile": True, "podcasts": True, "website": True})
    # The profile comes from the same read, so it is kept; nothing below is.
    assert set(results) == {"linkedin_posts", "linkedin_profile"}
    assert not {"news", "website", "rss", "linkedin_company"} & set(calls)


def test_no_post_but_a_podcast_ends_it_there(monkeypatch):
    results, calls = _funnel(monkeypatch, {"linkedin_profile": True, "podcasts": True, "website": True})
    assert results["podcasts"].ok and not results["linkedin_posts"].ok
    assert not {"news", "website", "rss", "linkedin_company"} & set(calls)


def test_neither_goes_on_to_news_and_website_and_skips_the_company_page(monkeypatch):
    results, calls = _funnel(monkeypatch, {"linkedin_profile": True, "website": True})
    assert results["website"].ok and {"news", "website", "rss"} <= set(calls)
    assert "linkedin_company" not in calls


def test_the_company_page_is_the_last_resort(monkeypatch):
    results, calls = _funnel(monkeypatch, {"linkedin_company": True})
    assert calls[-1] == "linkedin_company" and results["linkedin_company"].ok


def test_only_ticked_sources_are_used(monkeypatch):
    results, calls = _funnel(monkeypatch, {"linkedin_posts": True, "podcasts": False, "website": True},
                             keys=["podcasts", "news", "website"])
    assert "linkedin_posts" not in calls and results["website"].ok


def test_the_podcast_search_runs_while_waiting_for_linkedin(monkeypatch):
    # LinkedIn is slow; the podcast search must already have been asked for.
    _, calls = _funnel(monkeypatch, {"podcasts": True}, delays={"linkedin_posts": 0.05, "linkedin_profile": 0.05})
    assert "podcasts" in calls[:3]


def test_a_podcast_result_must_name_the_person_and_the_company():
    results = (
        "Title: Data cost with Ada Lovelace\nHighlights: Ada Lovelace, VP Data at Analytical Inc., on lakehouse spend.\n"
        "\n---\n\n"
        "Title: Cooking with Ada Lovelace\nHighlights: Chef Ada Lovelace of Bistro Nine shares recipes.\n"
        "\n---\n\n"
        "Title: Analytical quarterly update\nHighlights: Analytical announces a new office.\n"
    )
    # Naming both is not enough: it has to be an appearance, not a profile page.
    assert matching_results(results, "Ada Lovelace", "Analytical, Inc.") == []
    results = results.replace("Title: Data cost with Ada Lovelace", "Title: Data Cost Podcast, episode 12, with Ada Lovelace")
    results += (
        "\n---\n\nTitle: Ada Lovelace - VP Data\nURL: https://www.linkedin.com/in/ada\n"
        "Highlights: Ada Lovelace at Analytical. Recently on a podcast.\n"
    )
    kept = matching_results(results, "Ada Lovelace", "Analytical, Inc.")
    assert len(kept) == 1 and "lakehouse spend" in kept[0]
    # A namesake alone, or the company alone, is not a find.
    assert matching_results(results, "Ada Lovelace", "Clarity") == []
    assert matching_results(results, "Grace Hopper", "Analytical") == []


class _BusyLinkedIn(_Fake):
    async def fetch(self, identity, cfg, client):
        from app.sources.base import SourceBusy

        self._calls.append(self.key)
        # The funnel must have asked not to wait.
        assert cfg.linkedin_wait is False
        raise SourceBusy("not now")


def test_research_does_not_wait_for_linkedin(monkeypatch):
    import asyncio as aio

    from app.sources.base import SourceConfig

    calls: list[str] = []
    fakes = {
        "linkedin_posts": _BusyLinkedIn("linkedin_posts", False, calls),
        "podcasts": _Fake("podcasts", False, calls),
        "linkedin_profile": _BusyLinkedIn("linkedin_profile", False, calls),
        "linkedin_company": _BusyLinkedIn("linkedin_company", False, calls),
        "news": _Fake("news", False, calls),
        "website": _Fake("website", True, calls),
        "rss": _Fake("rss", False, calls),
    }
    monkeypatch.setattr(registry, "ALL_SOURCES", fakes)

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(registry, "_cache_put", no_cache)
    results, pending = aio.run(
        registry.run_funnel(Identity(full_name="Ada"), list(fakes), SourceConfig(), use_cache=False)
    )
    # LinkedIn was busy: the lead is researched from the website now, and its
    # LinkedIn sources are handed to the background check instead of stored as failures.
    assert results["website"].ok
    assert pending == ["linkedin_posts", "linkedin_profile"]
    assert "linkedin_posts" not in results and "linkedin_profile" not in results
