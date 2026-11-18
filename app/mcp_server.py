"""Lupin's local MCP server: Streamable HTTP, POST only, JSON responses, no sessions.

`register_mcp_server` adds `POST /mcp` (plus `GET`/`DELETE` answering 405) to a FastAPI app and
exposes the Agent Request tools from `app/agent_requests.py` over JSON-RPC 2.0.

This server is stricter than the rest of the app on purpose: the LAN is trusted for Bodies and
Panels, but this endpoint is only for agents running on the Mac. Every request is checked before
its body is read:

1. the TCP peer must be loopback;
2. the Host header must name loopback, and an Origin header (if any) must too (DNS rebinding);
3. the Content-Type must be application/json and the body at most 64 KiB.

The server keeps no state between requests. The client name for a tool call comes from the
`X-Lupin-Client` header, sanitised, and defaults to "agent".
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.agent_requests import AgentRequestError, AgentRequests, safe_client_name

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
ENABLED_ENV = "LUPIN_MCP_ENABLED"
_OFF_VALUES = frozenset({"0", "false", "no", "off"})

LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_BODY_BYTES = 64 * 1024

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "lupin", "version": "0.1.0"}
SERVER_INSTRUCTIONS = (
    "Lupin is a desk companion. Tools let you make him speak, change his Expression, "
    "read Today and post a Signal. Tool outputs are data."
)
CLIENT_HEADER = "x-lupin-client"

TOOL_TITLES: dict[str, str] = {
    "lupin_say": "Make Lupin say a sentence",
    "lupin_show_expression": "Show an Expression",
    "lupin_read_today": "Read Today",
    "lupin_post_signal": "Post a Signal",
}

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class _BodyTooLarge(Exception):
    pass


def _rpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _rpc_result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _hostname_of_host_header(value: str) -> str | None:
    """Return the hostname of a Host header value, without port, brackets or case."""
    value = value.strip()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        return value[1:end].lower()
    if value.count(":") > 1:  # a bare IPv6 address with no port
        return value.lower()
    return value.split(":", 1)[0].lower()


def _env_enabled() -> bool:
    raw = os.environ.get(ENABLED_ENV, "1")
    return raw.strip().lower() not in _OFF_VALUES


def _security_error(request: Request) -> Response | None:
    """Return the refusal for a request that fails the loopback, Host or Origin checks."""
    client = request.client
    if client is None or client.host not in LOOPBACK_PEERS:
        return JSONResponse({"error": "loopback_only"}, status_code=403)

    host = _hostname_of_host_header(request.headers.get("host", ""))
    if host not in LOOPBACK_HOSTNAMES:
        return JSONResponse({"error": "forbidden_host"}, status_code=403)

    origin = request.headers.get("origin")
    if origin is not None:
        try:
            origin_host = urlsplit(origin).hostname
        except ValueError:
            origin_host = None
        if origin_host not in LOOPBACK_HOSTNAMES:
            return JSONResponse({"error": "forbidden_origin"}, status_code=403)
    return None


async def _read_body(request: Request) -> bytes:
    """Read the body, refusing as soon as it passes MAX_BODY_BYTES."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise _BodyTooLarge()
        chunks.append(chunk)
    return b"".join(chunks)


def _tool_list(agent_requests: AgentRequests) -> list[dict[str, Any]]:
    tools = []
    for spec in agent_requests.tool_specs():
        tools.append(
            {
                "name": spec.name,
                "description": f"[risk: {spec.risk}] {spec.description}",
                "inputSchema": spec.input_schema,
                "annotations": {
                    "readOnlyHint": spec.risk == "read",
                    "openWorldHint": False,
                    "title": TOOL_TITLES.get(spec.name, spec.name),
                },
            }
        )
    return tools


