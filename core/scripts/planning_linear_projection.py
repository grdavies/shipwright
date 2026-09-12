"""PRD 066 — Linear operator projection schema (R6, R7, R8, R29) + dual-write body (R26).

Maps the portable semantic planning graph onto Linear-native entities for the
operator projection. Projection entities remain rebuildable; portable graph is SoT.

R26: when Linear is both LCD issue-store and operator projection, freeze/hash
authority lives on the LCD Issue (or explicit Document-backed) body path —
never on Project/Document/Milestone/Initiative/Cycle projection mirrors.
"""

from __future__ import annotations

import hashlib
from typing import Any

# R26 — freeze/hash SoT body sources (facade get/freeze resolution).
CANONICAL_BODY_SOURCES = frozenset({"lcd-issue", "document-backed"})

# R26 — rebuildable projection mirrors; never freeze/hash authority.
PROJECTION_MIRROR_KINDS = frozenset(
    {
        "Project",
        "Document",
        "Milestone",
        "Initiative",
        "Cycle",
        "project",
        "document",
        "milestone",
        "initiative",
        "cycle",
    }
)

DOCUMENT_BACKED_LABEL = "sw:document-backed"
DOCUMENT_BACKED_MARKER = "<!-- sw-document-backed -->"

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
    """Facade summary for R6–R8/R29 Linear operator schema + R26 dual-write policy."""
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
        "dualWriteBody": dual_write_body_policy(),
    }


def _body_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def normalize_body_source(raw: str | None) -> str:
    """Normalize caller bodySource to lcd-issue | document-backed | projection-*."""
    if not raw:
        return "lcd-issue"
    value = str(raw).strip().lower().replace("_", "-")
    aliases = {
        "issue": "lcd-issue",
        "lcd": "lcd-issue",
        "lcd-issue": "lcd-issue",
        "document-backed": "document-backed",
        "document_backed": "document-backed",
        "doc-backed": "document-backed",
        "projection": "projection-mirror",
        "projection-mirror": "projection-mirror",
        "prefer-projection": "projection-prefer",
        "projection-prefer": "projection-prefer",
    }
    if value in aliases:
        return aliases[value]
    if value in {k.lower() for k in PROJECTION_MIRROR_KINDS}:
        return f"projection-{value}"
    return value


def is_projection_mirror_kind(kind: str | None) -> bool:
    if not kind:
        return False
    return str(kind).strip() in PROJECTION_MIRROR_KINDS


def dual_write_body_policy() -> dict[str, Any]:
    """R26 — normative dual-write / freeze SoT policy surface."""
    return {
        "canonicalBodySources": sorted(CANONICAL_BODY_SOURCES),
        "projectionMirrorKinds": sorted(
            {k for k in PROJECTION_MIRROR_KINDS if k[:1].isupper()}
        ),
        "freezeAuthority": "lcd-issue-or-document-backed",
        "projectionMayMirrorBrowsableContent": True,
        "projectionIsFreezeAuthority": False,
        "unresolvedCanonicalBody": "fail-closed",
        "projectionPreferSplitBrain": "fail-closed",
        "projectionBodyDivergence": "typed-drift",
        "documentBackedLabel": DOCUMENT_BACKED_LABEL,
        "documentBackedMarker": DOCUMENT_BACKED_MARKER,
    }


def infer_canonical_body_source(
    *,
    body_source: str | None = None,
    labels: list[str] | None = None,
    body: str | None = None,
    document_backed: bool | None = None,
) -> str:
    """Infer lcd-issue vs document-backed from explicit flags, labels, or markers."""
    if document_backed is True:
        return "document-backed"
    if body_source:
        return normalize_body_source(body_source)
    label_set = {str(x) for x in (labels or [])}
    if DOCUMENT_BACKED_LABEL in label_set:
        return "document-backed"
    if body and DOCUMENT_BACKED_MARKER in body:
        return "document-backed"
    return "lcd-issue"


