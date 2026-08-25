#!/usr/bin/env python3
"""Exploration supersession and dependent-output invalidation (PRD 331 R13, R41)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from exploration_store import utc_now


class ExplorationModelError(ValueError):
    """Invalid exploration model transition."""


def invalidate_dependent_output(
    output: Mapping[str, Any],
    *,
    current_revision: int,
) -> dict[str, Any]:
    """Mark readiness/brief stale when source revision lags the live map (R41)."""
    source_revision = output.get("sourceRevision")
    if not isinstance(source_revision, int):
        raise ExplorationModelError("invalid-source-revision")
    updated = deepcopy(dict(output))
    if source_revision >= current_revision:
        return updated
    invalidation = dict(updated.get("invalidation") or {})
    invalidation.update(
        {
            "state": "stale",
            "reason": f"ExplorationMap advanced to revision {current_revision}",
            "invalidatedAt": utc_now(),
            "supersededByRevision": current_revision,
        }
    )
    updated["invalidation"] = invalidation
    if "readyForDocHandoff" in updated:
        updated["readyForDocHandoff"] = False
    readiness = updated.get("readiness")
    if isinstance(readiness, dict) and "readyForDocHandoff" in readiness:
        readiness["readyForDocHandoff"] = False
    return updated


def invalidate_dependent_outputs(
    map_document: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
    brief: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    revision = int(map_document.get("revision", 1))
    result: dict[str, Any] = {"revision": revision}
    if readiness is not None:
        result["readiness"] = invalidate_dependent_output(readiness, current_revision=revision)
    if brief is not None:
        result["brief"] = invalidate_dependent_output(brief, current_revision=revision)
    return result


def supersede_decision(
    map_document: Mapping[str, Any],
    *,
    decision_id: str,
    successor: Mapping[str, Any],
    at: str | None = None,
) -> dict[str, Any]:
    """Retain superseded decision provenance and bump map revision (R13)."""
    nodes = [deepcopy(node) for node in map_document.get("nodes") or [] if isinstance(node, dict)]
    found = False
    for node in nodes:
        if node.get("id") == decision_id and node.get("type") == "decision":
            node["status"] = "superseded"
            found = True
            break
    if not found:
        raise ExplorationModelError("decision-not-found")
    successor_node = deepcopy(dict(successor))
    successor_node.setdefault("type", "decision")
    successor_node.setdefault("supersedes", decision_id)
    if "status" not in successor_node:
        successor_node["status"] = "open"
    nodes.append(successor_node)
    superseded_ids = list(map_document.get("supersededNodeIds") or [])
    if decision_id not in superseded_ids:
        superseded_ids.append(decision_id)
    updated = deepcopy(dict(map_document))
    updated["nodes"] = nodes
    updated["supersededNodeIds"] = superseded_ids
    updated["revision"] = int(map_document.get("revision", 1)) + 1
    provenance = updated.get("provenance")
    if isinstance(provenance, dict):
        provenance["updatedAt"] = at or utc_now()
    return updated


def apply_supersession_invalidation(
    map_document: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
    brief: Mapping[str, Any] | None = None,
    decision_id: str,
    successor: Mapping[str, Any],
) -> dict[str, Any]:
    """Supersede a decision and invalidate dependent outputs in one step."""
    updated_map = supersede_decision(
        map_document,
        decision_id=decision_id,
        successor=successor,
    )
    outputs = invalidate_dependent_outputs(
        updated_map,
        readiness=readiness,
        brief=brief,
    )
    outputs["map"] = updated_map
    return outputs
