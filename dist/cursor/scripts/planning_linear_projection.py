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
