#!/usr/bin/env python3
"""Versioned exogenous label schema for reviewer effectiveness (PRD 273 R12)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

LABEL_SCHEMA_VERSION = 1

TERMINAL_STATUSES = frozenset({"confirmed", "rejected", "ambiguous", "superseded", "late"})
MATCH_REASONS = frozenset(
    {
        "exogenous-ci",
        "exogenous-post-merge",
        "exogenous-human",
        "peer-agreement",
        "operator-override",
        "late-correction",
    }
)
CONFLICT_PRECEDENCE: tuple[str, ...] = (
    "operator-override",
    "exogenous-human",
    "exogenous-post-merge",
    "exogenous-ci",
    "late-correction",
    "peer-agreement",
)


class LabelSchemaError(ValueError):
    """Raised when a label payload violates the versioned schema."""


class TerminalStatus(str, Enum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"
    SUPERSEDED = "superseded"
    LATE = "late"


@dataclass(frozen=True)
class ExogenousLabel:
    """Immutable exogenous label with provenance and dedup metadata."""

    schema_version: int
    finding_id: str
    run_id: str
    provenance: str
    attribution_window: str
    match_reason: str
    terminal_status: str
    dedup_key: str
    conflict_precedence: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "findingId": self.finding_id,
            "runId": self.run_id,
            "provenance": self.provenance,
            "attributionWindow": self.attribution_window,
            "matchReason": self.match_reason,
            "terminalStatus": self.terminal_status,
            "dedupKey": self.dedup_key,
            "conflictPrecedence": self.conflict_precedence,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExogenousLabel:
        validate_label_payload(payload)
        return cls(
            schema_version=int(payload["schemaVersion"]),
            finding_id=str(payload["findingId"]),
            run_id=str(payload["runId"]),
            provenance=str(payload["provenance"]),
            attribution_window=str(payload["attributionWindow"]),
            match_reason=str(payload["matchReason"]),
            terminal_status=str(payload["terminalStatus"]),
            dedup_key=str(payload["dedupKey"]),
            conflict_precedence=int(payload["conflictPrecedence"]),
        )


def required_label_fields() -> tuple[str, ...]:
    return (
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


def validate_label_payload(payload: Mapping[str, Any]) -> None:
    missing = [field for field in required_label_fields() if field not in payload]
    if missing:
        raise LabelSchemaError(f"missing required fields: {', '.join(missing)}")
    version = int(payload["schemaVersion"])
    if version != LABEL_SCHEMA_VERSION:
        raise LabelSchemaError(f"unsupported schema version: {version}")
    terminal = str(payload["terminalStatus"])
    if terminal not in TERMINAL_STATUSES:
        raise LabelSchemaError(f"invalid terminal status: {terminal!r}")
    match_reason = str(payload["matchReason"])
    if match_reason not in MATCH_REASONS:
        raise LabelSchemaError(f"invalid match reason: {match_reason!r}")
    if not str(payload["findingId"]).strip() or not str(payload["runId"]).strip():
        raise LabelSchemaError("findingId and runId are required")
    if not str(payload["attributionWindow"]).strip():
        raise LabelSchemaError("attributionWindow is required")
    if not str(payload["dedupKey"]).strip():
        raise LabelSchemaError("dedupKey is required")


def conflict_precedence_rank(match_reason: str) -> int:
    try:
        return CONFLICT_PRECEDENCE.index(match_reason)
    except ValueError as exc:
        raise LabelSchemaError(f"unknown match reason for precedence: {match_reason!r}") from exc


def compute_dedup_key(*, finding_id: str, run_id: str, match_reason: str) -> str:
    material = json.dumps(
        {"findingId": finding_id, "runId": run_id, "matchReason": match_reason},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_label(
    *,
    finding_id: str,
    run_id: str,
    provenance: str,
    attribution_window: str,
    match_reason: str,
    terminal_status: str,
) -> ExogenousLabel:
    dedup_key = compute_dedup_key(
        finding_id=finding_id,
        run_id=run_id,
        match_reason=match_reason,
    )
    return ExogenousLabel(
        schema_version=LABEL_SCHEMA_VERSION,
        finding_id=finding_id,
        run_id=run_id,
        provenance=provenance,
        attribution_window=attribution_window,
        match_reason=match_reason,
        terminal_status=terminal_status,
        dedup_key=dedup_key,
        conflict_precedence=conflict_precedence_rank(match_reason),
    )


def resolve_conflict(labels: Sequence[ExogenousLabel]) -> ExogenousLabel | None:
    if not labels:
        return None
    return min(labels, key=lambda label: label.conflict_precedence)
