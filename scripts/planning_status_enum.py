#!/usr/bin/env python3
"""Stub status enums for planning-unit validation (PRD 031 R4).

Values only — transition semantics owned by PRD 033.
The token ``planned`` is a homonym: valid for gap and lifecycle types with distinct semantics.
"""

from __future__ import annotations

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

GAP_TYPE = "gap"
LIFECYCLE_TYPES: frozenset[str] = frozenset({"brainstorm", "prd", "decision", "amendment"})

PLANNED_HOMONYM_NOTE = (
    "planned is a homonym: gap units use planned (scheduled for work); "
    "lifecycle units use planned (accepted but not started)."
)


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
    allowed = allowed_statuses(unit_type)
    if not allowed:
        return f"unknown unit type: {unit_type!r}"
    if is_cross_enum_token(unit_type, status):
        return f"cross-enum status {status!r} for type {unit_type!r}"
    if status not in allowed:
        return f"unknown status {status!r} for type {unit_type!r}"
    return None
