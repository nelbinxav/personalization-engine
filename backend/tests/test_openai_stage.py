"""The OpenAI stage runner's request shaping and response parsing, without
the network."""
import pytest

from app.ai import pricing
from app.ai.openai_stage import (
    OpenAIError,
    OpenAIRefusal,
    build_request,
    is_openai_model,
    openai_schema,
    parse_response,
)
from app.ai.schemas import AnglesOut, DraftOut, strict_schema
from app.models.prospect import Usage


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        found = set()
        for key, value in node.items():
            # Property names are data; only schema keywords are of interest.
            found |= _keys(value) if key == "properties" else {key} | _keys(value)
        return found
    if isinstance(node, list):
        return set().union(*(_keys(item) for item in node)) if node else set()
    return set()


def test_only_gpt_models_go_to_openai():
    assert is_openai_model("gpt-6-luna")
    assert not is_openai_model("claude-sonnet-5-5")


def test_schema_drops_keywords_strict_mode_rejects_but_keeps_fields():
    schema = openai_schema(strict_schema(AnglesOut))
    assert not {"default", "title", "examples"} & _keys(schema)
    assert {"angles", "sufficient", "fit_established", "fit_evidence"} <= set(schema["properties"])
    assert schema["additionalProperties"] is False
    # A field that happens to be called "title" is data, not a keyword.
    kept = openai_schema({"type": "object", "properties": {"title": {"type": "string", "title": "T"}}})
    assert kept["properties"] == {"title": {"type": "string"}}


def test_request_carries_the_schema_effort_and_both_turns():
    body = build_request(
        model="gpt-6-luna",
        system_text="rules",
        user_text="prospect",
        schema=strict_schema(DraftOut),
        effort="low",
        max_tokens=8000,
    )
    assert body["model"] == "gpt-6-luna" and body["reasoning"] == {"effort": "low"}
    assert [turn["role"] for turn in body["input"]] == ["system", "user"]
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"]
    assert body["store"] is False


def _response(**overrides) -> dict:
    data = {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": '{"summary": "ok"}'}]},
        ],
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 300,
            "input_tokens_details": {"cached_tokens": 1000},
        },
    }
    data.update(overrides)
    return data


def test_response_is_parsed_and_cached_input_is_split_out():
    parsed, usage = parse_response(_response())
    assert parsed == {"summary": "ok"}
    assert (usage.input_tokens, usage.cache_read_input_tokens, usage.output_tokens) == (200, 1000, 300)


def test_refusals_and_truncation_are_not_treated_as_answers():
    refused = _response(output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}])
    with pytest.raises(OpenAIRefusal):
        parse_response(refused)
    with pytest.raises(OpenAIError):
        parse_response(_response(status="incomplete", incomplete_details={"reason": "max_output_tokens"}))
    with pytest.raises(OpenAIError):
        parse_response(_response(output=[]))


def test_the_named_models_are_priced():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert pricing.cost_usd("claude-sonnet-5-5", usage) == 12.0
    assert pricing.cost_usd("gpt-6-luna", usage) == 0.6
