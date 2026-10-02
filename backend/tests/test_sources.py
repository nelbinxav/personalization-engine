"""Source logic that does not need the network: the LinkedIn recent-post
filter, MCP reply parsing and what each source will fetch."""
from datetime import datetime, timezone

import httpx
import pytest

from app.models.common import Identity
from app.sources import registry
from app.sources.base import SourceError
from app.sources.exa import PodcastSource
from app.sources.linkedin_account import read_gap, recent_posts, render_posts, split_posts
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
