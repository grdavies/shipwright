#!/usr/bin/env python3
"""Provenance actor-class and override tests (PRD 273 R18)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.provenance import (  # noqa: E402
    ActorClass,
    ProvenanceRecord,
    append_override,
    can_confirm_label,
    label_with_provenance,
    self_authored_alone,
)


def _record(actor: ActorClass, actor_id: str = "actor-1") -> ProvenanceRecord:
    return ProvenanceRecord(
        actor_class=actor,
        actor_id=actor_id,
        source="fixture",
        recorded_at="2026-08-16T00:00:00Z",
    )


def test_label_provenance_self_authored_not_sole_confirm() -> None:
    records = [_record(ActorClass.SELF_AUTHORED, "reviewer-a")]
    assert self_authored_alone(records) is True
    assert can_confirm_label(records) is False
    assert label_with_provenance(
        finding_id="finding-self",
        run_id="run-self",
        provenance_records=records,
        attribution_window="window",
        match_reason="exogenous-human",
        terminal_status="confirmed",
        provenance_summary="self-only",
    ) is None


def test_operator_provenance_can_confirm() -> None:
    records = [_record(ActorClass.OPERATOR, "operator-1")]
    assert can_confirm_label(records) is True
    label = label_with_provenance(
        finding_id="finding-op",
        run_id="run-op",
        provenance_records=records,
        attribution_window="window",
        match_reason="exogenous-human",
        terminal_status="confirmed",
        provenance_summary="operator:operator-1",
    )
    assert label is not None
    assert label.finding_id == "finding-op"


def test_self_authored_with_operator_can_confirm() -> None:
    records = [
        _record(ActorClass.SELF_AUTHORED, "reviewer-b"),
        _record(ActorClass.OPERATOR, "operator-2"),
    ]
    assert can_confirm_label(records) is True


def test_overrides_append_only() -> None:
    overrides = ()
    override_record = _record(ActorClass.OPERATOR, "operator-3")
    updated = append_override(
        overrides,
        prior_dedup_key="dedup-1",
        override=override_record,
        reason="operator correction",
    )
    assert len(updated) == 1
    assert updated[0].prior_dedup_key == "dedup-1"
    again = append_override(
        updated,
        prior_dedup_key="dedup-2",
        override=override_record,
        reason="second correction",
    )
    assert len(again) == 2
    assert again[0].reason == "operator correction"
    assert again[1].reason == "second correction"
