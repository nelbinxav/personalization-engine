import json
from datetime import datetime, timezone

import pytest

from app.ai.claude_code import (
    ClaudeCodeError,
    UsageLimitReached,
    limits_summary,
    parse_reset_time,
    parse_result,
    split_stream,
)
from app.ai.client import AuthUnavailable


def _result(**overrides) -> str:
    data = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "",
        "structured_output": {"summary": "ok", "facts": []},
        "usage": {
            "input_tokens": 120,
            "output_tokens": 40,
            "cache_read_input_tokens": 1000,
            "cache_creation_input_tokens": 0,
        },
    }
    data.update(overrides)
    return json.dumps(data)


def test_structured_output_and_usage():
    parsed, usage = parse_result(_result(), "", 0)
    assert parsed == {"summary": "ok", "facts": []}
    assert usage.input_tokens == 120
    assert usage.output_tokens == 40
    assert usage.cache_read_input_tokens == 1000


def test_falls_back_to_json_in_result_text():
    parsed, _ = parse_result(_result(structured_output=None, result='{"a": 1}'), "", 0)
    assert parsed == {"a": 1}


def test_not_logged_in_is_an_auth_problem():
    out = _result(is_error=True, subtype="success", result="Not logged in · Please run /login")
    with pytest.raises(AuthUnavailable) as info:
        parse_result(out, "", 1)
    assert not isinstance(info.value, UsageLimitReached)


def test_usage_limit_is_not_an_auth_problem():
    # 401 is not 429: a plan limit must say "wait", never "reconnect".
    out = _result(is_error=True, result="Claude AI usage limit reached|1759000000")
    with pytest.raises(UsageLimitReached) as info:
        parse_result(out, "", 1)
    assert "reconnecting does not" in str(info.value)


def test_other_failures_fail_the_row():
    with pytest.raises(ClaudeCodeError):
        parse_result(_result(subtype="error_max_structured_output_retries", is_error=True), "", 1)


def test_non_json_output_is_classified():
    with pytest.raises(AuthUnavailable):
        parse_result("", "Invalid API key · Please run /login", 1)
    with pytest.raises(ClaudeCodeError):
        parse_result("", "segfault", 139)


NOW = datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc)


def test_reset_time_from_an_epoch_suffix():
    epoch = int(datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc).timestamp())
    when = parse_reset_time(f"Claude AI usage limit reached|{epoch}", NOW)
    assert when == datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)


def test_reset_time_from_a_clock_time_with_a_zone():
    # 9:30 AM in New York when it is asked; 3pm there is 19:00 UTC.
    when = parse_reset_time("You've hit your limit · resets 3pm (America/New_York)", NOW)
    assert when == datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc)
    when = parse_reset_time("limit reached. Your limit will reset at 2:15pm (UTC)", NOW)
    assert when == datetime(2026, 10, 2, 14, 15, tzinfo=timezone.utc)


def test_reset_time_already_past_today_means_tomorrow():
    when = parse_reset_time("usage limit reached, resets 9am (UTC)", NOW)
    assert when == datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)


def test_reset_time_is_none_when_the_message_does_not_say():
    assert parse_reset_time("Claude usage limit reached", NOW) is None
    assert parse_reset_time("resets Oct 9, 9am (Mars/Olympus)", NOW) is None
    # A stale or absurd timestamp is not trusted.
    assert parse_reset_time("usage limit reached|1000000000", NOW) is None


def test_usage_limit_carries_its_reset_time():
    epoch = int(datetime.now(timezone.utc).timestamp()) + 3600
    out = _result(is_error=True, result=f"Claude AI usage limit reached|{epoch}")
    with pytest.raises(UsageLimitReached) as info:
        parse_result(out, "", 1)
    assert int(info.value.resume_at.timestamp()) == epoch


LIMIT_EVENT = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "resetsAt": 1790961000,
        "rateLimitType": "five_hour",
        "unifiedWindows": {
            "five_hour": {"utilization": 0.2, "resetsAt": 1790961000},
            "seven_day": {"utilization": 0.62, "resetsAt": 1791064800},
        },
    },
}


def _stream(result: str, *, limit_event: dict | None = LIMIT_EVENT) -> str:
    lines = [json.dumps({"type": "system", "subtype": "init"})]
    if limit_event:
        lines.append(json.dumps(limit_event))
    lines.append(result)
    return "\n".join(lines)


def test_stream_output_yields_the_result_and_the_plan_limits():
    data, limits = split_stream(_stream(_result()))
    assert data["structured_output"] == {"summary": "ok", "facts": []}
    assert limits["unifiedWindows"]["seven_day"]["utilization"] == 0.62
    # The same parser still reads the older single-object output.
    parsed, usage = parse_result(_stream(_result()), "", 0)
    assert parsed == {"summary": "ok", "facts": []} and usage.output_tokens == 40
    assert split_stream(_result())[1] is None


def test_limits_summary_keeps_each_window_and_its_reset():
    summary = limits_summary(LIMIT_EVENT["rate_limit_info"])
    assert summary["status"] == "allowed"
    assert summary["windows"]["five_hour"]["utilization"] == 0.2
    assert summary["windows"]["seven_day"]["resets_at"] == datetime.fromtimestamp(1791064800, timezone.utc)


def test_a_limit_without_a_stated_reset_takes_it_from_the_limit_event():
    event = json.loads(json.dumps(LIMIT_EVENT))
    event["rate_limit_info"]["status"] = "rejected"
    out = _stream(_result(is_error=True, result="Claude usage limit reached"), limit_event=event)
    with pytest.raises(UsageLimitReached) as info:
        parse_result(out, "", 1)
    assert info.value.resume_at == datetime.fromtimestamp(1790961000, timezone.utc)
