"""A minimal MCP client over streamable HTTP: just enough to call one tool.

Two research backends are MCP servers rather than plain REST APIs -- Exa's
hosted search and the LinkedIn browser service -- and both speak this
transport. Only what a single tool call needs is implemented: the initialize
handshake, the session header, and reading the answer from either a JSON body
or an event stream.
"""
import json
import logging

import httpx

from app.sources.base import SourceError, SourceRateLimited

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class ToolFailed(SourceError):
    """The server ran the tool and reported an error (`isError`)."""


def _read_reply(response: httpx.Response, request_id: int) -> dict:
    """The JSON-RPC message answering `request_id`, from JSON or an event stream.

    A stream can carry progress notifications before the answer, so every
    `data:` line is checked rather than only the first.
    """
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(f"Unreadable reply from {response.url.host}") from exc

    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            message = json.loads(line[5:].strip())
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    raise SourceError(f"{response.url.host} closed the stream without an answer")


async def _post(
    client: httpx.AsyncClient, url: str, payload: dict, headers: dict, timeout: float
) -> httpx.Response:
    try:
        response = await client.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise SourceError(f"{httpx.URL(url).host} did not answer within {timeout:.0f}s") from exc
    except httpx.TransportError as exc:
        raise SourceError(f"Could not reach {httpx.URL(url).host}: {exc}") from exc
    if response.status_code == 429:
        limited = SourceRateLimited(f"{response.url.host} rate limit hit.")
        try:
            limited.retry_after = float(response.headers.get("retry-after"))
        except (TypeError, ValueError):
            limited.retry_after = None
        raise limited
    if response.status_code >= 400:
        raise SourceError(f"{response.url.host} returned HTTP {response.status_code}")
    return response


def tool_text(result: dict) -> str:
    """The text of a tool result, joined across its content blocks."""
    return "\n".join(
        block.get("text", "")
        for block in result.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


async def call_tool(
    client: httpx.AsyncClient,
    url: str,
    name: str,
    arguments: dict,
    *,
    timeout: float = 60.0,
    handshake: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> dict:
    """Call one tool and return its result object (`content`, `structuredContent`).

    `handshake=False` skips initialize for servers that answer a bare call,
    which saves two round trips per search.
    """
    headers = {**_HEADERS, **(extra_headers or {})}

    if handshake:
        init = await _post(
            client,
            url,
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "personalization-engine", "version": "1"},
                },
            },
            headers,
            timeout,
        )
        reply = _read_reply(init, 0)
        if "error" in reply:
            raise SourceError(f"{init.url.host} refused the connection: {reply['error']}")
        session_id = init.headers.get("mcp-session-id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        negotiated = (reply.get("result") or {}).get("protocolVersion") or PROTOCOL_VERSION
        headers["MCP-Protocol-Version"] = negotiated
        await _post(
            client,
            url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers,
            timeout,
        )

    response = await _post(
        client,
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers,
        timeout,
    )
    reply = _read_reply(response, 1)
    if "error" in reply:
        error = reply["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise SourceError(f"{name} failed: {message}")

    result = reply.get("result") or {}
    if result.get("isError"):
        raise ToolFailed(tool_text(result) or f"{name} reported an error")
    return result