def assert_projection_mirrors_not_freeze_authority(
    projection_mirrors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """R26 — Project/Document/Milestone/Initiative/Cycle never become freeze SoT."""
    mirrors = list(projection_mirrors or [])
    for mirror in mirrors:
        if not isinstance(mirror, dict):
            continue
        if mirror.get("isFreezeAuthority") is True or mirror.get("isSourceOfTruth") is True:
            return {
                "verdict": "fail",
                "error": "projection-claimed-freeze-authority",
                "action": "assert-projection-mirrors-not-freeze-authority",
                "entityKind": mirror.get("entityKind") or mirror.get("kind"),
                "entityId": mirror.get("entityId") or mirror.get("id"),
            }
        kind = str(mirror.get("entityKind") or mirror.get("kind") or "")
        if is_projection_mirror_kind(kind) and mirror.get("freezeAuthority") not in (
            None,
            False,
            "derived",
            "portable-graph",
        ):
            return {
                "verdict": "fail",
                "error": "projection-claimed-freeze-authority",
                "action": "assert-projection-mirrors-not-freeze-authority",
                "entityKind": kind,
                "entityId": mirror.get("entityId") or mirror.get("id"),
            }
    return {
        "verdict": "pass",
        "action": "assert-projection-mirrors-not-freeze-authority",
        "mirrorCount": len(mirrors),
        "freezeAuthority": "lcd-issue-or-document-backed",
    }


def check_canonical_projection_split_brain(
    *,
    canonical_body: str,
    projection_mirrors: list[dict[str, Any]] | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """R26 — fail closed on projection-prefer; typed drift when mirror body diverges."""
    prefer_norm = normalize_body_source(prefer) if prefer else None
    if prefer_norm in {"projection-prefer", "projection-mirror"} or (
        prefer_norm and prefer_norm.startswith("projection-")
    ):
        return {
            "verdict": "fail",
            "error": "projection-prefer-split-brain",
            "action": "check-canonical-projection-split-brain",
            "prefer": prefer,
        }

    authority = assert_projection_mirrors_not_freeze_authority(projection_mirrors)
    if authority["verdict"] != "pass":
        return {**authority, "action": "check-canonical-projection-split-brain"}

    canonical_digest = _body_digest(canonical_body)
    drifted: list[dict[str, Any]] = []
    for mirror in projection_mirrors or []:
        if not isinstance(mirror, dict):
            continue
        mirror_body = mirror.get("body")
        if mirror_body is None:
            continue
        if not isinstance(mirror_body, str):
            drifted.append(
                {
                    "entityKind": mirror.get("entityKind") or mirror.get("kind"),
                    "entityId": mirror.get("entityId") or mirror.get("id"),
                    "error": "projection-body-type-invalid",
                }
            )
            continue
        # Dual-write may store a derived browsable summary; only exact body
        # mirrors that claim parity (or omit derived=True) are drift-checked.
        if mirror.get("derived") is True and mirror.get("bodyParityRequired") is not True:
            continue
        if _body_digest(mirror_body) != canonical_digest:
            drifted.append(
                {
                    "entityKind": mirror.get("entityKind") or mirror.get("kind"),
                    "entityId": mirror.get("entityId") or mirror.get("id"),
                    "error": "canonical-projection-body-drift",
                    "canonicalDigest": canonical_digest,
                    "projectionDigest": _body_digest(mirror_body),
                }
            )
    if drifted:
        return {
            "verdict": "fail",
            "error": "canonical-projection-body-drift",
            "action": "check-canonical-projection-split-brain",
            "drift": drifted,
            "typedDrift": True,
        }
    return {
        "verdict": "pass",
        "action": "check-canonical-projection-split-brain",
        "canonicalDigest": canonical_digest,
        "typedDrift": False,
    }


def resolve_canonical_freeze_body(
    *,
    unit_id: str,
    body_path: str | None = None,
    body: str | None = None,
    body_source: str | None = None,
    labels: list[str] | None = None,
    document_backed: bool | None = None,
    projection_mirrors: list[dict[str, Any]] | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """R26 — resolve freeze/hash SoT body; projection mirrors never win."""
    action = "resolve-canonical-freeze-body"
    if not unit_id:
        return {
            "verdict": "fail",
            "error": "canonical-body-unresolved",
            "action": action,
            "reason": "missing-unit-id",
        }

    source = infer_canonical_body_source(
        body_source=body_source,
        labels=labels,
        body=body,
        document_backed=document_backed,
    )
    prefer_norm = normalize_body_source(prefer) if prefer else None
    if prefer_norm in {"projection-prefer", "projection-mirror"} or (
        prefer_norm and prefer_norm.startswith("projection-")
    ):
        return {
            "verdict": "fail",
            "error": "projection-prefer-split-brain",
            "action": action,
            "prefer": prefer,
            "bodySource": source,
        }

    if source not in CANONICAL_BODY_SOURCES:
        return {
            "verdict": "fail",
            "error": "projection-claimed-freeze-authority",
            "action": action,
            "bodySource": source,
        }

    if body is None or (isinstance(body, str) and body.strip() == ""):
        return {
            "verdict": "fail",
            "error": "canonical-body-unresolved",
            "action": action,
            "bodySource": source,
            "unitId": unit_id,
            "bodyPath": body_path,
        }

    split = check_canonical_projection_split_brain(
        canonical_body=body,
        projection_mirrors=projection_mirrors,
        prefer=prefer,
    )
    if split["verdict"] != "pass":
        return {**split, "action": action, "bodySource": source, "unitId": unit_id}

    digest = _body_digest(body)
    return {
        "verdict": "pass",
        "action": action,
        "unitId": unit_id,
        "bodyPath": body_path,
        "bodySource": source,
        "body": body,
        "hash": digest,
        "freezeAuthority": source,
        "projectionRebuildable": True,
    }


def freeze_from_canonical_body(
    *,
    unit_id: str,
    body_path: str | None = None,
    body: str | None = None,
    body_source: str | None = None,
    labels: list[str] | None = None,
    document_backed: bool | None = None,
    projection_mirrors: list[dict[str, Any]] | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """R26 — freeze/hash only after canonical body resolves; fail closed otherwise."""
    resolved = resolve_canonical_freeze_body(
        unit_id=unit_id,
        body_path=body_path,
        body=body,
        body_source=body_source,
        labels=labels,
        document_backed=document_backed,
        projection_mirrors=projection_mirrors,
        prefer=prefer,
    )
    if resolved.get("verdict") != "pass":
        return {
            **resolved,
            "action": "freeze-from-canonical-body",
            "frozen": False,
        }
    return {
        "verdict": "pass",
        "action": "freeze-from-canonical-body",
        "unitId": unit_id,
        "bodyPath": body_path,
        "bodySource": resolved["bodySource"],
        "hash": resolved["hash"],
        "frozen": True,
        "freezeAuthority": resolved["freezeAuthority"],
        "locked": True,
    }


def dual_write_projection_mirror(
    *,
    canonical_body: str,
    entity_kind: str,
    entity_id: str,
    mirror_body: str | None = None,
    derived_summary: str | None = None,
) -> dict[str, Any]:
    """R26 — allow browsable projection mirrors derived from canonical body only."""
    if not is_projection_mirror_kind(entity_kind):
        return {
            "verdict": "fail",
            "error": "unsupported-projection-mirror-kind",
            "entityKind": entity_kind,
        }
    if mirror_body is not None and _body_digest(mirror_body) != _body_digest(canonical_body):
        if derived_summary is None:
            return {
                "verdict": "fail",
                "error": "canonical-projection-body-drift",
                "typedDrift": True,
                "entityKind": entity_kind,
                "entityId": entity_id,
            }
    mirror: dict[str, Any] = {
        "entityKind": entity_kind,
        "entityId": entity_id,
        "isFreezeAuthority": False,
        "isSourceOfTruth": False,
        "freezeAuthority": "derived",
        "derived": True,
        "canonicalDigest": _body_digest(canonical_body),
    }
    if mirror_body is not None and _body_digest(mirror_body) == _body_digest(canonical_body):
        mirror["body"] = mirror_body
        mirror["bodyParityRequired"] = True
        mirror["derived"] = False
    if derived_summary is not None:
        mirror["summary"] = derived_summary
        mirror["derived"] = True
    return {
        "verdict": "pass",
        "action": "dual-write-projection-mirror",
        "mirror": mirror,
    }


UNIT_MARKER_PREFIX = "sw:unit:"
GAP_LABEL = "Gap"
TASK_LABEL = "Task"
_PROJECTION_ARTIFACT_ORDER = ("prd", "brainstorm", "gap", "phase", "task")
LINEAR_HIERARCHY_REBUILD_STEPS = ("prd-brainstorm-gap", "phases", "tasks", "tombstone")


def unit_projection_marker(unit_id: str) -> str:
    """Stable unit-id marker embedded on rebuildable Linear projection entities."""
    return f"{UNIT_MARKER_PREFIX}{unit_id}"


def _record_str(record: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _record_list(record: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            if "," in value:
                return [part.strip() for part in value.split(",") if part.strip()]
            return [value.strip()]
    return []


def _requirements_summary(content: str) -> str:
    body = (content or "").strip()
    if not body:
        return ""
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:280]
    return body[:280]


def semantic_owned_fields(record: dict[str, Any], *, project_key: str = "") -> dict[str, Any]:
    """Derive projection-owned fields from a semantic-store record (SoT)."""
    artifact_type = _record_str(record, "artifactType", "type").lower()
    unit_id = _record_str(record, "unitId", "id")
    title = _record_str(record, "title")
    content = _record_str(record, "content", "body")
    status = _record_str(record, "status", "state", default="proposed")
    if not title and content:
        for line in content.splitlines():
            if line.strip().startswith("#"):
                title = line.strip().lstrip("#").strip()
                break
    if not title:
        title = unit_id
    owned: dict[str, Any] = {
        "title": title,
        "status": status,
        "marker": unit_projection_marker(unit_id),
    }
    if project_key:
        owned["projectKey"] = project_key
    if artifact_type == "prd":
        owned["requirementsSummary"] = _record_str(record, "requirementsSummary") or _requirements_summary(
            content
        )
        owned["links"] = _record_list(record, "links", "native_links", "nativeLinks")
    elif artifact_type == "brainstorm":
        owned["summary"] = _record_str(record, "summary") or _requirements_summary(content)
        owned["prdUnitId"] = _record_str(record, "prdUnitId", "projectId", "parentUnitId")
    elif artifact_type == "gap":
        owned["lifecycle"] = _record_str(record, "lifecycle", "gapStatus", default=status)
        owned["prerequisites"] = _record_list(record, "prerequisites", "depends", "prerequisite")
        owned["absorbs"] = _record_list(record, "absorbs", "absorbedBy", "absorption")
        owned["prdUnitId"] = _record_str(record, "prdUnitId", "projectId", "parentUnitId")
        owned["labels"] = sorted(
            set(_record_list(record, "labels") or [GAP_LABEL, f"sw:gap", f"sw:unit:{unit_id}"])
        )
    elif artifact_type == "phase":
        owned["phaseId"] = _record_str(record, "phaseId", "id", default=unit_id)
        owned["dependsOn"] = _record_list(record, "dependsOn", "depends", "prerequisite")
        owned["deliveryStatus"] = _record_str(
            record, "deliveryStatus", "completionStatus", "status", default=status
        )
        owned["sortOrder"] = record.get("sortOrder")
        owned["prdUnitId"] = _record_str(record, "prdUnitId", "projectId", "parentUnitId")
    elif artifact_type == "task":
        owned["taskRef"] = _record_str(record, "taskRef", "ref", default=unit_id)
        owned["phaseUnitId"] = _record_str(record, "phaseUnitId", "phaseId", "milestoneId")
        owned["parentTaskUnitId"] = _record_str(record, "parentTaskUnitId", "parentUnitId")
        owned["rIds"] = _record_list(record, "rIds", "requirements", "r_ids")
        owned["scenarios"] = _record_list(record, "scenarios", "testScenarios")
        owned["completionStatus"] = _record_str(
            record, "completionStatus", "checkboxStatus", "status", default=status
        )
        owned["labels"] = sorted(
            set(_record_list(record, "labels") or [TASK_LABEL, f"sw:task:{owned['taskRef']}"])
        )
    return owned


def _phase_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    phase_id = _record_str(record, "phaseId", "id")
    digits = "".join(ch for ch in phase_id if ch.isdigit())
    order = int(digits) if digits else 999
    return (order, _record_str(record, "unitId", "id"))


def _sort_phases_by_dependency(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Topological sort on phase dependsOn with numeric phase-id fallback."""
    by_phase_id: dict[str, dict[str, Any]] = {}
    by_unit: dict[str, dict[str, Any]] = {}
    for phase in phases:
        unit_id = _record_str(phase, "unitId", "id")
        phase_id = _record_str(phase, "phaseId", "id", default=unit_id)
        by_phase_id[phase_id] = phase
        by_unit[unit_id] = phase

    ordered: list[dict[str, Any]] = []
    visited: set[str] = set()

    def visit(phase: dict[str, Any]) -> None:
        unit_id = _record_str(phase, "unitId", "id")
        if unit_id in visited:
            return
        for dep in _record_list(phase, "dependsOn", "depends", "prerequisite"):
            parent = by_phase_id.get(dep) or by_unit.get(dep)
            if parent is not None:
                visit(parent)
        visited.add(unit_id)
        ordered.append(phase)

    for phase in sorted(phases, key=_phase_sort_key):
        visit(phase)
    return ordered


def build_prd_project_spec(
    record: dict[str, Any],
    *,
    project_key: str,
) -> dict[str, Any]:
    """R33 — semantic PRD record → deterministic Linear Project projection."""
    artifact_type = _record_str(record, "artifactType", "type").lower()
    if artifact_type != "prd":
        return {
            "verdict": "fail",
            "error": "unsupported-artifact-type",
            "action": "build-prd-project-spec",
            "artifactType": artifact_type,
        }
    unit_id = _record_str(record, "unitId", "id")
    owned = semantic_owned_fields(record, project_key=project_key)
    prefix = f"[{project_key}] " if project_key else ""
    title = owned["title"]
    if prefix and not title.startswith(prefix):
        title = f"{prefix}{title}"
    owned["title"] = title
    return {
        "verdict": "pass",
        "action": "build-prd-project-spec",
        "linearEntity": "Project",
        "unitId": unit_id,
        "artifactType": "prd",
        "marker": unit_projection_marker(unit_id),
        "ownedFields": owned,
        "isFreezeAuthority": False,
        "isSourceOfTruth": False,
        "freezeAuthority": "portable-graph",
    }


def build_brainstorm_document_spec(
    record: dict[str, Any],
    *,
    project_key: str,
    prd_project_entity_id: str | None = None,
) -> dict[str, Any]:
    """R33 — semantic brainstorm record → linked Linear Document (projection only)."""
    artifact_type = _record_str(record, "artifactType", "type").lower()
    if artifact_type != "brainstorm":
        return {
            "verdict": "fail",
            "error": "unsupported-artifact-type",
            "action": "build-brainstorm-document-spec",
            "artifactType": artifact_type,
        }
    unit_id = _record_str(record, "unitId", "id")
    owned = semantic_owned_fields(record, project_key=project_key)
    return {
        "verdict": "pass",
        "action": "build-brainstorm-document-spec",
        "linearEntity": "Document",
        "unitId": unit_id,
        "artifactType": "brainstorm",
        "marker": unit_projection_marker(unit_id),
        "attachedToProject": prd_project_entity_id or record.get("prdProjectEntityId"),
        "ownedFields": owned,
        "isFreezeAuthority": False,
        "isSourceOfTruth": False,
        "freezeAuthority": "portable-graph",
    }


def build_gap_issue_spec(
    record: dict[str, Any],
    *,
    project_key: str,
    prd_project_entity_id: str | None = None,
) -> dict[str, Any]:
    """R33 — semantic gap record → searchable Linear Issue with lifecycle + links."""
    artifact_type = _record_str(record, "artifactType", "type").lower()
    if artifact_type != "gap":
        return {
            "verdict": "fail",
            "error": "unsupported-artifact-type",
            "action": "build-gap-issue-spec",
            "artifactType": artifact_type,
        }
    unit_id = _record_str(record, "unitId", "id")
    owned = semantic_owned_fields(record, project_key=project_key)
    labels = list(owned.get("labels") or [])
    if GAP_LABEL not in labels:
        labels.append(GAP_LABEL)
    if project_key:
        labels.append(f"sw:project:{project_key}")
    owned["labels"] = sorted(set(labels))
    return {
        "verdict": "pass",
        "action": "build-gap-issue-spec",
        "linearEntity": "Issue",
        "unitId": unit_id,
        "artifactType": "gap",
        "marker": unit_projection_marker(unit_id),
        "labels": owned["labels"],
        "projectMembership": prd_project_entity_id or record.get("prdProjectEntityId"),
        "ownedFields": owned,
        "isFreezeAuthority": False,
        "isSourceOfTruth": False,
        "freezeAuthority": "portable-graph",
    }


def build_phase_milestone_spec(
    record: dict[str, Any],
    *,
    project_key: str,
    prd_project_entity_id: str | None = None,
) -> dict[str, Any]:
    """R33 — semantic phase record → Linear Milestone with dependency order + delivery status."""
    artifact_type = _record_str(record, "artifactType", "type").lower()
    if artifact_type != "phase":
        return {
            "verdict": "fail",
            "error": "unsupported-artifact-type",
            "action": "build-phase-milestone-spec",
            "artifactType": artifact_type,
        }
    unit_id = _record_str(record, "unitId", "id")
    owned = semantic_owned_fields(record, project_key=project_key)
    phase_id = owned.get("phaseId") or unit_id
    prefix = f"[{project_key}] " if project_key else ""
    title = owned["title"]
    if prefix and not title.startswith(prefix):
        title = f"{prefix}Phase {phase_id}: {title}"
    owned["title"] = title
    return {
        "verdict": "pass",
        "action": "build-phase-milestone-spec",
        "linearEntity": "Milestone",
        "unitId": unit_id,
        "artifactType": "phase",
        "marker": unit_projection_marker(unit_id),
        "projectId": prd_project_entity_id or record.get("prdProjectEntityId"),
        "ownedFields": owned,
        "isFreezeAuthority": False,
        "isSourceOfTruth": False,
        "freezeAuthority": "portable-graph",
    }


def build_task_issue_spec(
    record: dict[str, Any],
    *,
    project_key: str,
    prd_project_entity_id: str | None = None,
    phase_milestone_entity_id: str | None = None,
    parent_issue_entity_id: str | None = None,
) -> dict[str, Any]:
    """R33 — semantic task record → linked sub-issue with phase parentage and traceability."""
    artifact_type = _record_str(record, "artifactType", "type").lower()
    if artifact_type != "task":
        return {
            "verdict": "fail",
            "error": "unsupported-artifact-type",
            "action": "build-task-issue-spec",
            "artifactType": artifact_type,
        }
    unit_id = _record_str(record, "unitId", "id")
    owned = semantic_owned_fields(record, project_key=project_key)
    task_ref = owned.get("taskRef") or unit_id
    prefix = f"[{project_key}] " if project_key else ""
    title = owned["title"]
    if prefix and not title.startswith(prefix):
        title = f"{prefix}{task_ref} {title}"
    owned["title"] = title
    labels = list(owned.get("labels") or [])
    if TASK_LABEL not in labels:
        labels.append(TASK_LABEL)
    if project_key:
        labels.append(f"sw:project:{project_key}")
    owned["labels"] = sorted(set(labels))
    return {
        "verdict": "pass",
        "action": "build-task-issue-spec",
        "linearEntity": "Issue",
        "unitId": unit_id,
        "artifactType": "task",
        "marker": unit_projection_marker(unit_id),
        "labels": owned["labels"],
        "projectMembership": prd_project_entity_id or record.get("prdProjectEntityId"),
        "milestoneId": phase_milestone_entity_id or record.get("phaseMilestoneEntityId"),
        "parentIssueId": parent_issue_entity_id or record.get("parentIssueEntityId"),
        "subIssue": True,
        "ownedFields": owned,
        "isFreezeAuthority": False,
        "isSourceOfTruth": False,
        "freezeAuthority": "portable-graph",
    }


def semantic_record_to_projection_spec(
    record: dict[str, Any],
    *,
    project_key: str,
    prd_project_entity_id: str | None = None,
    phase_milestone_entity_id: str | None = None,
    parent_issue_entity_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch semantic record → Linear projection entity spec."""
    artifact_type = _record_str(record, "artifactType", "type").lower()
    if artifact_type == "prd":
        return build_prd_project_spec(record, project_key=project_key)
    if artifact_type == "brainstorm":
        return build_brainstorm_document_spec(
            record,
            project_key=project_key,
            prd_project_entity_id=prd_project_entity_id,
        )
    if artifact_type == "gap":
        return build_gap_issue_spec(
            record,
            project_key=project_key,
            prd_project_entity_id=prd_project_entity_id,
        )
    if artifact_type == "phase":
        return build_phase_milestone_spec(
            record,
            project_key=project_key,
            prd_project_entity_id=prd_project_entity_id,
        )
    if artifact_type == "task":
        return build_task_issue_spec(
            record,
            project_key=project_key,
            prd_project_entity_id=prd_project_entity_id,
            phase_milestone_entity_id=phase_milestone_entity_id,
            parent_issue_entity_id=parent_issue_entity_id,
        )
    return {
        "verdict": "fail",
        "error": "unsupported-artifact-type",
        "action": "semantic-record-to-projection-spec",
        "artifactType": artifact_type,
    }


class LinearProjectionRebuildStore:
    """In-memory Linear projection store for rebuild tests and dry-run rebuilds."""

    def __init__(self) -> None:
        self.projects: dict[str, dict[str, Any]] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.milestones: dict[str, dict[str, Any]] = {}
        self.issues: dict[str, dict[str, Any]] = {}

    def _bucket(self, linear_entity: str) -> dict[str, dict[str, Any]]:
        kind = linear_entity.lower()
        if kind == "project":
            return self.projects
        if kind == "document":
            return self.documents
        if kind == "milestone":
            return self.milestones
        if kind == "issue":
            return self.issues
        raise KeyError(linear_entity)

    def iter_entities(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for bucket in (self.projects, self.documents, self.milestones, self.issues):
            rows.extend(dict(entity) for entity in bucket.values())
        return rows

    def find_by_marker(self, marker: str, linear_entity: str) -> dict[str, Any] | None:
        bucket = self._bucket(linear_entity)
        for entity in bucket.values():
            if entity.get("marker") == marker:
                return dict(entity)
        return None

    def tombstone(self, entity_id: str, linear_entity: str) -> dict[str, Any]:
        bucket = self._bucket(linear_entity)
        existing = bucket.get(entity_id)
        if existing is None:
            return {
                "verdict": "miss",
                "action": "linear-projection-store-tombstone",
                "entityId": entity_id,
                "linearEntity": linear_entity,
            }
        entity = dict(existing)
        entity["tombstoned"] = True
        entity["isSourceOfTruth"] = False
        entity["isFreezeAuthority"] = False
        bucket[entity_id] = entity
        return {
            "verdict": "pass",
            "action": "linear-projection-store-tombstone",
            "entityId": entity_id,
            "linearEntity": linear_entity,
            "tombstoned": True,
        }

    def upsert(self, spec: dict[str, Any]) -> dict[str, Any]:
        linear_entity = str(spec.get("linearEntity") or "")
        marker = str(spec.get("marker") or "")
        unit_id = str(spec.get("unitId") or "")
        bucket = self._bucket(linear_entity)
        existing = self.find_by_marker(marker, linear_entity) if marker else None
        entity_id = str((existing or {}).get("entityId") or spec.get("entityId") or f"lin-{linear_entity.lower()}-{unit_id}")
        entity = {
            "entityId": entity_id,
            "linearEntity": linear_entity,
            "unitId": unit_id,
            "artifactType": spec.get("artifactType"),
            "marker": marker,
            "ownedFields": dict(spec.get("ownedFields") or {}),
            "isFreezeAuthority": False,
            "isSourceOfTruth": False,
            "tombstoned": False,
        }
        if linear_entity == "Document":
            entity["attachedToProject"] = spec.get("attachedToProject")
        if linear_entity == "Milestone":
            entity["projectId"] = spec.get("projectId")
        if linear_entity == "Issue":
            entity["labels"] = list(spec.get("labels") or [])
            entity["projectMembership"] = spec.get("projectMembership")
            entity["milestoneId"] = spec.get("milestoneId")
            entity["parentIssueId"] = spec.get("parentIssueId")
            entity["subIssue"] = bool(spec.get("subIssue"))
        created = existing is None
        bucket[entity_id] = entity
        return {
            "verdict": "pass",
            "action": "linear-projection-store-upsert",
            "created": created,
            "updated": not created,
            "entityId": entity_id,
            "entity": entity,
        }


def rebuild_projection_for_unit(
    graph: dict[str, Any],
    *,
    unit_id: str,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R33 — idempotent re-project for one unit; no duplicate entities."""
    del workspace  # reserved for initiative/cycle capability probes
    layout = project_graph_to_linear_layout(graph)
    if layout.get("verdict") != "pass":
        return layout
    matches = [entity for entity in layout.get("entities") or [] if entity.get("unitId") == unit_id]
    if len(matches) > 1:
        return {
            "verdict": "fail",
            "error": "duplicate-projection-entities",
            "action": "rebuild-projection-for-unit",
            "unitId": unit_id,
            "count": len(matches),
        }
    layout2 = project_graph_to_linear_layout(graph)
    matches2 = [entity for entity in layout2.get("entities") or [] if entity.get("unitId") == unit_id]
    if len(matches) != len(matches2):
        return {
            "verdict": "fail",
            "error": "duplicate-projection-entities",
            "action": "rebuild-projection-for-unit",
            "unitId": unit_id,
        }
    return {
        "verdict": "pass",
        "action": "rebuild-projection-for-unit",
        "unitId": unit_id,
        "entity": matches[0] if matches else None,
        "idempotent": True,
        "duplicateEntities": False,
    }


def _resolve_prd_project_entity_id(
    root_path: Any,
    *,
    prd_unit: str,
    prd_entity_by_unit: dict[str, str],
    scope: str,
) -> str | None:
    if not prd_unit:
        return None
    cached = prd_entity_by_unit.get(prd_unit)
    if cached:
        return cached
    from planning_projection_ledger import projection_ledger_lookup

    lookup = projection_ledger_lookup(
        root_path,
        unit_id=prd_unit,
        artifact_type="prd",
        provider="linear",
        scope=scope,
    )
    if lookup.get("verdict") == "pass":
        return str((lookup.get("entry") or {}).get("entityId") or "") or None
    return None


def _order_semantic_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = [record for record in records if isinstance(record, dict)]
    phases = [row for row in base if _record_str(row, "artifactType", "type").lower() == "phase"]
    others = [row for row in base if _record_str(row, "artifactType", "type").lower() != "phase"]
    ordered_others = sorted(
        others,
        key=lambda row: (
            _PROJECTION_ARTIFACT_ORDER.index(
                _record_str(row, "artifactType", "type").lower()
            )
            if _record_str(row, "artifactType", "type").lower() in _PROJECTION_ARTIFACT_ORDER
            else 99,
            _record_str(row, "unitId", "id"),
        ),
    )
    ordered_phases = _sort_phases_by_dependency(phases)
    tasks = [row for row in ordered_others if _record_str(row, "artifactType", "type").lower() == "task"]
    non_tasks = [row for row in ordered_others if _record_str(row, "artifactType", "type").lower() != "task"]
    return non_tasks + ordered_phases + sorted(tasks, key=lambda row: _record_str(row, "taskRef", "ref", "unitId", "id"))


def tombstone_stale_linear_projection_entities(
    projection_store: LinearProjectionRebuildStore,
    active_markers: set[str],
) -> dict[str, Any]:
    """Tombstone projection entities absent from the semantic-store authority set."""
    tombstoned: list[dict[str, Any]] = []
    for entity in projection_store.iter_entities():
        marker = str(entity.get("marker") or "")
        if not marker or marker in active_markers or entity.get("tombstoned"):
            continue
        result = projection_store.tombstone(
            str(entity.get("entityId") or ""),
            str(entity.get("linearEntity") or ""),
        )
        if result.get("verdict") == "pass":
            tombstoned.append(
                {
                    "entityId": result.get("entityId"),
                    "linearEntity": result.get("linearEntity"),
                    "marker": marker,
                }
            )
    return {
        "verdict": "pass",
        "action": "tombstone-stale-linear-projection-entities",
        "tombstoneCount": len(tombstoned),
        "tombstoned": tombstoned,
    }


def rebuild_linear_projection_from_semantic_store(
    root: Any,
    records: list[dict[str, Any]],
    *,
    project_key: str = "demo",
    store: LinearProjectionRebuildStore | None = None,
    overwrite_drift: bool = False,
    scope: str = "default",
    artifact_types: tuple[str, ...] | None = None,
    tombstone_stale: bool = True,
) -> dict[str, Any]:
    """R33 — rebuild PRD/Brainstorm/Gap/Phase/Task projections from semantic-store authority."""
    from pathlib import Path

    from planning_projection_ledger import (
        assert_portable_graph_authority,
        check_projection_drift,
        owned_fields_digest,
        projection_ledger_lookup,
        projection_ledger_upsert,
    )

    root_path = Path(root)
    authority = assert_portable_graph_authority(
        {"freezeAuthority": "portable-graph"},
        projection={"freezeAuthority": "derived", "isSourceOfTruth": False},
    )
    if authority.get("verdict") != "pass":
        return authority

    projection_store = store or LinearProjectionRebuildStore()
    ordered = _order_semantic_records(records)
    if artifact_types is not None:
        allowed = {str(item).lower() for item in artifact_types}
        ordered = [
            row
            for row in ordered
            if _record_str(row, "artifactType", "type").lower() in allowed
        ]

    prd_entity_by_unit: dict[str, str] = {}
    phase_entity_by_unit: dict[str, str] = {}
    task_entity_by_unit: dict[str, str] = {}
    created = 0
    updated = 0
    repaired = 0
    upserts: list[dict[str, Any]] = []
    active_markers: set[str] = set()

    for record in ordered:
        artifact_type = _record_str(record, "artifactType", "type").lower()
        unit_id = _record_str(record, "unitId", "id")
        if not unit_id or artifact_type not in _PROJECTION_ARTIFACT_ORDER:
            return {
                "verdict": "fail",
                "error": "rebuild-record-incomplete",
                "action": "rebuild-linear-projection-from-semantic-store",
                "record": record,
            }

        prd_project_entity_id = None
        phase_milestone_entity_id = None
        parent_issue_entity_id = None
        if artifact_type in {"brainstorm", "gap", "phase", "task"}:
            prd_unit = _record_str(record, "prdUnitId", "projectId", "parentUnitId")
            prd_project_entity_id = _resolve_prd_project_entity_id(
                root_path,
                prd_unit=prd_unit,
                prd_entity_by_unit=prd_entity_by_unit,
                scope=scope,
            )
        if artifact_type == "task":
            phase_unit = _record_str(record, "phaseUnitId", "phaseId", "milestoneId")
            phase_milestone_entity_id = phase_entity_by_unit.get(phase_unit)
            if not phase_milestone_entity_id and phase_unit:
                lookup = projection_ledger_lookup(
                    root_path,
                    unit_id=phase_unit,
                    artifact_type="phase",
                    provider="linear",
                    scope=scope,
                )
                if lookup.get("verdict") == "pass":
                    phase_milestone_entity_id = str((lookup.get("entry") or {}).get("entityId") or "")
            parent_task_unit = _record_str(record, "parentTaskUnitId", "parentUnitId")
            if parent_task_unit:
                parent_issue_entity_id = task_entity_by_unit.get(parent_task_unit)

        spec = semantic_record_to_projection_spec(
            record,
            project_key=project_key,
            prd_project_entity_id=prd_project_entity_id or None,
            phase_milestone_entity_id=phase_milestone_entity_id or None,
            parent_issue_entity_id=parent_issue_entity_id or None,
        )
        if spec.get("verdict") != "pass":
            return {**spec, "action": "rebuild-linear-projection-from-semantic-store"}

        marker = str(spec.get("marker") or "")
        linear_entity = str(spec.get("linearEntity") or "")
        if marker:
            active_markers.add(marker)
        existing = projection_store.find_by_marker(marker, linear_entity) if marker else None
        ledger = projection_ledger_lookup(
            root_path,
            unit_id=unit_id,
            artifact_type=artifact_type,
            provider="linear",
            scope=scope,
        )

        if existing is None and ledger.get("verdict") == "pass":
            entity_id = str((ledger.get("entry") or {}).get("entityId") or "")
            bucket = projection_store._bucket(linear_entity)
            existing = bucket.get(entity_id)

        owned = dict(spec.get("ownedFields") or {})
        if existing:
            prior_owned = dict(existing.get("ownedFields") or {})
            if owned_fields_digest(prior_owned) != owned_fields_digest(owned):
                drift = check_projection_drift(
                    root_path,
                    unit_id=unit_id,
                    artifact_type=artifact_type,
                    provider="linear",
                    provider_owned_fields=owned,
                    overwrite_drift=overwrite_drift,
                    audit_actor="linear-projection-rebuild",
                    scope=scope,
                )
                if drift.get("verdict") != "pass":
                    return {
                        **drift,
                        "action": "rebuild-linear-projection-from-semantic-store",
                        "semanticAuthority": True,
                    }
                repaired += 1
        result = projection_store.upsert(spec)
        if result.get("verdict") != "pass":
            return result
        if result.get("created"):
            created += 1
        else:
            updated += 1
        entity_id = str(result.get("entityId") or "")
        if artifact_type == "prd" and entity_id:
            prd_entity_by_unit[unit_id] = entity_id
        if artifact_type == "phase" and entity_id:
            phase_entity_by_unit[unit_id] = entity_id
        if artifact_type == "task" and entity_id:
            task_entity_by_unit[unit_id] = entity_id

        ledger_result = projection_ledger_upsert(
            root_path,
            unit_id=unit_id,
            artifact_type=artifact_type,
            provider="linear",
            entity_id=entity_id,
            owned_fields=owned,
            marker=marker,
            scope=scope,
        )
        if ledger_result.get("verdict") != "pass":
            return ledger_result
        upserts.append(
            {
                "unitId": unit_id,
                "artifactType": artifact_type,
                "linearEntity": linear_entity,
                "entityId": entity_id,
                "marker": marker,
            }
        )

    tombstone_result: dict[str, Any] | None = None
    if tombstone_stale and artifact_types is None:
        tombstone_result = tombstone_stale_linear_projection_entities(
            projection_store, active_markers
        )

    mirror_check = assert_projection_mirrors_not_freeze_authority(
        [
            {
                "entityKind": row["linearEntity"],
                "entityId": row["entityId"],
                "isFreezeAuthority": False,
                "isSourceOfTruth": False,
            }
            for row in upserts
        ]
    )
    if mirror_check.get("verdict") != "pass":
        return {**mirror_check, "action": "rebuild-linear-projection-from-semantic-store"}

    return {
        "verdict": "pass",
        "action": "rebuild-linear-projection-from-semantic-store",
        "provider": "linear",
        "semanticAuthority": True,
        "freezeAuthority": "portable-graph",
        "created": created,
        "updated": updated,
        "repaired": repaired,
        "upsertCount": len(upserts),
        "entities": upserts,
        "tombstone": tombstone_result,
        "counts": {
            "Project": len(projection_store.projects),
            "Document": len(projection_store.documents),
            "Milestone": len(projection_store.milestones),
            "Issue": len(projection_store.issues),
        },
    }
