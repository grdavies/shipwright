"""Conformance: fixtures validate against capture-event-schema.json (PRD 350 TS6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _sw.capture_schema_lib import load_schema, validate_event_against_schema_document

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "capture-events"


@pytest.mark.parametrize("path", sorted(FIX.glob("*.json")), ids=lambda p: p.stem)
def test_fixture_conforms_to_schema(path: Path) -> None:
    event = json.loads(path.read_text(encoding="utf-8"))
    schema = load_schema()
    validate_event_against_schema_document(event, schema)
