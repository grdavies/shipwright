"""Conformance: capture fixtures validate against capture-event-schema.json (TS6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _sw.capture_schema_lib import load_schema, validate_event_against_schema_document

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "capture-events"


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


def test_fixtures_directory_has_seven_event_types() -> None:
    names = {path.stem for path in _fixture_files()}
    assert names == {
        "task_start",
        "milestone",
        "discovery",
        "verification",
        "blocker",
        "delegation",
        "interruption",
    }


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.stem)
def test_fixture_conforms_to_schema(path: Path) -> None:
    event = json.loads(path.read_text(encoding="utf-8"))
    schema = load_schema()
    assert schema.get("schemaVersion") == "1"
    validate_event_against_schema_document(event, schema)
