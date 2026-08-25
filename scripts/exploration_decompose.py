#!/usr/bin/env python3
"""Derive bounded planning-unit candidates only — never create PRDs or tasks (PRD 331 D4, R20, R31)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from planning_readiness import PlanningReadinessError, assert_fresh, compute_readiness, refuse_invalidated

AUTHORITY_BOUNDARY: dict[str, bool] = {
    "createsPrds": False,
    "createsTasks": False,
    "dispatchesImplementation": False,
}

FORBIDDEN_WRITE_PREFIXES = (
    "docs/prds/",
    "docs/planning/",
)

FORBIDDEN_WRITE_NAMES = frozenset(
    {
        "tasks-",
        "prd-",
        "PRD",
        "branch",
        "implementation",
    }
)


class ExplorationDecomposeError(ValueError):
    """Invalid planning-unit candidate derivation."""


class PlanningWriteForbiddenError(ExplorationDecomposeError):
    """Authority boundary violation — planning artifacts must not be created (R20, R31)."""


def assert_no_planning_writes(target_path: str) -> None:
    """Guard against accidental PRD/task/branch/implementation writes (R20, R31)."""
    normalized = target_path.replace("\\", "/").strip().lower()
    for prefix in FORBIDDEN_WRITE_PREFIXES:
        if normalized.startswith(prefix) or f"/{prefix}" in normalized:
            raise PlanningWriteForbiddenError(f"forbidden-planning-write:{target_path}")
    leaf = normalized.rsplit("/", 1)[-1]
    for token in FORBIDDEN_WRITE_NAMES:
        if token.lower() in leaf:
            raise PlanningWriteForbiddenError(f"forbidden-planning-write:{target_path}")


def _hint_candidates(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    structured = map_document.get("structuredFields")
    if not isinstance(structured, dict):
        return []
    hints = structured.get("planningUnitCandidates")
    if not isinstance(hints, list):
        return []
    collected: list[dict[str, Any]] = []
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        candidate_id = str(hint.get("id") or "").strip()
        title = str(hint.get("title") or "").strip()
        if not candidate_id or not title:
            continue
        rationale = str(hint.get("rationale") or f"Structured hint for {title}.").strip()
        candidate: dict[str, Any] = {
            "id": candidate_id,
            "title": title,
            "rationale": rationale,
        }
        dependencies = hint.get("dependencies")
        if isinstance(dependencies, list):
            deps = [str(item).strip() for item in dependencies if str(item).strip()]
            if deps:
                candidate["dependencies"] = sorted(deps)
        collected.append(candidate)
    return collected


def _approach_candidates(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    structured = map_document.get("structuredFields")
    if not isinstance(structured, dict):
        return []
    approaches = structured.get("candidateApproaches")
    if not isinstance(approaches, list):
        return []
    collected: list[dict[str, Any]] = []
    for index, approach in enumerate(approaches, start=1):
        title = str(approach).strip()
        if not title:
            continue
        slug = title.lower().replace(" ", "-")
        slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in slug).strip("-")
        candidate_id = f"approach-{index}" if not slug else f"approach-{slug[:40]}"
        collected.append(
            {
                "id": candidate_id,
                "title": title,
                "rationale": "Derived from structured candidateApproaches field.",
            }
        )
    return collected


def _discovery_candidates(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for node in map_document.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "discovery" or node.get("status") not in {"open", "resolved"}:
            continue
        node_id = str(node.get("id") or "").strip()
        statement = str(node.get("statement") or node.get("title") or "").strip()
        if not node_id or not statement:
            continue
        candidate: dict[str, Any] = {
            "id": f"discovery-{node_id}",
            "title": statement[:120],
            "rationale": f"Discovery node {node_id} suggests a bounded planning unit.",
        }
        linked = node.get("linkedNodeIds")
        if isinstance(linked, list):
            deps = [str(item).strip() for item in linked if str(item).strip()]
            if deps:
                candidate["dependencies"] = sorted(deps)
        collected.append(candidate)
    return collected


def derive_candidates(map_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic, sorted planning-unit candidates without planning writes (R20)."""
    merged: dict[str, dict[str, Any]] = {}
    for candidate in _hint_candidates(map_document) + _approach_candidates(map_document) + _discovery_candidates(
        map_document
    ):
        merged[candidate["id"]] = candidate
    return [deepcopy(merged[key]) for key in sorted(merged)]


def decompose(
    map_document: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive readiness plus candidate units; never mutates planning artifacts (D4, R31)."""
    live_readiness = readiness or compute_readiness(map_document)
    if readiness is not None:
        refuse_invalidated(live_readiness)
        assert_fresh(live_readiness, map_document)
    candidates = derive_candidates(map_document)
    return {
        "explorationMapId": str(map_document.get("id") or ""),
        "sourceRevision": int(map_document.get("revision", 1)),
        "readiness": deepcopy(dict(live_readiness)),
        "planningUnitCandidates": candidates,
        "authorityBoundary": deepcopy(AUTHORITY_BOUNDARY),
    }


def decomposition_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    boundary = result.get("authorityBoundary") or {}
    return {
        "candidateCount": len(result.get("planningUnitCandidates") or []),
        "readyForDocHandoff": bool((result.get("readiness") or {}).get("readyForDocHandoff")),
        "authorityBoundary": boundary,
    }
