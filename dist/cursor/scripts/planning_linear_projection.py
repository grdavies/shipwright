"""PRD 066 phase 5 — Linear operator projection schema (R6, R7, R8, R29).

Maps the portable semantic planning graph onto Linear-native entities for the
operator projection. Projection entities remain rebuildable; portable graph is SoT.
"""

from __future__ import annotations

from typing import Any

# R6 — normative semantic unit → Linear entity mapping.
LINEAR_ENTITY_MAP: dict[str, dict[str, Any]] = {
    "prd": {
        "artifactType": "prd",
        "linearEntity": "Project",
        "notes": "One Project per PRD unit",
        "r1": [1, 2, 3, 4],
    },
    "brainstorm": {
        "artifactType": "brainstorm",
        "linearEntity": "Document",
        "notes": "Attached to the PRD Project",
        "r1": [2],
        "attachTo": "Project",
    },
    "gap": {
        "artifactType": "gap",
        "linearEntity": "Issue",
        "labels": ["Gap"],
        "notes": "Linked into Project when absorbed/assigned",
        "r1": [1],
        "linkInto": "Project",
    },
    "phase": {
        "artifactType": "phase",
        "linearEntity": "Milestone",
        "notes": "Task-list phases → Project Milestones",
        "r1": [3],
        "parent": "Project",
    },
    "task": {
        "artifactType": "task",
        "linearEntity": "Issue",
        "subIssueAllowed": True,
        "milestoneMembership": True,
        "notes": "Assigned to phase Milestone",
        "r1": [3],
    },
    "program": {
        "artifactType": "program",
        "linearEntity": "Initiative",
        "notes": "Cross-PRD program/release grouping (R7)",
        "r1": [4],
        "optionalWhenUnavailable": True,
    },
    "cycle-wave": {
        "artifactType": "cycle-wave",
        "linearEntity": "Cycle",
        "orthogonalTo": "Milestone",
        "notes": "Deliver-wave time-box; does not replace Milestone membership (R8)",
        "r1": [],
        "mutatesCycleDefinition": False,
    },
    "progress": {
        "artifactType": "progress",
        "linearEntity": "status-updates",
        "notes": "Issue/Project/Milestone status (+ comments as required)",
        "r1": [3, 4],
    },
}

# R29 — endpoint-typed edge encoding (no IssueRelation to Project/Document).
EDGE_ENCODINGS: dict[str, dict[str, Any]] = {
    "absorbs": {
        "edgeType": "absorbs",
        "encoding": "project-membership+gap-label",
        "sourceKinds": ("gap", "Issue"),
        "targetKinds": ("prd", "Project"),
        "issueRelationAllowed": False,
        "stubIssueEndpointsProhibited": True,
        "projectionFields": ["projectMembership", "gapLabelOrField", "gapIssueIdentity"],
    },
    "feeds": {
        "edgeType": "feeds",
        "encoding": "document-attachment+project-metadata",
        "sourceKinds": ("brainstorm", "Document"),
        "targetKinds": ("prd", "Project"),
        "issueRelationAllowed": False,
        "stubIssueEndpointsProhibited": True,
        "projectionFields": ["documentAttachmentOrMembership", "brainstormIdentity", "prdProjectLink"],
    },
    "depends": {
        "edgeType": "depends",
        "encoding": "issue-relation",
        "sourceKinds": ("task", "gap", "Issue"),
        "targetKinds": ("task", "gap", "Issue"),
        "issueRelationAllowed": True,
        "stubIssueEndpointsProhibited": True,
        "projectionFields": ["issueRelation"],
    },
}

R1_4_SUBSTITUTE_VIEWS: dict[str, Any] = {
    "id": "team-project-saved-views",
    "description": (
        "When Initiative is unavailable, answer R1(4) via Team/Project saved views "
        "and filters over Project status vocabulary mapped to backlog/in_flight/done"
    ),
    "requiredViews": [
        "program-backlog",
        "program-in-flight",
        "program-done",
    ],
    "programDiscriminator": "project-status-views+team-filter",
    "silentSkipProhibited": True,
}


def linear_entity_mapping() -> dict[str, Any]:
    """R6 — documented Linear operator schema mapping."""
    return {
        "verdict": "ok",
        "action": "linear-entity-mapping",
        "provider": "linear",
        "rows": [dict(row) for row in LINEAR_ENTITY_MAP.values()],
        "byArtifactType": {k: dict(v) for k, v in LINEAR_ENTITY_MAP.items()},
    }


