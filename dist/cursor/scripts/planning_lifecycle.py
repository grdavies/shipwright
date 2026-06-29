#!/usr/bin/env python3
"""Single-sourced planning-unit lifecycle enum and transition classification (PRD 033 R1/R2/R23).

Replaces PRD 031's values-only stub at the same import surface. Transition semantics are data tables
consumed by the reconciler and scheduler — behavior lives in planning_graph / reconciler modules.
"""

from __future__ import annotations

from typing import Final

GAP_STATUSES: frozenset[str] = frozenset(
    {
        "open",
        "planned",
        "partially resolved",
        "resolved",
    }
)

LIFECYCLE_STATUSES: frozenset[str] = frozenset(
    {
        "proposed",
        "planned",
        "in-progress",
        "complete",
        "superseded",
        "cancelled",
        "deferred",
        "blocked",
    }
)

GAP_TYPE: Final[str] = "gap"
LIFECYCLE_TYPES: frozenset[str] = frozenset({"brainstorm", "prd", "decision", "amendment"})

PLANNED_HOMONYM_NOTE: Final[str] = (
    "planned is a homonym: gap units use planned (scheduled for work); "
    "lifecycle units use planned (accepted but not started / frozen)."
)

# R2 — transition classification (data only; reconciler never invents in-progress without deliver evidence).
MECHANICAL_DERIVED_STATUSES: frozenset[str] = frozenset({"in-progress", "complete", "blocked"})
FREEZE_GATE: tuple[str, str] = ("proposed", "planned")
HUMAN_GATED_STATUSES: frozenset[str] = frozenset({"superseded", "cancelled", "deferred"})

TRANSITION_CLASSIFICATION: dict[str, str] = {
    "in-progress": "mechanical",
    "complete": "mechanical",
    "blocked": "mechanical",
    "proposed->planned": "freeze-gate",
    "superseded": "human-gated",
    "cancelled": "human-gated",
    "deferred": "human-gated",
}


def allowed_statuses(unit_type: str) -> frozenset[str]:
    if unit_type == GAP_TYPE:
        return GAP_STATUSES
    if unit_type in LIFECYCLE_TYPES:
        return LIFECYCLE_STATUSES
    return frozenset()


def is_cross_enum_token(unit_type: str, status: str) -> bool:
    """True when status belongs exclusively to the other enum (not homonyms like planned)."""
    if unit_type == GAP_TYPE:
        return status in LIFECYCLE_STATUSES and status not in GAP_STATUSES
    if unit_type in LIFECYCLE_TYPES:
        return status in GAP_STATUSES and status not in LIFECYCLE_STATUSES
    return False


def validate_status(unit_type: str, status: str) -> str | None:
    """Closed-world status validation; rejects unknown tokens."""
    allowed = allowed_statuses(unit_type)
    if not allowed:
        return f"unknown unit type: {unit_type!r}"
    if is_cross_enum_token(unit_type, status):
        return f"cross-enum status {status!r} for type {unit_type!r}"
    if status not in allowed:
        return f"unknown status {status!r} for type {unit_type!r}"
    return None


def transition_kind(from_status: str, to_status: str) -> str | None:
    """Classify a transition edge for reconciler policy lookup."""
    if from_status == "proposed" and to_status == "planned":
        return TRANSITION_CLASSIFICATION["proposed->planned"]
    if to_status in MECHANICAL_DERIVED_STATUSES:
        return TRANSITION_CLASSIFICATION.get(to_status)
    if to_status in HUMAN_GATED_STATUSES:
        return TRANSITION_CLASSIFICATION.get(to_status)
    return None


def is_mechanical_status(status: str) -> bool:
    return status in MECHANICAL_DERIVED_STATUSES


def is_human_gated_status(status: str) -> bool:
    return status in HUMAN_GATED_STATUSES

def gap_absorption_target(absorber_derived: str, gap_status: str) -> str:
    """R11 — mechanical gap progression when an absorbing unit advances."""
    if absorber_derived == "complete":
        return "resolved"
    if absorber_derived == "in-progress":
        if gap_status == "resolved":
            return gap_status
        return "partially resolved"
    if absorber_derived == "planned" and gap_status == "open":
        return "planned"
    return gap_status

