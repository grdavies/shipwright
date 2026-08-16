#!/usr/bin/env python3
"""Label schema fixtures — positive, negative, ambiguous, duplicate, late (PRD 273 R12)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.label_schema import (  # noqa: E402
    ExogenousLabel,
    LabelSchemaError,
    build_label,
    compute_dedup_key,
    required_label_fields,
    resolve_conflict,
    validate_label_payload,
)


def test_label_schema_required_fields_present() -> None:
    assert required_label_fields() == (
        "schemaVersion",
        "findingId",
        "runId",
        "provenance",
        "attributionWindow",
        "matchReason",
        "terminalStatus",
        "dedupKey",
        "conflictPrecedence",
    )
    label = build_label(
        finding_id="finding-1",
        run_id="run-1",
        provenance="operator:alice",
        attribution_window="2026-08-01/2026-08-16",
        match_reason="exogenous-human",
        terminal_status="confirmed",
    )
    payload = label.to_dict()
    for field in required_label_fields():
        assert field in payload
    roundtrip = ExogenousLabel.from_dict(payload)
    assert roundtrip.finding_id == "finding-1"
    assert roundtrip.run_id == "run-1"


def test_positive_exogenous_label_fixture() -> None:
    label = build_label(
        finding_id="finding-positive",
        run_id="run-positive",
        provenance="ci:post-merge",
        attribution_window="window-a",
        match_reason="exogenous-ci",
        terminal_status="confirmed",
    )
    validate_label_payload(label.to_dict())
    assert label.terminal_status == "confirmed"
    assert label.match_reason == "exogenous-ci"


def test_negative_rejected_label_fixture() -> None:
    label = build_label(
        finding_id="finding-negative",
        run_id="run-negative",
        provenance="operator:bob",
        attribution_window="window-b",
        match_reason="exogenous-human",
        terminal_status="rejected",
    )
    assert label.terminal_status == "rejected"


def test_ambiguous_label_fixture() -> None:
    label = build_label(
        finding_id="finding-ambiguous",
        run_id="run-ambiguous",
        provenance="system:arbiter",
        attribution_window="window-c",
        match_reason="peer-agreement",
        terminal_status="ambiguous",
    )
    assert label.terminal_status == "ambiguous"


def test_duplicate_dedup_key_fixture() -> None:
    first = build_label(
        finding_id="finding-dup",
        run_id="run-dup",
        provenance="operator:carol",
        attribution_window="window-d",
        match_reason="exogenous-human",
        terminal_status="confirmed",
    )
    second = build_label(
        finding_id="finding-dup",
        run_id="run-dup",
        provenance="operator:carol",
        attribution_window="window-d",
        match_reason="exogenous-human",
        terminal_status="confirmed",
    )
    assert first.dedup_key == second.dedup_key
    assert first.dedup_key == compute_dedup_key(
        finding_id="finding-dup",
        run_id="run-dup",
        match_reason="exogenous-human",
    )


def test_late_label_fixture() -> None:
    label = build_label(
        finding_id="finding-late",
        run_id="run-late",
        provenance="operator:late",
        attribution_window="window-e",
        match_reason="late-correction",
        terminal_status="late",
    )
    assert label.terminal_status == "late"
    assert label.match_reason == "late-correction"


def test_conflict_precedence_prefers_operator_override() -> None:
    operator = build_label(
        finding_id="finding-conflict",
        run_id="run-conflict",
        provenance="operator:dan",
        attribution_window="window-f",
        match_reason="operator-override",
        terminal_status="confirmed",
    )
    peer = build_label(
        finding_id="finding-conflict",
        run_id="run-conflict",
        provenance="peer:panel",
        attribution_window="window-f",
        match_reason="peer-agreement",
        terminal_status="confirmed",
    )
    winner = resolve_conflict([peer, operator])
    assert winner is not None
    assert winner.match_reason == "operator-override"


def test_missing_required_field_raises() -> None:
    label = build_label(
        finding_id="finding-missing",
        run_id="run-missing",
        provenance="operator:eve",
        attribution_window="window-g",
        match_reason="exogenous-human",
        terminal_status="confirmed",
    )
    payload = label.to_dict()
    del payload["findingId"]
    with pytest.raises(LabelSchemaError):
        validate_label_payload(payload)
