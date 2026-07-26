"""Unit tests for host transport classifier (PRD 079 R2, R4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from _sw.host._common import classify_transport  # noqa: E402


def test_classify_ok_200() -> None:
    transport = {"verdict": "ok", "statusCode": 200, "body": "{}"}
    assert classify_transport(transport, provider="github") == "ok"


def test_classify_ok_fixture_without_status() -> None:
    transport = {"verdict": "ok", "body": "{}"}
    assert classify_transport(transport, provider="github") == "ok"


def test_classify_auth_denied_401() -> None:
    transport = {"verdict": "ok", "statusCode": 401, "body": '{"message":"Bad credentials"}'}
    assert classify_transport(transport, provider="github") == "auth-denied"


def test_classify_auth_denied_403_without_throttle() -> None:
    transport = {
        "verdict": "ok",
        "statusCode": 403,
        "headers": {"x-github-media-type": "github.v3"},
        "body": '{"message":"Resource not accessible by integration"}',
    }
    assert classify_transport(transport, provider="github") == "auth-denied"


def test_classify_not_found_404() -> None:
    transport = {"verdict": "ok", "statusCode": 404, "body": '{"message":"Not Found"}'}
    assert classify_transport(transport, provider="github") == "not-found"


def test_classify_rate_limited_verdict() -> None:
    transport = {"verdict": "rate-limited", "statusCode": 403, "retryable": True}
    assert classify_transport(transport, provider="github") == "rate-limited"


def test_classify_rate_limited_403_throttle() -> None:
    transport = {
        "verdict": "ok",
        "statusCode": 403,
        "headers": {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"},
        "body": '{"message":"API rate limit exceeded"}',
    }
    assert classify_transport(transport, provider="github") == "rate-limited"


def test_classify_inconclusive_402() -> None:
    transport = {"verdict": "ok", "statusCode": 402, "body": '{"message":"Payment Required"}'}
    assert classify_transport(transport, provider="github") == "inconclusive"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (500, "inconclusive"),
        (502, "inconclusive"),
        (0, "inconclusive"),
    ],
)
def test_classify_inconclusive_other(status: int, expected: str) -> None:
    transport = {"verdict": "fail", "statusCode": status, "body": ""}
    assert classify_transport(transport, provider="github") == expected
