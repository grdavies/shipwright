"""DecisionGraph schema helpers and semantic validation (PRD 280 phase 1)."""
from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any

API_VERSION = "decision-graph/v1"
KIND = "DecisionGraph"
NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "core" / "sw-reference" / "decision-graph-schema.json"


class NodeKind(str, Enum):
    DECISION = "decision"
    RESEARCH = "research"
    HUMAN_ACTION = "human-action"
    PROTOTYPE = "prototype"
    UNKNOWN = "unknown"


NODE_KINDS: frozenset[str] = frozenset(member.value for member in NodeKind)


class ValidationErrorCode(str, Enum):
    SCHEMA_INVALID_KIND = "schema:invalid-kind"
    SCHEMA_MISSING_FIELD = "schema:missing-field"
    GRAPH_CYCLE = "graph:cycle"
    GRAPH_DANGLING_EDGE = "graph:dangling-edge"
    GRAPH_DUPLICATE_NODE_ID = "graph:duplicate-node-id"
    FREEZE_UNKNOWN_OPEN = "freeze:unknown-open"


def schema_path() -> Path:
    return SCHEMA_PATH


def load_schema_document() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_graph(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load graph JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("graph document must be a JSON object")
    return document


def _jsonschema_errors(document: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    def add(code: ValidationErrorCode, message: str, path: list[str]) -> None:
        errors.append({"code": code.value, "message": message, "path": path})

    if document.get("apiVersion") != API_VERSION:
        add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "invalid apiVersion", ["apiVersion"])
    if document.get("kind") != KIND:
        add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "invalid kind", ["kind"])

    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "metadata must be an object", ["metadata"])
        metadata = {}

    if not isinstance(metadata.get("name"), str) or not metadata.get("name"):
        add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "metadata.name required", ["metadata", "name"])

    spec = document.get("spec")
    if not isinstance(spec, dict):
        add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "spec must be an object", ["spec"])
        return errors

    nodes = spec.get("nodes")
    edges = spec.get("edges")
    if not isinstance(nodes, list):
        add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "spec.nodes must be an array", ["spec", "nodes"])
        nodes = []
    if not isinstance(edges, list):
        add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "spec.edges must be an array", ["spec", "edges"])
        edges = []

    for index, node in enumerate(nodes):
        path_prefix = ["spec", "nodes", str(index)]
        if not isinstance(node, dict):
            add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "node must be an object", path_prefix)
            continue

        node_id = node.get("id")
        if not isinstance(node_id, str) or not NODE_ID_PATTERN.fullmatch(node_id):
            add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "invalid node id", path_prefix + ["id"])

        kind = node.get("kind")
        if kind not in NODE_KINDS:
            add(
                ValidationErrorCode.SCHEMA_INVALID_KIND,
                f"invalid node kind: {kind!r}",
                path_prefix + ["kind"],
            )
            continue

        status = node.get("status")
        if status not in {"open", "resolved", "cancelled"}:
            add(
                ValidationErrorCode.SCHEMA_MISSING_FIELD,
                f"invalid node status: {status!r}",
                path_prefix + ["status"],
            )

        if kind == NodeKind.DECISION.value:
            if not isinstance(node.get("question"), str) or not node.get("question"):
                add(
                    ValidationErrorCode.SCHEMA_MISSING_FIELD,
                    "decision node requires question",
                    path_prefix + ["question"],
                )
        elif kind == NodeKind.RESEARCH.value:
            if not isinstance(node.get("topic"), str) or not node.get("topic"):
                add(
                    ValidationErrorCode.SCHEMA_MISSING_FIELD,
                    "research node requires topic",
                    path_prefix + ["topic"],
                )
        elif kind in {NodeKind.HUMAN_ACTION.value, NodeKind.PROTOTYPE.value}:
            if not isinstance(node.get("title"), str) or not node.get("title"):
                add(
                    ValidationErrorCode.SCHEMA_MISSING_FIELD,
                    f"{kind} node requires title",
                    path_prefix + ["title"],
                )
        elif kind == NodeKind.UNKNOWN.value:
            if not isinstance(node.get("question"), str) or not node.get("question"):
                add(
                    ValidationErrorCode.SCHEMA_MISSING_FIELD,
                    "unknown node requires question",
                    path_prefix + ["question"],
                )

        if kind in {NodeKind.DECISION.value, NodeKind.UNKNOWN.value} and status == "resolved":
            resolution = node.get("resolution")
            if not isinstance(resolution, dict):
                add(
                    ValidationErrorCode.SCHEMA_MISSING_FIELD,
                    "resolved node requires resolution",
                    path_prefix + ["resolution"],
                )
            elif not isinstance(resolution.get("outcome"), str) or not resolution.get("outcome"):
                add(
                    ValidationErrorCode.SCHEMA_MISSING_FIELD,
                    "resolution.outcome required",
                    path_prefix + ["resolution", "outcome"],
                )

    for index, edge in enumerate(edges):
        path_prefix = ["spec", "edges", str(index)]
        if not isinstance(edge, dict):
            add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "edge must be an object", path_prefix)
            continue
        if not isinstance(edge.get("from"), str) or not edge.get("from"):
            add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "edge.from required", path_prefix + ["from"])
        if not isinstance(edge.get("to"), str) or not edge.get("to"):
            add(ValidationErrorCode.SCHEMA_MISSING_FIELD, "edge.to required", path_prefix + ["to"])

    return errors


