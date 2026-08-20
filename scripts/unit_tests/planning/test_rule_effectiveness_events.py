"""Unit tests for rule effectiveness events (PRD 280 phase 1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from rule_effectiveness import (
    ValidationError,
    build_record,
    list_events,
    put_event,
    validate_record,
)


def test_schema_validates_required_fields() -> None:
    record = build_record(
        rule_id="mock-realism",
        surface="rules-load",
        provider="in-repo",
        outcome="loaded",
    )
    result = validate_record(record)
    assert result["verdict"] == "pass"


def test_schema_rejects_missing_rule_id() -> None:
    record = build_record(
        rule_id="mock-realism",
        surface="rules-load",
        provider="in-repo",
        outcome="loaded",
    )
    record.pop("ruleId")
    result = validate_record(record)
    assert result["verdict"] == "fail"


def test_put_event_idempotent(tmp_path: Path) -> None:
    record = build_record(
        rule_id="mock-realism",
        surface="rules-load",
        provider="in-repo",
        outcome="loaded",
    )
    first = put_event(tmp_path, record, provider="in-repo")
    second = put_event(tmp_path, record, provider="in-repo")
    assert first["verdict"] == "pass"
    assert second["verdict"] == "pass"
    assert second.get("idempotent") is True
    rows = list_events(tmp_path, provider="in-repo")
    assert len(rows) == 1


def test_list_events_filters_by_rule_id(tmp_path: Path) -> None:
    put_event(
        tmp_path,
        build_record(
            rule_id="alpha",
            surface="rules-load",
            provider="in-repo",
            outcome="loaded",
        ),
        provider="in-repo",
    )
    put_event(
        tmp_path,
        build_record(
            rule_id="beta",
            surface="rules-load",
            provider="in-repo",
            outcome="loaded",
        ),
        provider="in-repo",
    )
    rows = list_events(tmp_path, rule_id="alpha", provider="in-repo")
    assert len(rows) == 1
    assert rows[0]["ruleId"] == "alpha"


def test_record_rejects_empty_rule_id() -> None:
    with pytest.raises(ValidationError):
        build_record(
            rule_id="",
            surface="rules-load",
            provider="in-repo",
            outcome="loaded",
        )
