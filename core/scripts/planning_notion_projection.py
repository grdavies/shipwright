"""PRD 327 — Notion operator projection schema (R5).

Maps the portable semantic planning graph onto Notion-native databases for the
operator projection. Projection entities remain rebuildable; portable graph is SoT.

Freeze/hash authority lives on the LCD page body (or explicit document-backed body) —
never on database/relation/status projection mirrors.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Freeze/hash SoT body sources (facade get/freeze resolution).
CANONICAL_BODY_SOURCES = frozenset({"lcd-page", "lcd-issue", "document-backed"})

# Rebuildable projection mirrors; never freeze/hash authority.
PROJECTION_MIRROR_KINDS = frozenset(
    {
        "DatabasePage",
        "Relation",
        "Status",
        "Select",
        "Date",
        "database-page",
        "relation",
        "status",
        "select",
        "date",
        "progress",
        "program",
    }
)

DOCUMENT_BACKED_LABEL = "sw:document-backed"
DOCUMENT_BACKED_MARKER = "<!-- sw-document-backed -->"

# R5 — normative semantic unit → Notion database / property mapping.
NOTION_ENTITY_MAP: dict[str, dict[str, Any]] = {
    "prd": {
        "artifactType": "prd",
        "notionEntity": "DatabasePage",
        "databaseRole": "prd",
        "notes": "One PRD database page per PRD unit",
        "r1": [1, 2, 3, 4],
    },
    "brainstorm": {
        "artifactType": "brainstorm",
        "notionEntity": "DatabasePage",
        "databaseRole": "brainstorm",
        "notes": "Brainstorm database page; feeds → PRD via dual_property",
        "r1": [2],
        "relateTo": "prd",
    },
    "gap": {
        "artifactType": "gap",
        "notionEntity": "DatabasePage",
        "databaseRole": "gap",
        "notes": "Gap database page; absorbs → PRD via dual_property",
        "r1": [1],
        "relateTo": "prd",
    },
    "phase": {
        "artifactType": "phase",
        "notionEntity": "DatabasePage",
        "databaseRole": "phase",
        "notes": "Phase database page; relation child of task-list / PRD",
        "r1": [3],
        "parent": "prd",
        "windowProperty": "date",
    },
    "task": {
        "artifactType": "task",
        "notionEntity": "DatabasePage",
        "databaseRole": "task",
        "notes": "Task database page; depends encodes as task↔task relation",
        "r1": [3],
    },
    "program": {
        "artifactType": "program",
        "notionEntity": "Select",
        "databaseRole": "program",
        "property": "select",
        "notes": "Program grouping via select property / database row",
        "r1": [4],
        "optionalWhenUnavailable": True,
    },
    "progress": {
        "artifactType": "progress",
        "notionEntity": "Status",
        "databaseRole": "progress",
        "property": "Status",
        "notes": "Completion via Status property",
        "r1": [3, 4],
    },
}

# R5 — endpoint-typed edge encoding (dual_property preferred; single_property + back-ref view fallback).
EDGE_ENCODINGS: dict[str, dict[str, Any]] = {
    "absorbs": {
        "edgeType": "absorbs",
        "encoding": "dual_property",
        "fallbackEncoding": "single_property+back-reference-view",
        "sourceKinds": ("gap", "DatabasePage"),
        "targetKinds": ("prd", "DatabasePage"),
        "stubPageEndpointsProhibited": True,
        "projectionFields": ["dualPropertyRelation", "gapPageIdentity", "prdPageLink"],
    },
    "feeds": {
        "edgeType": "feeds",
        "encoding": "dual_property",
        "fallbackEncoding": "single_property+back-reference-view",
        "sourceKinds": ("brainstorm", "DatabasePage"),
        "targetKinds": ("prd", "DatabasePage"),
        "stubPageEndpointsProhibited": True,
        "projectionFields": ["dualPropertyRelation", "brainstormPageIdentity", "prdPageLink"],
    },
    "depends": {
        "edgeType": "depends",
        "encoding": "task-task-relation",
        "sourceKinds": ("task", "DatabasePage"),
        "targetKinds": ("task", "DatabasePage"),
        "stubPageEndpointsProhibited": True,
        "projectionFields": ["taskRelation"],
    },
}

DUAL_PROPERTY_FALLBACK_VIEWS: dict[str, Any] = {
    "id": "single-property-back-reference-views",
    "description": (
        "When the workspace forbids dual_property relations, encode absorbs/feeds as "
        "single_property on the source page plus a documented back-reference view on the "
        "target database so both endpoints remain browsable"
    ),
    "requiredViews": [
        "prd-absorbed-gaps",
        "prd-fed-by-brainstorms",
    ],
    "silentSkipProhibited": True,
}


def notion_entity_mapping() -> dict[str, Any]:
    """R5 — documented Notion operator schema mapping."""
    return {
        "verdict": "ok",
        "action": "notion-entity-mapping",
        "provider": "notion",
        "rows": [dict(row) for row in NOTION_ENTITY_MAP.values()],
        "byArtifactType": {k: dict(v) for k, v in NOTION_ENTITY_MAP.items()},
    }


def map_artifact_to_notion_entity(artifact_type: str) -> dict[str, Any]:
    """R5 — resolve a single artifact type to its Notion entity kind."""
    key = (artifact_type or "").strip().lower()
    row = NOTION_ENTITY_MAP.get(key)
    if row is None:
        return {
            "verdict": "fail",
            "error": "unsupported-artifact-type",
            "artifactType": artifact_type,
        }
    return {"verdict": "ok", "artifactType": key, **dict(row)}


def probe_dual_property_availability(
    *,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R5 — init/probe dual_property relation availability for the Notion workspace."""
    caps = workspace or {}
    available = caps.get("dualPropertyEnabled")
    if available is None:
        available = caps.get("dual_property", True)
    available = bool(available)
    return {
        "verdict": "ok",
        "action": "probe-dual-property-availability",
        "available": available,
        "degraded": not available,
        "fallback": DUAL_PROPERTY_FALLBACK_VIEWS if not available else None,
    }


