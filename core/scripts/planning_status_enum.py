#!/usr/bin/env python3
"""Backward-compatible re-export shim — PRD 033 single-sources enum in planning_lifecycle."""

from __future__ import annotations

from planning_lifecycle import (  # noqa: F401
    FREEZE_GATE,
    GAP_STATUSES,
    GAP_TYPE,
    HUMAN_GATED_STATUSES,
    LIFECYCLE_STATUSES,
    LIFECYCLE_TYPES,
    MECHANICAL_DERIVED_STATUSES,
    PLANNED_HOMONYM_NOTE,
    TRANSITION_CLASSIFICATION,
    allowed_statuses,
    is_cross_enum_token,
    is_human_gated_status,
    is_mechanical_status,
    transition_kind,
    validate_status,
)
