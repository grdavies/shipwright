"""Emit-time redaction chokepoint for host transport and verb payloads (PRD 079 R18)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from host_ratelimit import normalize_headers  # noqa: E402

EMIT_HEADER_ALLOWLIST = frozenset(
    {
        "content-type",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-used",
        "x-ratelimit-resource",
        "x-ratelimit-nearlimit",
        "x-github-media-type",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "ratelimit-used",
    }
)


def redact_emit_text(text: str) -> str:
    """Scrub deny-pattern secrets from a string (PRD 079 R18)."""
    from secret_patterns import REDACTIONS  # noqa: WPS433

    out = text
    for pattern, replacement in REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def filter_emit_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """Return only allowlisted response headers with redacted values (PRD 079 R18)."""
    if not headers:
        return {}
    normalized = normalize_headers(headers if isinstance(headers, dict) else None)
    out: dict[str, str] = {}
    for key, value in normalized.items():
        if key not in EMIT_HEADER_ALLOWLIST:
            continue
        out[key] = redact_emit_text(str(value))
    return out


def redact_emit_value(value: Any) -> Any:
    """Recursively redact strings in an emit-bound payload (PRD 079 R18)."""
    if isinstance(value, str):
        return redact_emit_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "headers" and isinstance(item, dict):
                out[key] = filter_emit_headers(item)
            else:
                out[key] = redact_emit_value(item)
        return out
    if isinstance(value, list):
        return [redact_emit_value(item) for item in value]
    return value


def redact_emit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Emit-time chokepoint for host transport and verb projections (PRD 079 R18)."""
    redacted = redact_emit_value(payload)
    return redacted if isinstance(redacted, dict) else payload


def redact_transport_payload(transport: dict[str, Any]) -> dict[str, Any]:
    """Redact a transport envelope before gate/status emit (PRD 079 R18)."""
    return redact_emit_payload(transport)