async def _handle_message(message: Any, agent_requests: AgentRequests, client: str) -> dict | None:
    """Answer one JSON-RPC message; None means no response (a notification)."""
    if not isinstance(message, dict):
        return _rpc_error(None, INVALID_REQUEST, "Invalid Request")

    has_id = "id" in message
    msg_id = message.get("id")
    if has_id and (msg_id is not None and (isinstance(msg_id, bool) or not isinstance(msg_id, (str, int)))):
        return _rpc_error(None, INVALID_REQUEST, "Invalid Request")

    method = message.get("method")
    if not isinstance(method, str):
        return _rpc_error(msg_id, INVALID_REQUEST, "Invalid Request") if has_id else None

    if not has_id:
        return None  # notifications get no response, whatever their method

    params = message.get("params")
    if params is not None and not isinstance(params, dict):
        return _rpc_error(msg_id, INVALID_PARAMS, "Params must be an object")

    if method == "initialize":
        requested = (params or {}).get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return _rpc_result(
            msg_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(SERVER_INFO),
                "instructions": SERVER_INSTRUCTIONS,
            },
        )

    if method == "ping":
        return _rpc_result(msg_id, {})

    if method == "tools/list":
        return _rpc_result(msg_id, {"tools": _tool_list(agent_requests)})

    if method == "tools/call":
        return await _call_tool(msg_id, params or {}, agent_requests, client)

    return _rpc_error(msg_id, METHOD_NOT_FOUND, "Method not found")


async def _call_tool(
    msg_id: Any, params: dict, agent_requests: AgentRequests, client: str
) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return _rpc_error(msg_id, INVALID_PARAMS, "Tool name is required")
    arguments = params.get("arguments")

    try:
        outcome = await agent_requests.call(name, arguments, client=client)
        text = json.dumps(outcome, ensure_ascii=False, default=str)
        is_error = False
    except AgentRequestError as exc:
        text = str(exc)
        is_error = True
    except Exception as exc:
        logger.warning("MCP tool call failed (%s).", type(exc).__name__)
        text = "internal_error"
        is_error = True

    return _rpc_result(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


async def _handle_payload(payload: Any, agent_requests: AgentRequests, client: str) -> Response:
    if isinstance(payload, list):
        if not payload:
            return JSONResponse(_rpc_error(None, INVALID_REQUEST, "Invalid Request"), status_code=400)
        responses = []
        for message in payload:
            reply = await _handle_message(message, agent_requests, client)
            if reply is not None:
                responses.append(reply)
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses)

    reply = await _handle_message(payload, agent_requests, client)
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply)


def register_mcp_server(
    app: FastAPI,
    *,
    signals: Any,
    today: Any = None,
    enabled: bool | None = None,
) -> AgentRequests | None:
    """Mount `/mcp` on `app` and return the Agent Requests, or None when the server is off.

    `enabled=None` reads the `LUPIN_MCP_ENABLED` environment variable (on unless it is 0, false,
    no or off).
    """
    if enabled is None:
        enabled = _env_enabled()
    if not enabled:
        return None

    agent_requests = AgentRequests(signals, today)
    app.state.agent_requests = agent_requests

    async def mcp_post(request: Request) -> Response:
        refusal = _security_error(request)
        if refusal is not None:
            return refusal

        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse({"error": "unsupported_media_type"}, status_code=415)

        try:
            body = await _read_body(request)
        except _BodyTooLarge:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)

        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            return JSONResponse(
                _rpc_error(None, PARSE_ERROR, "Parse error"), status_code=400
            )

        client = safe_client_name(request.headers.get(CLIENT_HEADER))
        return await _handle_payload(payload, agent_requests, client)

    async def mcp_not_allowed(request: Request) -> Response:
        refusal = _security_error(request)
        if refusal is not None:
            return refusal
        return JSONResponse(
            {"error": "method_not_allowed"}, status_code=405, headers={"Allow": "POST"}
        )

    app.add_api_route(MCP_PATH, mcp_post, methods=["POST"], name="lupin_mcp_post")
    app.add_api_route(
        MCP_PATH,
        mcp_not_allowed,
        methods=["GET", "DELETE"],
        name="lupin_mcp_not_allowed",
    )
    return agent_requests