def map_artifact_to_linear_entity(artifact_type: str) -> dict[str, Any]:
    """R6 — resolve a single artifact type to its Linear entity kind."""
    key = (artifact_type or "").strip().lower()
    row = LINEAR_ENTITY_MAP.get(key)
    if row is None:
        return {
            "verdict": "fail",
            "error": "unsupported-artifact-type",
            "artifactType": artifact_type,
        }
    return {"verdict": "ok", "artifactType": key, **dict(row)}


def project_graph_to_linear_layout(graph: dict[str, Any]) -> dict[str, Any]:
    """R6 — project a fixture semantic graph into expected Linear entity layout via facade."""
    if not isinstance(graph, dict) or not graph:
        return {"verdict": "fail", "error": "portable-graph-missing", "action": "project-graph-to-linear-layout"}
    units = list(graph.get("units") or [])
    edges = list(graph.get("edges") or [])
    entities: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        artifact_type = str(unit.get("artifactType") or unit.get("type") or "").strip().lower()
        mapped = map_artifact_to_linear_entity(artifact_type)
        if mapped.get("verdict") != "ok":
            return {**mapped, "action": "project-graph-to-linear-layout", "unit": unit}
        unit_id = str(unit.get("unitId") or unit.get("id") or "")
        entity: dict[str, Any] = {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "linearEntity": mapped["linearEntity"],
            "entityId": unit.get("entityId") or unit.get("providerEntityId"),
            "marker": unit.get("marker"),
            "ownedFields": dict(unit.get("ownedFields") or {}),
        }
        if mapped["linearEntity"] == "Issue" and artifact_type == "gap":
            entity["labels"] = list(mapped.get("labels") or ["Gap"])
            entity["projectMembership"] = unit.get("projectId") or unit.get("prdUnitId")
        if mapped["linearEntity"] == "Document":
            entity["attachedToProject"] = unit.get("prdUnitId") or unit.get("projectId")
        if mapped["linearEntity"] == "Milestone":
            entity["projectId"] = unit.get("prdUnitId") or unit.get("projectId")
        if mapped["linearEntity"] == "Issue" and artifact_type == "task":
            entity["milestoneId"] = unit.get("phaseUnitId") or unit.get("milestoneId")
            entity["cycleId"] = unit.get("cycleId")
        entities.append(entity)

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for ent in entities:
        by_kind.setdefault(str(ent["linearEntity"]), []).append(ent)

    encoded_edges: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        encoded = encode_planning_edge(edge)
        if encoded.get("verdict") != "pass":
            return {**encoded, "action": "project-graph-to-linear-layout"}
        encoded_edges.append(encoded)

    return {
        "verdict": "pass",
        "action": "project-graph-to-linear-layout",
        "provider": "linear",
        "freezeAuthority": "portable-graph",
        "isSourceOfTruth": False,
        "entities": entities,
        "byLinearEntity": by_kind,
        "edges": encoded_edges,
        "counts": {kind: len(rows) for kind, rows in by_kind.items()},
    }


