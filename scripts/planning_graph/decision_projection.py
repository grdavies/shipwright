"""PRD ↔ DecisionGraph linkage via sw-edges and issue-store projection (PRD 280 R15/R18)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from planning.identity import (
    decision_graph_unit_id,
    decision_graph_virtual_body_path,
    resolve_decision_put_path,
)
from planning_canonical import (
    build_edges_block,
    parse_edges_block,
    strip_markers_and_edges,
    union_edge_lists,
)

DECISION_GRAPH_EDGE_REL = "decision-graph"
DECISION_GRAPH_FRONTMATTER_KEYS = ("decision-graph", "decisionGraph")


def decision_graph_edge(target_unit_id: str) -> dict[str, str]:
    return {"rel": DECISION_GRAPH_EDGE_REL, "target": target_unit_id}


def decision_graph_target_from_edges(edges: list[dict[str, Any]] | None) -> str | None:
    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        rel = str(edge.get("rel") or edge.get("type") or "").strip()
        if rel != DECISION_GRAPH_EDGE_REL:
            continue
        target = str(edge.get("target") or "").strip()
        if target:
            return target
    return None


def decision_graph_target_from_frontmatter(fm: dict[str, str]) -> str | None:
    for key in DECISION_GRAPH_FRONTMATTER_KEYS:
        raw = str(fm.get(key) or "").strip()
        if raw:
            return raw
    return None


def resolve_decision_graph_unit(prd_unit_id: str, fm: dict[str, str] | None = None) -> str:
    if fm:
        explicit = decision_graph_target_from_frontmatter(fm)
        if explicit:
            return explicit
    return decision_graph_unit_id(prd_unit_id)


def merge_decision_graph_edge(
    existing_body: str,
    graph_unit_id: str,
) -> tuple[str, bool]:
    """Append durable sw-edges linkage from PRD body to DecisionGraph unit."""
    edges_block = parse_edges_block(existing_body)
    edges = list((edges_block or {}).get("edges") or [])
    native = list((edges_block or {}).get("native") or [])
    new_edge = decision_graph_edge(graph_unit_id)
    merged = union_edge_lists(edges, [new_edge])
    if decision_graph_target_from_edges(merged) != graph_unit_id:
        return existing_body, False
    if edges_block is not None and decision_graph_target_from_edges(edges) == graph_unit_id:
        return existing_body, False
    stripped = strip_markers_and_edges(existing_body)
    updated = stripped.rstrip() + "\n\n" + build_edges_block(merged, native)
    return updated, True


def put_decision_graph(
    root: Path,
    prd_unit_id: str,
    graph_document: dict[str, Any],
    *,
    graph_unit_id: str | None = None,
) -> dict[str, Any]:
    """Persist DecisionGraph JSON to issue-store via planning_store.put (R16/R17)."""
    import planning_artifact_handle as pah

    if not pah.issue_store_is_effective(root):
        return {"verdict": "fail", "error": "issue-store-required", "prdUnitId": prd_unit_id}

    unit_id = graph_unit_id or decision_graph_unit_id(prd_unit_id)
    body_path = decision_graph_virtual_body_path(unit_id)
    try:
        unit_id, body_path = resolve_decision_put_path(unit_id, body_path)
    except ValueError as exc:
        return {"verdict": "fail", "error": str(exc), "prdUnitId": prd_unit_id}

    metadata = graph_document.setdefault("metadata", {})
    if isinstance(metadata, dict):
        if not metadata.get("unitId"):
            metadata["unitId"] = unit_id
        if not metadata.get("visibility"):
            metadata["visibility"] = "public"

    content = json.dumps(graph_document, indent=2, ensure_ascii=False) + "\n"
    put = pah.put_artifact_text(root, unit_id, body_path, content)
    if put.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "error": "decision-graph-put-failed",
            "prdUnitId": prd_unit_id,
            "graphUnitId": unit_id,
            **put,
        }
    return {
        "verdict": "ok",
        "action": "put-decision-graph",
        "prdUnitId": prd_unit_id,
        "graphUnitId": unit_id,
        "bodyPath": body_path,
        "backend": put.get("backend"),
        "hash": put.get("hash"),
    }


def project_prd_decision_graph_link(
    root: Path,
    prd_unit_id: str,
    prd_body_path: str,
    *,
    graph_unit_id: str | None = None,
) -> dict[str, Any]:
    """Write PRD ↔ DecisionGraph sw-edges without code-repo file writes (R15/R18)."""
    import planning_artifact_handle as pah

    if not pah.issue_store_is_effective(root):
        return {"verdict": "fail", "error": "issue-store-required", "prdUnitId": prd_unit_id}

    prd_text, source = pah.resolve_artifact_text(root, prd_body_path, unit_id=prd_unit_id)
    if prd_text is None:
        return {
            "verdict": "fail",
            "error": "prd-not-found",
            "prdUnitId": prd_unit_id,
            "bodyPath": prd_body_path,
            "source": source,
        }

    graph_uid = graph_unit_id or decision_graph_unit_id(prd_unit_id)
    updated, changed = merge_decision_graph_edge(prd_text, graph_uid)
    if not changed:
        return {
            "verdict": "pass",
            "action": "project-prd-decision-graph-link",
            "skipped": True,
            "prdUnitId": prd_unit_id,
            "graphUnitId": graph_uid,
        }

    put = pah.put_artifact_text(root, prd_unit_id, prd_body_path, updated)
    if put.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "error": "prd-link-put-failed",
            "prdUnitId": prd_unit_id,
            "graphUnitId": graph_uid,
            **put,
        }
    return {
        "verdict": "pass",
        "action": "project-prd-decision-graph-link",
        "prdUnitId": prd_unit_id,
        "graphUnitId": graph_uid,
        "bodyPath": prd_body_path,
        "backend": put.get("backend"),
    }


def resolve_linked_decision_graph(
    root: Path,
    prd_unit_id: str,
    prd_body_path: str,
) -> dict[str, Any]:
    """Read-only resolve of linked DecisionGraph unit + virtual path for a PRD."""
    import planning_artifact_handle as pah

    prd_text, _ = pah.resolve_artifact_text(root, prd_body_path, unit_id=prd_unit_id)
    if prd_text is None:
        return {"verdict": "fail", "error": "prd-not-found", "prdUnitId": prd_unit_id}

    from doc_link import split_frontmatter

    fm, _ = split_frontmatter(prd_text)
    graph_uid = resolve_decision_graph_unit(prd_unit_id, fm)
    edges_block = parse_edges_block(prd_text)
    edge_target = decision_graph_target_from_edges(list((edges_block or {}).get("edges") or []))
    if edge_target:
        graph_uid = edge_target

    body_path = decision_graph_virtual_body_path(graph_uid)
    exists = pah.artifact_handle_resolves(root, body_path, unit_id=graph_uid)
    return {
        "verdict": "ok" if exists else "not-found",
        "prdUnitId": prd_unit_id,
        "graphUnitId": graph_uid,
        "bodyPath": body_path,
        "linked": bool(edge_target or decision_graph_target_from_frontmatter(fm)),
        "resolved": exists,
    }
