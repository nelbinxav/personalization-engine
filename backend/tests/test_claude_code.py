import json

import pytest

from app.ai.claude_code import ClaudeCodeError, UsageLimitReached, parse_result
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