def probe_initiative_availability(
    *,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R7 — init/probe Initiative availability for the Linear workspace."""
    caps = workspace or {}
    available = bool(caps.get("initiativesEnabled") or caps.get("initiativeAvailable"))
    authorized = caps.get("initiativeAuthorized")
    if authorized is None:
        authorized = available
    else:
        authorized = bool(authorized)
    present = available and authorized
    return {
        "verdict": "ok",
        "action": "probe-initiative-availability",
        "available": present,
        "initiativesEnabled": available,
        "initiativeAuthorized": authorized,
        "degraded": not present,
    }


def r1_4_substitute_views() -> dict[str, Any]:
    """R7 — documented minimum R1(4) substitute when Initiative is unavailable."""
    return {
        "verdict": "ok",
        "action": "r1-4-substitute-views",
        **dict(R1_4_SUBSTITUTE_VIEWS),
    }


def apply_initiative_capability(
    matrix: dict[str, Any] | None = None,
    *,
    probe: dict[str, Any] | None = None,
    substitute_configured: bool = True,
) -> dict[str, Any]:
    """R7 — emit matrix degradation + substitute; silent skip prohibited."""
    probe_result = probe or probe_initiative_availability(workspace={"initiativesEnabled": False})
    substitute = r1_4_substitute_views()
    available = bool(probe_result.get("available"))
    notices: list[dict[str, Any]] = []
    if not available:
        if not substitute_configured:
            return {
                "verdict": "fail",
                "error": "initiative-unavailable-without-substitute",
                "action": "apply-initiative-capability",
                "silentSkipProhibited": True,
                "r14Answerable": False,
            }
        notices.append(
            {
                "concept": "initiative",
                "severity": "degraded",
                "missingNative": "Linear Initiative (cross-PRD program grouping)",
                "fallbackBrowsePath": substitute["description"],
                "requiredViews": list(substitute["requiredViews"]),
                "silentSkip": False,
            }
        )
    linear_program = "initiative" if available else "initiative-unavailable+substitute-views"
    return {
        "verdict": "ok",
        "action": "apply-initiative-capability",
        "initiativeAvailable": available,
        "linearProgramRow": linear_program,
        "degradationNotices": notices,
        "substituteViews": substitute if not available else None,
        "r14Answerable": available or substitute_configured,
        "silentSkipProhibited": True,
        "matrix": matrix,
    }


def assert_cycle_orthogonal_to_milestone(
    *,
    issue: dict[str, Any],
    cycle_id: str | None,
    milestone_id: str | None,
) -> dict[str, Any]:
    """R8 — Cycle assignment must not replace Milestone phase membership."""
    assigned_milestone = issue.get("milestoneId") or issue.get("milestone")
    if milestone_id and assigned_milestone and str(assigned_milestone) != str(milestone_id):
        return {
            "verdict": "fail",
            "error": "cycle-replaced-milestone-membership",
            "action": "assert-cycle-orthogonal-to-milestone",
            "milestoneId": milestone_id,
            "issueMilestoneId": assigned_milestone,
        }
    if cycle_id and milestone_id and not assigned_milestone:
        return {
            "verdict": "fail",
            "error": "cycle-assignment-dropped-milestone",
            "action": "assert-cycle-orthogonal-to-milestone",
            "cycleId": cycle_id,
            "milestoneId": milestone_id,
        }
    return {
        "verdict": "pass",
        "action": "assert-cycle-orthogonal-to-milestone",
        "cycleId": cycle_id,
        "milestoneId": milestone_id or assigned_milestone,
        "orthogonal": True,
    }


def assign_issue_to_cycle(
    issue: dict[str, Any],
    *,
    cycle_id: str,
    preserve_milestone: bool = True,
    mutate_cycle_definition: bool = False,
) -> dict[str, Any]:
    """R8 — share via issue assignment into an existing Cycle; no Cycle def mutation."""
    if mutate_cycle_definition:
        return {
            "verdict": "fail",
            "error": "cycle-definition-mutation-prohibited",
            "action": "assign-issue-to-cycle",
            "note": "Shipwright must not rename/reschedule Cycle dates/name",
        }
    if not cycle_id:
        return {"verdict": "fail", "error": "cycle-id-required", "action": "assign-issue-to-cycle"}
    updated = dict(issue)
    prior_milestone = updated.get("milestoneId") or updated.get("milestone")
    updated["cycleId"] = cycle_id
    if preserve_milestone and prior_milestone is not None:
        updated["milestoneId"] = prior_milestone
    check = assert_cycle_orthogonal_to_milestone(
        issue=updated,
        cycle_id=cycle_id,
        milestone_id=str(prior_milestone) if prior_milestone is not None else None,
    )
    if check.get("verdict") != "pass":
        return check
    return {
        "verdict": "pass",
        "action": "assign-issue-to-cycle",
        "issue": updated,
        "mutatedCycleDefinition": False,
        "milestonePreserved": prior_milestone is None or updated.get("milestoneId") == prior_milestone,
    }


def cycle_sharing_notice(*, team_has_active_human_cycle: bool) -> dict[str, Any]:
    """R8 — loud notice when Team already has an active human Cycle cadence."""
    if not team_has_active_human_cycle:
        return {
            "verdict": "ok",
            "action": "cycle-sharing-notice",
            "loud": False,
            "notice": None,
            "sharedCadence": False,
        }
    return {
        "verdict": "ok",
        "action": "cycle-sharing-notice",
        "loud": True,
        "sharedCadence": True,
        "notice": {
            "severity": "warning",
            "code": "shared-cycle-cadence",
            "message": (
                "Team already has an active human Cycle cadence; Shipwright shares via "
                "issue assignment into the existing Cycle and will not mutate Cycle "
                "definition (dates/name). Milestone remains phase SoT."
            ),
            "mutatesCycleDefinition": False,
            "phaseSourceOfTruth": "Milestone",
        },
    }


def _endpoint_kind(endpoint: dict[str, Any] | str | None) -> str:
    if endpoint is None:
        return ""
    if isinstance(endpoint, str):
        return endpoint.strip()
    for key in ("linearEntity", "artifactType", "kind", "type"):
        val = endpoint.get(key)
        if val:
            return str(val).strip()
    return ""


def _is_issue_endpoint(kind: str) -> bool:
    lowered = kind.lower()
    return lowered in {"issue", "task", "gap", "sub-issue", "subissue"}


def _is_project_or_document(kind: str) -> bool:
    lowered = kind.lower()
    return lowered in {"project", "prd", "document", "brainstorm"}


def encode_planning_edge(edge: dict[str, Any]) -> dict[str, Any]:
    """R29 — endpoint-typed encoding for absorbs/feeds; IssueRelation only issue↔issue."""
    edge_type = str(edge.get("type") or edge.get("edgeType") or edge.get("rel") or "").strip().lower()
    source = edge.get("source") if isinstance(edge.get("source"), dict) else {
        "artifactType": edge.get("sourceType") or edge.get("fromType"),
        "unitId": edge.get("sourceId") or edge.get("from"),
        "linearEntity": edge.get("sourceEntity"),
    }
    target = edge.get("target") if isinstance(edge.get("target"), dict) else {
        "artifactType": edge.get("targetType") or edge.get("toType"),
        "unitId": edge.get("targetId") or edge.get("to"),
        "linearEntity": edge.get("targetEntity"),
    }
    source_kind = _endpoint_kind(source)
    target_kind = _endpoint_kind(target)

    if edge.get("stubIssueEndpoints") is True:
        return {
            "verdict": "fail",
            "error": "stub-issue-endpoints-prohibited",
            "action": "encode-planning-edge",
            "edgeType": edge_type,
        }

    if edge_type in EDGE_ENCODINGS:
        spec = EDGE_ENCODINGS[edge_type]
    elif _is_issue_endpoint(source_kind) and _is_issue_endpoint(target_kind):
        spec = EDGE_ENCODINGS["depends"]
        edge_type = edge_type or "depends"
    else:
        return {
            "verdict": "fail",
            "error": "unsupported-edge-type",
            "action": "encode-planning-edge",
            "edgeType": edge_type,
        }

    wants_issue_relation = bool(edge.get("issueRelation")) or (
        edge.get("encoding") == "issue-relation"
    )
    if wants_issue_relation or edge.get("useIssueRelation") is True:
        if _is_project_or_document(source_kind) or _is_project_or_document(target_kind):
            return {
                "verdict": "fail",
                "error": "issue-relation-to-project-or-document",
                "action": "encode-planning-edge",
                "edgeType": edge_type,
                "sourceKind": source_kind,
                "targetKind": target_kind,
            }

    if edge_type == "absorbs" and source_kind.lower() not in {"gap", "issue"}:
        return {
            "verdict": "fail",
            "error": "absorbs-requires-gap-issue-source",
            "action": "encode-planning-edge",
        }
    if edge_type == "feeds" and source_kind.lower() not in {"brainstorm", "document"}:
        return {
            "verdict": "fail",
            "error": "feeds-requires-document-source",
            "action": "encode-planning-edge",
        }

    encoding = str(spec["encoding"])
    if edge_type in {"absorbs", "feeds"}:
        issue_relation = False
    else:
        issue_relation = bool(spec.get("issueRelationAllowed")) and _is_issue_endpoint(
            source_kind
        ) and _is_issue_endpoint(target_kind)

    return {
        "verdict": "pass",
        "action": "encode-planning-edge",
        "edgeType": edge_type,
        "encoding": encoding,
        "issueRelation": issue_relation,
        "source": {
            "kind": source_kind,
            "unitId": (source or {}).get("unitId") if isinstance(source, dict) else None,
        },
        "target": {
            "kind": target_kind,
            "unitId": (target or {}).get("unitId") if isinstance(target, dict) else None,
        },
        "projectionFields": list(spec.get("projectionFields") or []),
        "stubIssueEndpoints": False,
    }


def linear_projection_schema_contract() -> dict[str, Any]:
    """Facade summary for R6–R8/R29 Linear operator schema."""
    return {
        "verdict": "ok",
        "action": "linear-projection-schema-contract",
        "entityMapping": linear_entity_mapping(),
        "edgeEncodings": {k: dict(v) for k, v in EDGE_ENCODINGS.items()},
        "r14SubstituteViews": r1_4_substitute_views(),
        "cycleOrthogonality": {
            "orthogonalTo": "Milestone",
            "mutatesCycleDefinition": False,
            "sharePath": "issue-assignment",
        },
    }
