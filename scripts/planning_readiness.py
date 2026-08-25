#!/usr/bin/env python3
"""Compute PlanningReadiness from exploration state (PRD 331 R11, R12, R39, R41)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from exploration_model import invalidate_dependent_output
from exploration_store import utc_now

UNKNOWN_CLASSIFICATIONS = frozenset({"blocking", "non-blocking", "deferred"})
READINESS_VERSION = "PlanningReadiness@v1"


class PlanningReadinessError(ValueError):
    """Invalid or stale planning readiness derivation."""


def _structured_unknowns(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    structured = map_document.get("structuredFields")
    if not isinstance(structured, dict):
        return []
    unknowns = structured.get("unknowns")
    if not isinstance(unknowns, list):
        return []
    collected: list[dict[str, Any]] = []
    for entry in unknowns:
        if not isinstance(entry, dict):
            continue
        unknown_id = str(entry.get("id") or "").strip()
        statement = str(entry.get("statement") or "").strip()
        classification = str(entry.get("classification") or "").strip()
        if not unknown_id or not statement or classification not in UNKNOWN_CLASSIFICATIONS:
            continue
        classified: dict[str, Any] = {
            "id": unknown_id,
            "statement": statement,
            "classification": classification,
        }
        rationale = entry.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            classified["rationale"] = rationale.strip()
        collected.append(classified)
    return collected


def _question_unknowns(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for node in map_document.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "question" or node.get("status") != "open":
            continue
        node_id = str(node.get("id") or "").strip()
        statement = str(node.get("statement") or node.get("title") or "").strip()
        if not node_id or not statement:
            continue
        classification = str(node.get("classification") or "blocking").strip()
        if classification not in UNKNOWN_CLASSIFICATIONS:
            classification = "blocking"
        collected.append(
            {
                "id": node_id,
                "statement": statement,
                "classification": classification,
                "sourceNodeId": node_id,
            }
        )
    return collected


def collect_unknowns(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Merge structured and open-question unknowns with deterministic ordering (R11, R12)."""
    merged: dict[str, dict[str, Any]] = {}
    for unknown in _structured_unknowns(map_document) + _question_unknowns(map_document):
        merged[unknown["id"]] = unknown
    return [merged[key] for key in sorted(merged)]


def summarize_unknowns(unknowns: list[Mapping[str, Any]]) -> dict[str, Any]:
    blocking = sum(1 for item in unknowns if item.get("classification") == "blocking")
    non_blocking = sum(1 for item in unknowns if item.get("classification") == "non-blocking")
    deferred = sum(1 for item in unknowns if item.get("classification") == "deferred")
    summary: dict[str, Any] = {
        "blockingCount": blocking,
        "nonBlockingCount": non_blocking,
        "deferredCount": deferred,
    }
    if not unknowns:
        summary["narrative"] = "No open unknowns remain."
    elif blocking:
        summary["narrative"] = f"{blocking} blocking unknown(s) must be resolved before doc handoff."
    else:
        summary["narrative"] = "No blocking unknowns; non-blocking or deferred items may remain."
    return summary


def ready_for_doc_handoff(unknowns: list[Mapping[str, Any]], *, invalidation_state: str) -> bool:
    if invalidation_state != "valid":
        return False
    return not any(item.get("classification") == "blocking" for item in unknowns)


def readiness_id_for_map(map_id: str) -> str:
    return f"readiness-{map_id}"


def compute_readiness(
    map_document: Mapping[str, Any],
    *,
    readiness_id: str | None = None,
    computed_at: str | None = None,
) -> dict[str, Any]:
    """Derive a deterministic PlanningReadiness@v1 document from the live map (R11, R12, R39)."""
    map_id = str(map_document.get("id") or "").strip()
    if not map_id:
        raise PlanningReadinessError("missing-map-id")
    revision = map_document.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise PlanningReadinessError("invalid-map-revision")
    unknowns = collect_unknowns(map_document)
    invalidation = {"state": "valid"}
    readiness: dict[str, Any] = {
        "id": readiness_id or readiness_id_for_map(map_id),
        "version": READINESS_VERSION,
        "sourceRevision": revision,
        "explorationMapId": map_id,
        "unknowns": deepcopy(unknowns),
        "summary": summarize_unknowns(unknowns),
        "invalidation": invalidation,
        "computedAt": computed_at or utc_now(),
        "readyForDocHandoff": ready_for_doc_handoff(unknowns, invalidation_state="valid"),
    }
    return readiness


def assert_fresh(readiness: Mapping[str, Any], map_document: Mapping[str, Any]) -> None:
    """Fail closed when readiness does not match the live map revision (R41)."""
    invalidation = readiness.get("invalidation")
    if isinstance(invalidation, dict) and invalidation.get("state") != "valid":
        raise PlanningReadinessError("readiness-invalidated")
    source_revision = readiness.get("sourceRevision")
    live_revision = map_document.get("revision")
    if not isinstance(source_revision, int) or not isinstance(live_revision, int):
        raise PlanningReadinessError("invalid-revision")
    if source_revision != live_revision:
        raise PlanningReadinessError("stale-readiness")


def refuse_invalidated(readiness: Mapping[str, Any]) -> None:
    """Refuse operations on invalidated readiness outputs (R41)."""
    invalidation = readiness.get("invalidation")
    if not isinstance(invalidation, dict):
        raise PlanningReadinessError("missing-invalidation")
    if invalidation.get("state") != "valid":
        raise PlanningReadinessError("readiness-invalidated")


def recompute_if_stale(
    readiness: Mapping[str, Any],
    map_document: Mapping[str, Any],
    *,
    computed_at: str | None = None,
) -> dict[str, Any]:
    """Return readiness unchanged when fresh, or a newly computed document when stale."""
    try:
        assert_fresh(readiness, map_document)
        return deepcopy(dict(readiness))
    except PlanningReadinessError:
        return compute_readiness(
            map_document,
            readiness_id=str(readiness.get("id") or readiness_id_for_map(str(map_document.get("id")))),
            computed_at=computed_at,
        )


def invalidate_readiness(
    readiness: Mapping[str, Any],
    *,
    current_revision: int,
) -> dict[str, Any]:
    """Mark readiness stale when the exploration map advances (R41)."""
    return invalidate_dependent_output(readiness, current_revision=current_revision)
