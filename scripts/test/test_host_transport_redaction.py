"""Emit-time transport redaction coverage (PRD 079 R18)."""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _sw.host import _common as common  # noqa: E402
from secret_patterns import DENY_PATTERNS  # noqa: E402

_GITHUB_CLASSIC = "ghp_" + "A" * 36
_GITHUB_FINE = "github_pat_" + "A" * 22
_GITHUB_OAUTH = "gho_" + "A" * 36
_BEARER = "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"


@pytest.mark.parametrize(
    ("pattern_name", "sample"),
    [
        ("GITHUB_PAT", _GITHUB_CLASSIC),
        ("GITHUB_PAT_FINE", _GITHUB_FINE),
        ("GITHUB_OAUTH", _GITHUB_OAUTH),
        ("BEARER_TOKEN", _BEARER),
    ],
)
def test_redact_emit_text_per_deny_pattern(pattern_name: str, sample: str) -> None:
    deny = next(p for p in DENY_PATTERNS if p.name == pattern_name)
    assert deny.pattern.search(sample) is not None
    redacted = common.redact_emit_text(sample)
    assert sample not in redacted
    assert "[REDACTED:" in redacted


def test_filter_emit_headers_allowlists_rate_limit_headers() -> None:
    headers = {
        "Authorization": f"Bearer {_GITHUB_CLASSIC}",
        "X-RateLimit-Remaining": "0",
        "Retry-After": "12",
        "Set-Cookie": "session=secret",
    }
    filtered = common.filter_emit_headers(headers)
    assert "authorization" not in filtered
    assert "set-cookie" not in filtered
    assert filtered["retry-after"] == "12"
    assert filtered["x-ratelimit-remaining"] == "0"


def test_redact_transport_payload_scrubs_body_and_headers() -> None:
    transport = {
        "verdict": "fail",
        "statusCode": 401,
        "body": json.dumps({"message": f"Bad credentials {_GITHUB_FINE}"}),
        "headers": {
            "Authorization": f"Bearer {_GITHUB_CLASSIC}",
            "X-RateLimit-Remaining": "10",
        },
    }
    redacted = common.redact_transport_payload(transport)
    serialized = json.dumps(redacted)
    assert _GITHUB_FINE not in serialized
    assert _GITHUB_CLASSIC not in serialized
    assert "github_pat_" not in serialized
    assert "ghp_" not in serialized
    assert redacted["headers"]["x-ratelimit-remaining"] == "10"
    assert "authorization" not in redacted["headers"]


def test_redact_emit_payload_covers_nested_projections() -> None:
    payload = {
        "verdict": "ok",
        "verb": "pr-view",
        "provider": "github",
        "data": {
            "title": "PR",
            "body": f"token leak {_GITHUB_FINE} in description",
        },
    }
    redacted = common.redact_emit_payload(payload)
    assert _GITHUB_FINE not in json.dumps(redacted)
    assert "[REDACTED:GITHUB_PAT_FINE]" in redacted["data"]["body"]


def test_emit_stdout_chokepoint_redacts_before_print() -> None:
    payload = {
        "verdict": "fail",
        "verb": "checks",
        "provider": "github",
        "body": f"auth failed with {_GITHUB_FINE}",
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        common.emit(payload)
    out = buf.getvalue()
    assert _GITHUB_FINE not in out
    assert "github_pat_" not in out


def test_github_pat_fine_pattern_registered() -> None:
    names = {p.name for p in DENY_PATTERNS}
    assert "GITHUB_PAT_FINE" in names
    match = next(p for p in DENY_PATTERNS if p.name == "GITHUB_PAT_FINE")
    assert match.pattern.search(_GITHUB_FINE) is not None
