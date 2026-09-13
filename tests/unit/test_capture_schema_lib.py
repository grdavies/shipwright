"""Unit tests for capture_schema_lib (PRD 350 TS2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _sw.capture_schema_lib import (
    EVENT_TYPES,
    CapturePrivacyError,
    CaptureSchemaError,
    compute_event_id,
    validate_event,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "capture-events"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
def test_valid_event_types_pass(event_type: str) -> None:
    event = _load_fixture(f"{event_type}.json")
    validate_event(event)


def test_missing_mandatory_field_raises() -> None:
    event = _load_fixture("task_start.json")
    del event["summary"]
    with pytest.raises(CaptureSchemaError, match="missing required field: summary"):
        validate_event(event)


def test_compute_event_id_is_16_char_hex() -> None:
    eid = compute_event_id("run-a", "phase-b", "discovery", "2026-09-12T10:00:00Z")
    assert len(eid) == 16
    assert all(c in "0123456789abcdef" for c in eid)
    # Stable for identical inputs.
    assert eid == compute_event_id("run-a", "phase-b", "discovery", "2026-09-12T10:00:00Z")


def test_privacy_error_on_long_unstructured_line() -> None:
    event = _load_fixture("discovery.json")
    event["summary"] = "x" * 201
    # Recompute id because summary change does not affect id, but keep valid otherwise.
    with pytest.raises(CapturePrivacyError, match="raw transcript"):
        validate_event(event)


def test_privacy_error_on_bearer_token() -> None:
    event = _load_fixture("discovery.json")
    event["summary"] = "auth failed Bearer sk-abcdefghijklmnopqrstuvwxyz012345"
    with pytest.raises(CapturePrivacyError, match="Bearer"):
        validate_event(event)


def test_privacy_error_on_long_base64() -> None:
    event = _load_fixture("discovery.json")
    # Non-hex base64 alphabet (+ / =) so pure-hex digests are not flagged.
    event["summary"] = "blob " + ("AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/" * 2)
    with pytest.raises(CapturePrivacyError, match="base64"):
        validate_event(event)


def test_privacy_allows_git_sha_and_hex_digest() -> None:
    event = _load_fixture("discovery.json")
    event["summary"] = "tip " + ("a" * 40)
    event["provenanceRef"] = "sha256:" + ("b" * 64)
    validate_event(event)  # must not raise


def test_privacy_error_on_private_key_header() -> None:
    event = _load_fixture("discovery.json")
    event["summary"] = "key -----BEGIN RSA PRIVATE KEY-----"
    with pytest.raises(CapturePrivacyError, match="private key"):
        validate_event(event)
