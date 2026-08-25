#!/usr/bin/env python3
"""Emit revision-bound ExplorationBrief@v1 handoff output (PRD 331 R14, R27, R41)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from exploration_decompose import AUTHORITY_BOUNDARY, decompose
from exploration_model import invalidate_dependent_output
from planning_readiness import (
    PlanningReadinessError,
    assert_fresh as assert_readiness_fresh,
    collect_unknowns,
    compute_readiness,
    readiness_id_for_map,
    refuse_invalidated,
)
from exploration_store import utc_now

BRIEF_VERSION = "ExplorationBrief@v1"


class ExplorationBriefError(ValueError):
    """Invalid or stale exploration brief derivation."""


def brief_id_for_map(map_id: str) -> str:
    return f"brief-{map_id}"


def collect_decision_summaries(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for node in map_document.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "decision":
            continue
        node_id = str(node.get("id") or "").strip()
        title = str(node.get("title") or node.get("statement") or "").strip()
        status = str(node.get("status") or "open").strip()
        if not node_id or not title:
            continue
        entry: dict[str, Any] = {"nodeId": node_id, "title": title, "status": status}
        resolution = node.get("resolution")
        if isinstance(resolution, str) and resolution.strip():
            entry["resolution"] = resolution.strip()
        collected.append(entry)
    return sorted(collected, key=lambda item: item["nodeId"])


def collect_evidence_summaries(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for node in map_document.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "evidence":
            continue
        ref = node.get("evidenceRef")
        if not isinstance(ref, dict):
            continue
        ref_id = str(ref.get("refId") or "").strip()
        kind = str(ref.get("kind") or "").strip()
        if not ref_id or kind not in {"ResearchEvidence", "PrototypeEvidence"}:
            continue
        entry: dict[str, Any] = {"refId": ref_id, "kind": kind}
        claim = node.get("statement") or node.get("title")
        if isinstance(claim, str) and claim.strip():
            entry["claim"] = claim.strip()
        trust = ref.get("trust")
        if isinstance(trust, str) and trust in {"trusted", "untrusted"}:
            entry["trust"] = trust
        collected.append(entry)
    return sorted(collected, key=lambda item: (item["kind"], item["refId"]))


def collect_remaining_uncertainty(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "statement": item["statement"],
            "classification": item["classification"],
        }
        for item in collect_unknowns(map_document)
    ]


def emit_brief(
    map_document: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
    decomposition: Mapping[str, Any] | None = None,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    """Derive an ExplorationBrief@v1 document bound to the live map revision (R14, R27, R41)."""
    map_id = str(map_document.get("id") or "").strip()
    if not map_id:
        raise ExplorationBriefError("missing-map-id")
    revision = map_document.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ExplorationBriefError("invalid-map-revision")
    destination = map_document.get("destination")
    if not isinstance(destination, dict) or not str(destination.get("statement") or "").strip():
        raise ExplorationBriefError("missing-destination")

    derived = decomposition or decompose(map_document, readiness=readiness)
    live_readiness = derived["readiness"]
    if readiness is not None:
        refuse_invalidated(live_readiness)
        assert_readiness_fresh(live_readiness, map_document)

    brief: dict[str, Any] = {
        "id": brief_id_for_map(map_id),
        "version": BRIEF_VERSION,
        "sourceRevision": revision,
        "explorationMapId": map_id,
        "destination": {"statement": str(destination["statement"]).strip()},
        "readiness": {
            "readinessId": str(live_readiness.get("id") or readiness_id_for_map(map_id)),
            "readyForDocHandoff": bool(live_readiness.get("readyForDocHandoff")),
        },
        "planningUnitCandidates": deepcopy(list(derived.get("planningUnitCandidates") or [])),
        "invalidation": {"state": "valid"},
        "emittedAt": emitted_at or utc_now(),
        "authorityBoundary": deepcopy(AUTHORITY_BOUNDARY),
    }
    decisions = collect_decision_summaries(map_document)
    if decisions:
        brief["decisions"] = decisions
    evidence = collect_evidence_summaries(map_document)
    if evidence:
        brief["evidence"] = evidence
    uncertainty = collect_remaining_uncertainty(map_document)
    if uncertainty:
        brief["remainingUncertainty"] = uncertainty
    return brief


def assert_fresh(brief: Mapping[str, Any], map_document: Mapping[str, Any]) -> None:
    """Fail closed when the brief does not match the live map revision (R41)."""
    invalidation = brief.get("invalidation")
    if isinstance(invalidation, dict) and invalidation.get("state") != "valid":
        raise ExplorationBriefError("brief-invalidated")
    source_revision = brief.get("sourceRevision")
    live_revision = map_document.get("revision")
    if not isinstance(source_revision, int) or not isinstance(live_revision, int):
        raise ExplorationBriefError("invalid-revision")
    if source_revision != live_revision:
        raise ExplorationBriefError("stale-brief")
    if str(brief.get("explorationMapId") or "") != str(map_document.get("id") or ""):
        raise ExplorationBriefError("map-id-mismatch")


def invalidate_brief(brief: Mapping[str, Any], *, current_revision: int) -> dict[str, Any]:
    """Mark a brief stale when the exploration map advances (R41)."""
    return invalidate_dependent_output(brief, current_revision=current_revision)


def recompute_if_stale(
    brief: Mapping[str, Any],
    map_document: Mapping[str, Any],
    *,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    """Return the brief unchanged when fresh, or a newly emitted document when stale."""
    try:
        assert_fresh(brief, map_document)
        return deepcopy(dict(brief))
    except ExplorationBriefError:
        return emit_brief(map_document, emitted_at=emitted_at)
