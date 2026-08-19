"""DecisionGraph frontier ready-set solver (PRD 280 phase 2)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from decision_graph.schema import ValidationErrorCode, load_graph, validate_graph


def _spec(document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return [], []
    nodes = spec.get("nodes")
    edges = spec.get("edges")
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    return nodes, edges


def _node_map(nodes: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            out[node["id"]] = node
    return out


def _predecessors(edges: list[Any]) -> dict[str, list[str]]:
    preds: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        from_id = edge.get("from")
        to_id = edge.get("to")
        if isinstance(from_id, str) and isinstance(to_id, str):
            preds.setdefault(to_id, []).append(from_id)
    return preds


def detect_cycle(document: dict[str, Any]) -> bool:
    """Return True when spec.edges contain a dependency cycle."""
    nodes, edges = _spec(document)
    node_ids = {node["id"] for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        from_id = edge.get("from")
        to_id = edge.get("to")
        if isinstance(from_id, str) and isinstance(to_id, str) and from_id in adjacency:
            adjacency[from_id].append(to_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for child in adjacency.get(node_id, []):
            if visit(child):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in node_ids)


def _cancelled_blocks(predecessor_id: str, by_id: dict[str, dict[str, Any]]) -> bool:
    pred = by_id.get(predecessor_id)
    if pred is None:
        return False
    status = str(pred.get("status") or "")
    if status == "cancelled":
        return True
    return False


def compute_frontier(document: dict[str, Any]) -> dict[str, Any]:
    """Return ready open nodes whose dependencies are satisfied; fail closed on cycles."""
    if detect_cycle(document):
        return {
            "verdict": "fail",
            "error": ValidationErrorCode.GRAPH_CYCLE.value,
            "ready": [],
            "blocked": [],
        }

    nodes, edges = _spec(document)
    by_id = _node_map(nodes)
    preds = _predecessors(edges)

    ready: list[str] = []
    blocked: list[dict[str, str]] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        status = str(node.get("status") or "")
        if status != "open":
            continue

        predecessors = preds.get(node_id, [])
        block_reason: str | None = None
        for pred_id in predecessors:
            pred = by_id.get(pred_id)
            if pred is None:
                block_reason = "missing-predecessor"
                break
            pred_status = str(pred.get("status") or "")
            if pred_status == "cancelled":
                block_reason = "cancelled-predecessor"
                break
            if pred_status != "resolved":
                block_reason = "unresolved-predecessor"
                break

        if block_reason:
            blocked.append({"id": node_id, "reason": block_reason})
            continue
        ready.append(node_id)

    ready.sort()
    blocked.sort(key=lambda item: item["id"])
    return {
        "verdict": "pass",
        "ready": ready,
        "blocked": blocked,
        "readyCount": len(ready),
    }


def resolve_graph_path(root: Path, unit_id: str) -> Path | None:
    """Locate a DecisionGraph JSON file for a planning unit (read-only discovery)."""
    candidates = [
        root / "docs" / "planning" / unit_id / "decision-graph.json",
        root / ".cursor" / "sw-decision-graphs" / f"{unit_id}.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def frontier_for_unit(root: Path, unit_id: str, *, graph_path: Path | None = None) -> dict[str, Any]:
    """Load graph for unit-id and compute frontier without mutating storage."""
    path = graph_path or resolve_graph_path(root, unit_id)
    if path is None:
        return {
            "verdict": "fail",
            "error": "graph:not-found",
            "unitId": unit_id,
        }
    try:
        document = load_graph(path)
    except ValueError as exc:
        return {"verdict": "fail", "error": "graph:invalid-json", "message": str(exc), "unitId": unit_id}

    validation = validate_graph(document, check_freeze=False)
    if validation.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "error": "graph:invalid",
            "unitId": unit_id,
            "validation": validation,
        }

    frontier = compute_frontier(document)
    frontier["unitId"] = unit_id
    frontier["graphPath"] = str(path)
    if document.get("metadata", {}).get("name"):
        frontier["graphName"] = document["metadata"]["name"]
    return frontier
