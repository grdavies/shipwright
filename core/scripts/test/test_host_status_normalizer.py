"""Unit tests for host transport statusCode normalization (PRD 079 R3)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from _sw.host._common import (  # noqa: E402
    remote_ref_exists_from_transport,
    transport_ok,
    transport_status_code,
)


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        ({"statusCode": 404}, 404),
        ({"status": 403}, 403),
        ({"statusCode": 200, "status": 500}, 200),
        ({}, None),
        ({"verdict": "ok"}, None),
        ({"statusCode": "not-a-number"}, None),
    ],
)
def test_transport_status_code(transport: dict, expected: int | None) -> None:
    assert transport_status_code(transport) == expected


def test_transport_status_code_missing_is_not_200() -> None:
    assert transport_status_code({}) is None
    assert transport_status_code({"verdict": "ok", "body": "{}"}) is None


def test_transport_ok_missing_status_does_not_assume_200() -> None:
    assert transport_ok({"verdict": "ok", "body": "{}"}) is True
    assert transport_ok({"verdict": "degraded"}) is False


def test_remote_ref_missing_status_probe_inconclusive() -> None:
    payload, code = remote_ref_exists_from_transport(
        verb="ref-exists",
        provider="github",
        branch="main",
        transport={"verdict": "ok", "body": "{}"},
    )
    assert payload["reason"] == "probe-inconclusive"
    assert code == 30


def test_remote_ref_status_code_only_404() -> None:
    payload, code = remote_ref_exists_from_transport(
        verb="ref-exists",
        provider="github",
        branch="main",
        transport={"verdict": "ok", "statusCode": 404, "body": "{}"},
    )
    assert payload["verdict"] == "ok"
    assert payload["data"]["exists"] is False
    assert code == 0


def test_remote_ref_legacy_status_only_200() -> None:
    payload, code = remote_ref_exists_from_transport(
        verb="ref-exists",
        provider="github",
        branch="main",
        transport={"verdict": "ok", "status": 200, "body": "{}"},
    )
    assert payload["verdict"] == "ok"
    assert payload["data"]["exists"] is True
    assert code == 0