def apply_dual_property_capability(
    *,
    probe: dict[str, Any] | None = None,
    substitute_configured: bool = True,
) -> dict[str, Any]:
    """R5 — emit dual_property degradation + back-ref views; silent skip prohibited."""
    probe_result = probe or probe_dual_property_availability()
    available = bool(probe_result.get("available"))
    notices: list[dict[str, Any]] = []
    if not available:
        if not substitute_configured:
            return {
                "verdict": "fail",
                "error": "dual-property-unavailable-without-substitute",
                "action": "apply-dual-property-capability",
                "silentSkipProhibited": True,
            }
        notices.append(
            {
                "concept": "dual_property",
                "severity": "degraded",
                "missingNative": "Notion dual_property relations",
                "fallbackBrowsePath": DUAL_PROPERTY_FALLBACK_VIEWS["description"],
                "requiredViews": list(DUAL_PROPERTY_FALLBACK_VIEWS["requiredViews"]),
                "silentSkip": False,
            }
        )
    encoding = "dual_property" if available else "single_property+back-reference-view"
    return {
        "verdict": "ok",
        "action": "apply-dual-property-capability",
        "dualPropertyAvailable": available,
        "edgeEncoding": encoding,
        "degradationNotices": notices,
        "substituteViews": dict(DUAL_PROPERTY_FALLBACK_VIEWS) if not available else None,
        "silentSkipProhibited": True,
    }


def encode_planning_edge(
    edge: dict[str, Any],
    *,
    dual_property_available: bool = True,
) -> dict[str, Any]:
    """R5 — encode absorbs/feeds/depends for Notion projection."""
    if not isinstance(edge, dict):
        return {"verdict": "fail", "error": "edge-missing", "action": "encode-planning-edge"}
    edge_type = str(edge.get("edgeType") or edge.get("type") or "").strip().lower()
    spec = EDGE_ENCODINGS.get(edge_type)
    if spec is None:
        return {
            "verdict": "fail",
            "error": "unsupported-edge-type",
            "action": "encode-planning-edge",
            "edgeType": edge_type,
        }

    source = edge.get("source") if isinstance(edge.get("source"), dict) else {
        "unitId": edge.get("sourceUnitId") or edge.get("from"),
        "kind": edge.get("sourceKind") or edge.get("fromKind"),
        "stub": edge.get("sourceStub"),
    }
    target = edge.get("target") if isinstance(edge.get("target"), dict) else {
        "unitId": edge.get("targetUnitId") or edge.get("to"),
        "kind": edge.get("targetKind") or edge.get("toKind"),
        "stub": edge.get("targetStub"),
    }
    if source.get("stub") is True or target.get("stub") is True:
        return {
            "verdict": "fail",
            "error": "stub-page-endpoints-prohibited",
            "action": "encode-planning-edge",
            "edgeType": edge_type,
        }
    if edge.get("stubEndpoints") is True or edge.get("stubPageEndpoints") is True:
        return {
            "verdict": "fail",
            "error": "stub-page-endpoints-prohibited",
            "action": "encode-planning-edge",
            "edgeType": edge_type,
        }

    source_kind = str(source.get("kind") or "").strip()
    target_kind = str(target.get("kind") or "").strip()
    encoding = str(spec["encoding"])
    notices: list[dict[str, Any]] = []
    if edge_type in {"absorbs", "feeds"} and not dual_property_available:
        encoding = str(spec["fallbackEncoding"])
        notices.append(
            {
                "concept": "dual_property",
                "severity": "degraded",
                "edgeType": edge_type,
                "fallback": encoding,
                "silentSkip": False,
            }
        )

    return {
        "verdict": "pass",
        "action": "encode-planning-edge",
        "edgeType": edge_type,
        "encoding": encoding,
        "source": {
            "kind": source_kind,
            "unitId": source.get("unitId"),
        },
        "target": {
            "kind": target_kind,
            "unitId": target.get("unitId"),
        },
        "projectionFields": list(spec.get("projectionFields") or []),
        "stubPageEndpoints": False,
        "degradationNotices": notices,
        "properties": {
            "phaseWindow": "date",
            "programGrouping": "select",
            "completion": "Status",
        },
    }


