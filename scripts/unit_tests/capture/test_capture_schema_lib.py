"""Unit tests for capture schema validation (PRD 350 TS2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _sw.capture_schema_lib import (
    CapturePrivacyError,
    CaptureSchemaError,
    EVENT_TYPES,
    compute_event_id,
    validate_event,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "capture-events"


def _base(**overrides):
    run_id = "run-test"
    phase_id = "1"
    event_type = "task_start"
    ts = "2026-09-12T20:00:00Z"
    event = {
        "eventId": compute_event_id(run_id, phase_id, event_type, ts),
        "schemaVersion": "1",
        "eventType": event_type,
        "runId": run_id,
        "phaseId": phase_id,
        "agentId": "agent-a",
        "timestamp": ts,
        "provenanceKind": "tool_output",
        "provenanceRef": "tool:1",
        "summary": "task: hello",
        "pendingState": None,
    }
    event.update(overrides)
    if "eventId" not in overrides and {
        "runId",
        "phaseId",
        "eventType",
        "timestamp",
    } & overrides.keys():
        event["eventId"] = compute_event_id(
            event["runId"], event["phaseId"], event["eventType"], event["timestamp"]
        )
    return event


@pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
def test_valid_event_types_pass(event_type: str) -> None:
    event = _base(eventType=event_type)
    event["eventId"] = compute_event_id(
        event["runId"], event["phaseId"], event_type, event["timestamp"]
    )
    validate_event(event)


def test_missing_required_field_raises() -> None:
    event = _base()
    del event["summary"]
    with pytest.raises(CaptureSchemaError, match="summary"):
        validate_event(event)


def test_privacy_rejects_bearer_token() -> None:
    event = _base(summary="status: Bearer sk-abcdefghijklmnopqrstuvwxyz0123456789")
    with pytest.raises(CapturePrivacyError):
        validate_event(event)


def test_privacy_rejects_long_unstructured_line() -> None:
    event = _base(summary="x" * 201)
    with pytest.raises(CapturePrivacyError):
        validate_event(event)


def test_compute_event_id_is_16_hex() -> None:
    eid = compute_event_id("r", "p", "task_start", "2026-01-01T00:00:00Z")
    assert len(eid) == 16
    assert all(c in "0123456789abcdef" for c in eid)


def test_fixtures_round_trip() -> None:
    for path in sorted(FIX.glob("*.json")):
        event = json.loads(path.read_text(encoding="utf-8"))
        validate_event(event)
