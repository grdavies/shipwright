#!/usr/bin/env python3
"""Load, validate, and compile the versioned WorkflowGraph runtime IR."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
WORKFLOW_SCHEMA_PATH = SCHEMA_DIR / "workflow_graph.schema.json"
NODE_SCHEMA_PATH = SCHEMA_DIR / "node_spec.schema.json"
PHASE_STEP_PLAN_TARGET = "phase-step-plan"


class WorkflowGraphValidationError(ValueError):
    """Raised when a WorkflowGraph or NodeSpec fails closed validation."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowGraphValidationError(f"cannot load JSON document {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise WorkflowGraphValidationError(f"JSON document must be an object: {path}")
    return document


def _schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    return _read_json(WORKFLOW_SCHEMA_PATH), _read_json(NODE_SCHEMA_PATH)


def _matches_type(value: Any, expected: str) -> bool:
    type_map = {
        "object": lambda item: isinstance(item, Mapping),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }
    check = type_map.get(expected)
    return bool(check and check(value))


def _validate_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str = "<root>",
) -> None:
    if "$ref" in schema:
        _, node_schema = _schemas()
        if schema["$ref"] != node_schema["$id"]:
            raise WorkflowGraphValidationError(f"{path}: unresolved schema reference")
        _validate_schema(value, node_schema, path=path)
        return
    if "type" in schema and not _matches_type(value, str(schema["type"])):
        raise WorkflowGraphValidationError(
            f"{path}: expected {schema['type']}, got {type(value).__name__}"
        )
    if "const" in schema and value != schema["const"]:
        raise WorkflowGraphValidationError(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise WorkflowGraphValidationError(f"{path}: value {value!r} is not allowed")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise WorkflowGraphValidationError(f"{path}: string is too short")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(str(pattern), value) is None:
            raise WorkflowGraphValidationError(f"{path}: string does not match {pattern}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < int(schema["minimum"]):
            raise WorkflowGraphValidationError(f"{path}: value is below minimum")
        if "maximum" in schema and value > int(schema["maximum"]):
            raise WorkflowGraphValidationError(f"{path}: value is above maximum")
    if isinstance(value, Mapping):
        required = schema.get("required") or []
        missing = [key for key in required if key not in value]
        if missing:
            raise WorkflowGraphValidationError(
                f"{path}: missing required properties: {', '.join(missing)}"
            )
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise WorkflowGraphValidationError(
                    f"{path}: unknown properties: {', '.join(extras)}"
                )
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                _validate_schema(child, child_schema, path=f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, child in enumerate(value):
            _validate_schema(child, schema["items"], path=f"{path}.{index}")


def default_execution_for_isolation(isolation: Mapping[str, Any]) -> dict[str, str]:
    """Derive trusted execution defaults from isolation.writeScope (R6/R15)."""
    write_scope = str(isolation.get("writeScope") or "none")
    if write_scope in ("none", "read-only"):
        return {"purity": "read-only", "cache": "content-addressed"}
    return {"purity": "mutating", "cache": "disabled"}


def normalize_node_execution(
    node: Mapping[str, Any],
    *,
    trusted_template: bool = True,
) -> dict[str, Any]:
    """Apply execution defaults and strip untrusted purity/cache overrides (R15)."""
    detached = json.loads(json.dumps(node))
    isolation = detached.get("isolation") or {}
    defaults = default_execution_for_isolation(
        isolation if isinstance(isolation, Mapping) else {}
    )
    raw = detached.get("execution")
    if not isinstance(raw, Mapping):
        detached["execution"] = defaults
        return detached
    if not trusted_template:
        # Untrusted payloads may not set security-relevant execution fields.
        detached["execution"] = defaults
        return detached
    purity = str(raw.get("purity") or defaults["purity"])
    cache = str(raw.get("cache") or defaults["cache"])
    if purity == "mutating" and "cache" not in raw:
        cache = "disabled"
    if purity == "mutating" and cache == "content-addressed":
        node_id = detached.get("id", "<unknown>")
        raise WorkflowGraphValidationError(
            f"node {node_id}: mutating nodes must use cache disabled"
        )
    trust = raw.get("trust")
    if isinstance(trust, Mapping) and trust and not raw.get("templateDigest"):
        node_id = detached.get("id", "<unknown>")
        raise WorkflowGraphValidationError(
            f"node {node_id}: execution.trust requires templateDigest from a "
            "trusted in-repo template"
        )
    execution = {"purity": purity, "cache": cache}
    if raw.get("templateDigest"):
        execution["templateDigest"] = str(raw["templateDigest"])
    if isinstance(trust, Mapping) and trust:
        execution["trust"] = json.loads(json.dumps(trust))
    detached["execution"] = execution
    return detached


def validate_node_spec(
    document: Mapping[str, Any],
    *,
    trusted_template: bool = True,
) -> dict[str, Any]:
    """Validate one NodeSpec and return a detached JSON-compatible copy."""
    _, node_schema = _schemas()
    _validate_schema(document, node_schema)
    return normalize_node_execution(
        json.loads(json.dumps(document)),
        trusted_template=trusted_template,
    )


def validate_workflow_graph(
    document: Mapping[str, Any],
    *,
    trusted_template: bool = True,
) -> dict[str, Any]:
    """Validate schema and graph-level identity constraints."""
    workflow_schema, _ = _schemas()
    _validate_schema(document, workflow_schema)
    detached = json.loads(json.dumps(document))
    nodes = detached["spec"]["nodes"]
    node_ids = [node["id"] for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise WorkflowGraphValidationError("duplicate node id")
    known = set(node_ids)
    for edge in detached["spec"]["edges"]:
        for endpoint in ("from", "to"):
            if edge[endpoint] not in known:
                raise WorkflowGraphValidationError(
                    f"edge {endpoint} references unknown node: {edge[endpoint]}"
                )
    detached["spec"]["nodes"] = [
        normalize_node_execution(node, trusted_template=trusted_template)
        for node in nodes
    ]
    return detached


def load_workflow_graph(path: str | Path) -> dict[str, Any]:
    """Load a WorkflowGraph JSON file and validate it before returning."""
    return validate_workflow_graph(_read_json(Path(path)))


def _ordered_nodes(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = document["spec"]["nodes"]
    by_id = {node["id"]: node for node in nodes}
    source_index = {node["id"]: index for index, node in enumerate(nodes)}
    incoming = {node_id: 0 for node_id in by_id}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    for edge in document["spec"]["edges"]:
        incoming[edge["to"]] += 1
        outgoing[edge["from"]].append(edge["to"])

    ready = sorted(
        (node_id for node_id, count in incoming.items() if count == 0),
        key=source_index.__getitem__,
    )
    ordered: list[dict[str, Any]] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(by_id[node_id])
        for successor in outgoing[node_id]:
            incoming[successor] -= 1
            if incoming[successor] == 0:
                ready.append(successor)
                ready.sort(key=source_index.__getitem__)
    if len(ordered) != len(nodes):
        raise WorkflowGraphValidationError("workflow graph contains a cycle")
    return ordered


def compile_target(
    document: Mapping[str, Any],
    *,
    target: str,
) -> dict[str, Any]:
    """Compile validated IR to one existing plan shape without executing it."""
    graph = validate_workflow_graph(document)
    if target != PHASE_STEP_PLAN_TARGET:
        raise WorkflowGraphValidationError(f"unsupported compile target: {target}")

    steps: list[str] = []
    for node in _ordered_nodes(graph):
        step = (node.get("target") or {}).get("step")
        if not isinstance(step, str) or not step:
            raise WorkflowGraphValidationError(
                f"node {node['id']} has no phase-step-plan target"
            )
        steps.append(step)
    return {
        "version": 1,
        "tier": "phase",
        "phaseType": "ship",
        "phaseId": graph["metadata"].get("phaseId", graph["metadata"]["name"]),
        "steps": steps,
        "sourceApiVersion": graph["apiVersion"],
    }