def _node_ids(nodes: list[Any]) -> list[str]:
    ids: list[str] = []
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            ids.append(node["id"])
    return ids


def _semantic_errors(document: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return errors

    nodes = spec.get("nodes")
    edges = spec.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return errors

    node_ids = _node_ids(nodes)
    seen: set[str] = set()
    for node_id in node_ids:
        if node_id in seen:
            errors.append(
                {
                    "code": ValidationErrorCode.GRAPH_DUPLICATE_NODE_ID.value,
                    "message": f"duplicate node id: {node_id}",
                    "path": ["spec", "nodes"],
                }
            )
        seen.add(node_id)

    id_set = set(node_ids)
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            continue
        from_id = edge.get("from")
        to_id = edge.get("to")
        if isinstance(from_id, str) and from_id not in id_set:
            errors.append(
                {
                    "code": ValidationErrorCode.GRAPH_DANGLING_EDGE.value,
                    "message": f"dangling edge from: {from_id}",
                    "path": ["spec", "edges", str(index), "from"],
                }
            )
        if isinstance(to_id, str) and to_id not in id_set:
            errors.append(
                {
                    "code": ValidationErrorCode.GRAPH_DANGLING_EDGE.value,
                    "message": f"dangling edge to: {to_id}",
                    "path": ["spec", "edges", str(index), "to"],
                }
            )

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in id_set}
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

    for node_id in id_set:
        if visit(node_id):
            errors.append(
                {
                    "code": ValidationErrorCode.GRAPH_CYCLE.value,
                    "message": "dependency cycle detected",
                    "path": ["spec", "edges"],
                }
            )
            break

    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("kind") == NodeKind.UNKNOWN.value and node.get("status") == "open":
            node_id = node.get("id", "")
            errors.append(
                {
                    "code": ValidationErrorCode.FREEZE_UNKNOWN_OPEN.value,
                    "message": f"open unknown node blocks freeze: {node_id}",
                    "path": ["spec", "nodes", str(node_id)],
                }
            )

    return errors


def validate_graph(
    document: dict[str, Any],
    *,
    check_freeze: bool = True,
) -> dict[str, Any]:
    errors = _jsonschema_errors(document)
    semantic = _semantic_errors(document)
    if not check_freeze:
        semantic = [
            item
            for item in semantic
            if item.get("code") != ValidationErrorCode.FREEZE_UNKNOWN_OPEN.value
        ]
    errors.extend(semantic)
    if errors:
        return {"verdict": "fail", "errors": errors}
    return {"verdict": "pass", "apiVersion": document.get("apiVersion")}


def minimal_fixture_graph() -> dict[str, Any]:
    return {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "metadata": {"name": "fixture-minimal"},
        "spec": {
            "nodes": [
                {
                    "id": "d1",
                    "kind": NodeKind.DECISION.value,
                    "status": "open",
                    "question": "Which storage backend?",
                }
            ],
            "edges": [],
        },
    }