def project_graph_to_notion_layout(
    graph: dict[str, Any],
    *,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R5 — project a fixture semantic graph into expected Notion entity layout."""
    if not isinstance(graph, dict) or not graph:
        return {
            "verdict": "fail",
            "error": "portable-graph-missing",
            "action": "project-graph-to-notion-layout",
        }
    units = list(graph.get("units") or [])
    edges = list(graph.get("edges") or [])
    dual = apply_dual_property_capability(
        probe=probe_dual_property_availability(workspace=workspace),
    )
    dual_ok = bool(dual.get("dualPropertyAvailable"))

    entities: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        artifact_type = str(unit.get("artifactType") or unit.get("type") or "").strip().lower()
        mapped = map_artifact_to_notion_entity(artifact_type)
        if mapped.get("verdict") != "ok":
            return {**mapped, "action": "project-graph-to-notion-layout", "unit": unit}
        unit_id = str(unit.get("unitId") or unit.get("id") or "")
        entity: dict[str, Any] = {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "notionEntity": mapped["notionEntity"],
            "databaseRole": mapped.get("databaseRole"),
            "entityId": unit.get("entityId") or unit.get("providerEntityId"),
            "marker": unit.get("marker"),
            "ownedFields": dict(unit.get("ownedFields") or {}),
            "isFreezeAuthority": False,
            "isSourceOfTruth": False,
        }
        if artifact_type == "phase":
            entity["windowProperty"] = "date"
            entity["parentUnitId"] = unit.get("prdUnitId") or unit.get("parentUnitId")
        if artifact_type == "program":
            entity["property"] = "select"
        if artifact_type == "progress":
            entity["property"] = "Status"
        if artifact_type in {"gap", "brainstorm"}:
            entity["relateTo"] = unit.get("prdUnitId") or unit.get("projectId")
        entities.append(entity)

    by_role: dict[str, list[dict[str, Any]]] = {}
    for ent in entities:
        by_role.setdefault(str(ent.get("databaseRole") or ent["notionEntity"]), []).append(ent)

    encoded_edges: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        encoded = encode_planning_edge(edge, dual_property_available=dual_ok)
        if encoded.get("verdict") != "pass":
            return {**encoded, "action": "project-graph-to-notion-layout"}
        encoded_edges.append(encoded)

    return {
        "verdict": "pass",
        "action": "project-graph-to-notion-layout",
        "provider": "notion",
        "freezeAuthority": "portable-graph",
        "isSourceOfTruth": False,
        "entities": entities,
        "byDatabaseRole": by_role,
        "edges": encoded_edges,
        "counts": {role: len(rows) for role, rows in by_role.items()},
        "dualProperty": dual,
        "properties": {
            "phaseWindow": "date",
            "programGrouping": "select",
            "completion": "Status",
        },
    }


def notion_projection_schema_contract() -> dict[str, Any]:
    """Facade summary for R5 Notion operator schema + dual-write policy."""
    return {
        "verdict": "ok",
        "action": "notion-projection-schema-contract",
        "entityMapping": notion_entity_mapping(),
        "edgeEncodings": {k: dict(v) for k, v in EDGE_ENCODINGS.items()},
        "dualPropertyFallbackViews": dict(DUAL_PROPERTY_FALLBACK_VIEWS),
        "dualWriteBody": dual_write_body_policy(),
        "parityMatrixRow": {
            "backend": "notion",
            "artifacts": "Database per artifact type",
            "phases": "Relation children",
            "progress": "Status property",
            "edges": "dual_property relations",
            "releaseGrouping": "Date/select properties",
        },
    }


def _body_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def normalize_body_source(raw: str | None) -> str:
    """Normalize caller bodySource to lcd-page | document-backed | projection-*."""
    if not raw:
        return "lcd-page"
    value = str(raw).strip().lower().replace("_", "-")
    aliases = {
        "page": "lcd-page",
        "lcd": "lcd-page",
        "lcd-page": "lcd-page",
        "issue": "lcd-page",
        "lcd-issue": "lcd-page",
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
    """R5 — normative dual-write / freeze SoT policy surface for Notion."""
    return {
        "canonicalBodySources": sorted(CANONICAL_BODY_SOURCES),
        "projectionMirrorKinds": sorted(
            {k for k in PROJECTION_MIRROR_KINDS if k[:1].isupper()}
        ),
        "freezeAuthority": "lcd-page-or-document-backed",
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
    """Infer lcd-page vs document-backed from explicit flags, labels, or markers."""
    if document_backed is True:
        return "document-backed"
    if body_source:
        return normalize_body_source(body_source)
    label_set = {str(x) for x in (labels or [])}
    if DOCUMENT_BACKED_LABEL in label_set:
        return "document-backed"
    if body and DOCUMENT_BACKED_MARKER in body:
        return "document-backed"
    return "lcd-page"


def assert_projection_mirrors_not_freeze_authority(
    projection_mirrors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """R5 — database/relation/status mirrors never become freeze SoT."""
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
        "freezeAuthority": "lcd-page-or-document-backed",
    }


def check_canonical_projection_split_brain(
    *,
    canonical_body: str,
    projection_mirrors: list[dict[str, Any]] | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """R5 — fail closed on projection-prefer; typed drift when mirror body diverges."""
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
    """R5 — resolve freeze/hash SoT body; projection mirrors never win."""
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


def dual_write_projection_mirror(
    *,
    unit_id: str,
    entity_kind: str,
    entity_id: str | None = None,
    body: str | None = None,
    derived: bool = True,
) -> dict[str, Any]:
    """R5 — build a rebuildable projection mirror that is never freeze authority."""
    kind = str(entity_kind or "").strip()
    if not kind:
        return {
            "verdict": "fail",
            "error": "projection-mirror-kind-required",
            "action": "dual-write-projection-mirror",
        }
    mirror = {
        "unitId": unit_id,
        "entityKind": kind,
        "entityId": entity_id or f"notion:{unit_id}:{kind}",
        "isFreezeAuthority": False,
        "isSourceOfTruth": False,
        "freezeAuthority": "portable-graph",
        "derived": derived,
        "body": body,
        "bodyParityRequired": False if derived else True,
    }
    check = assert_projection_mirrors_not_freeze_authority([mirror])
    if check["verdict"] != "pass":
        return check
    return {
        "verdict": "pass",
        "action": "dual-write-projection-mirror",
        "mirror": mirror,
    }


def rebuild_projection_for_unit(
    graph: dict[str, Any],
    *,
    unit_id: str,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R5 — idempotent re-project; no duplicate pages for a unit-id."""
    layout = project_graph_to_notion_layout(graph, workspace=workspace)
    if layout.get("verdict") != "pass":
        return layout
    matches = [e for e in layout.get("entities") or [] if e.get("unitId") == unit_id]
    if len(matches) > 1:
        return {
            "verdict": "fail",
            "error": "duplicate-projection-pages",
            "action": "rebuild-projection-for-unit",
            "unitId": unit_id,
            "count": len(matches),
        }
    # Second rebuild must be identical entity set for unit.
    layout2 = project_graph_to_notion_layout(graph, workspace=workspace)
    matches2 = [e for e in layout2.get("entities") or [] if e.get("unitId") == unit_id]
    if len(matches) != len(matches2):
        return {
            "verdict": "fail",
            "error": "duplicate-projection-pages",
            "action": "rebuild-projection-for-unit",
            "unitId": unit_id,
        }
    return {
        "verdict": "pass",
        "action": "rebuild-projection-for-unit",
        "unitId": unit_id,
        "entity": matches[0] if matches else None,
        "idempotent": True,
        "duplicatePages": False,
    }
