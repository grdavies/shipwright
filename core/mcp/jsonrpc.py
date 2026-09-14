"""Minimal MCP JSON-RPC 2.0 helpers (PRD 352 R19 / TR5).

Implements the subset required for stdio MCP launchability without requiring the
full ``mcp`` SDK at import time. The ``mcp`` package is declared in
``scripts/_sw/depmanifest.json`` for supply-chain tracking (TR5).
"""

from __future__ import annotations

import json
from typing import Any, Mapping

JSONRPC_VERSION = "2.0"
# MCP protocol version negotiated at initialize (2024-11-05 is widely deployed).
DEFAULT_PROTOCOL_VERSION = "2024-11-05"


def make_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def make_error(
    request_id: Any,
    code: int,
    message: str,
    *,
    data: Any | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": err}


def parse_message(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    text = raw.strip()
    if not text:
        raise ValueError("empty JSON-RPC message")
    msg = json.loads(text)
    if not isinstance(msg, dict):
        raise ValueError("JSON-RPC message must be an object")
    return msg


def is_notification(msg: Mapping[str, Any]) -> bool:
    return "id" not in msg


def method_name(msg: Mapping[str, Any]) -> str:
    return str(msg.get("method") or "").strip()
