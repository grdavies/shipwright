#!/usr/bin/env python3
"""Immutable label provenance with actor classes (PRD 273 R18)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from graph.reviewer_metrics.label_schema import ExogenousLabel, build_label


class ActorClass(str, Enum):
    OPERATOR = "operator"
    SYSTEM = "system"
    PEER = "peer"
    SELF_AUTHORED = "self-authored"
    EXOGENOUS = "exogenous"


CONFIRMING_ACTOR_CLASSES = frozenset(
    {ActorClass.OPERATOR, ActorClass.SYSTEM, ActorClass.EXOGENOUS}
)


@dataclass(frozen=True)
class ProvenanceRecord:
    """Immutable provenance binding for a label decision."""

    actor_class: ActorClass
    actor_id: str
    source: str
    recorded_at: str
    immutable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "actorClass": self.actor_class.value,
            "actorId": self.actor_id,
            "source": self.source,
            "recordedAt": self.recorded_at,
            "immutable": self.immutable,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProvenanceRecord:
        actor = ActorClass(str(payload.get("actorClass", "")))
        return cls(
            actor_class=actor,
            actor_id=str(payload.get("actorId", "")),
            source=str(payload.get("source", "")),
            recorded_at=str(payload.get("recordedAt", "")),
            immutable=bool(payload.get("immutable", True)),
        )


@dataclass(frozen=True)
class ProvenanceOverride:
    """Append-only override event — never mutates prior provenance."""

    prior_dedup_key: str
    override: ProvenanceRecord
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "priorDedupKey": self.prior_dedup_key,
            "override": self.override.to_dict(),
            "reason": self.reason,
        }


def has_confirming_provenance(records: Sequence[ProvenanceRecord]) -> bool:
    return any(record.actor_class in CONFIRMING_ACTOR_CLASSES for record in records)


def self_authored_alone(records: Sequence[ProvenanceRecord]) -> bool:
    if not records:
        return False
    return all(record.actor_class == ActorClass.SELF_AUTHORED for record in records)


def can_confirm_label(records: Sequence[ProvenanceRecord]) -> bool:
    """Self-authored provenance alone is insufficient to confirm a label."""
    if not records:
        return False
    if self_authored_alone(records):
        return False
    return has_confirming_provenance(records)


def append_override(
    overrides: Sequence[ProvenanceOverride],
    *,
    prior_dedup_key: str,
    override: ProvenanceRecord,
    reason: str,
) -> tuple[ProvenanceOverride, ...]:
    """Return a new tuple with the override appended (append-only semantics)."""
    event = ProvenanceOverride(
        prior_dedup_key=prior_dedup_key,
        override=override,
        reason=reason,
    )
    return (*overrides, event)


def label_with_provenance(
    *,
    finding_id: str,
    run_id: str,
    provenance_records: Sequence[ProvenanceRecord],
    attribution_window: str,
    match_reason: str,
    terminal_status: str,
    provenance_summary: str,
) -> ExogenousLabel | None:
    if not can_confirm_label(provenance_records):
        return None
    return build_label(
        finding_id=finding_id,
        run_id=run_id,
        provenance=provenance_summary,
        attribution_window=attribution_window,
        match_reason=match_reason,
        terminal_status=terminal_status,
    )
