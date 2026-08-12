#!/usr/bin/env python3
"""Compile WorkflowGraph IR through Shipwright's deterministic safety kernel."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from graph.ir import WorkflowGraphValidationError, validate_workflow_graph

KERNEL_CLASSIFICATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "sw-reference"
    / "kernel-classification.json"
)
KERNEL_VERSION = "1.0.0"
CLOSED_NODE_KINDS = frozenset(
    {
        "barrier",
        "command",
        "convergence-loop",
        "gate",
        "router",
        "transform",
        "verifier",
    }
)


class KernelCompilationError(ValueError):
    """Raised when a graph attempts to bypass a safety-kernel constraint."""


def _classification() -> dict[str, Any]:
    try:
        value = json.loads(KERNEL_CLASSIFICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KernelCompilationError(
            f"cannot load kernel classification: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise KernelCompilationError("kernel classification must be an object")
    return value


def _required_gate_steps(classification: Mapping[str, Any]) -> tuple[str, ...]:
    gates = []
    for chokepoint in classification.get("kernelChokepoints", []):
        if isinstance(chokepoint, Mapping) and chokepoint.get("stepId"):
            gates.append(str(chokepoint["stepId"]))
    return tuple(sorted(set(gates)))


def _normalize_capabilities(
    node_capabilities: Mapping[str, Mapping[str, Sequence[str]]] | None,
    node_ids: set[str],
) -> dict[str, dict[str, tuple[str, ...]]]:
    normalized: dict[str, dict[str, tuple[str, ...]]] = {}
    for node_id, capabilities in (node_capabilities or {}).items():
        if node_id not in node_ids:
            raise KernelCompilationError(
                f"capabilities reference unknown node: {node_id}"
            )
        normalized[node_id] = {
            "credentials": tuple(
                sorted(set(str(item) for item in capabilities.get("credentials", ())))
            ),
            "sideEffects": tuple(
                sorted(set(str(item) for item in capabilities.get("sideEffects", ())))
            ),
        }
    return normalized


def _assert_declared(
    capabilities: Mapping[str, Mapping[str, Sequence[str]]],
    *,
    declared_credentials: Iterable[str],
    declared_side_effects: Iterable[str],
) -> None:
    credential_allowlist = set(declared_credentials)
    side_effect_allowlist = set(declared_side_effects)
    for node_id, requested in capabilities.items():
        undeclared_credentials = set(requested["credentials"]) - credential_allowlist
        if undeclared_credentials:
            names = ", ".join(sorted(undeclared_credentials))
            raise KernelCompilationError(
                f"node {node_id} requests undeclared credential: {names}"
            )
        undeclared_side_effects = set(requested["sideEffects"]) - side_effect_allowlist
        if undeclared_side_effects:
            names = ", ".join(sorted(undeclared_side_effects))
            raise KernelCompilationError(
                f"node {node_id} requests undeclared side effect: {names}"
            )


def _assert_bounded_loops(
    graph: Mapping[str, Any],
    loop_bounds: Mapping[str, Mapping[str, int]] | None,
) -> None:
    bounds = loop_bounds or {}
    for node in graph["spec"]["nodes"]:
        if node["kind"] != "convergence-loop":
            continue
        node_bounds = bounds.get(node["id"])
        if not node_bounds:
            raise KernelCompilationError(
                f"loop node {node['id']} must declare bounded execution"
            )
        max_rounds = node_bounds.get("maxRounds", 0)
        max_tokens = node_bounds.get("maxTokens", 0)
        if (
            isinstance(max_rounds, bool)
            or not isinstance(max_rounds, int)
            or max_rounds <= 0
            or isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise KernelCompilationError(
                f"loop node {node['id']} must have positive bounded rounds and tokens"
            )


def _assert_gates(
    graph: Mapping[str, Any],
    *,
    required_gates: Sequence[str],
    proposed_steps: Sequence[str] | None,
) -> None:
    verification = graph["spec"]["verification"]
    if not verification["required"] or not verification["failClosed"]:
        raise KernelCompilationError("workflow verification gate cannot be removed")
    for node in graph["spec"]["nodes"]:
        if not node["verification"]["required"]:
            raise KernelCompilationError(
                f"node {node['id']} attempts to weaken its verification gate"
            )
    if proposed_steps is not None:
        missing = set(required_gates) - set(proposed_steps)
        if missing:
            raise KernelCompilationError(
                "proposed plan removes kernel gate(s): " + ", ".join(sorted(missing))
            )


def compile_workflow_graph(
    document: Mapping[str, Any],
    *,
    node_capabilities: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    declared_credentials: Iterable[str] = (),
    declared_side_effects: Iterable[str] = (),
    loop_bounds: Mapping[str, Mapping[str, int]] | None = None,
    proposed_steps: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate and compile a graph to a non-executable, kernel-stamped artifact."""
    try:
        graph = validate_workflow_graph(document)
    except WorkflowGraphValidationError as exc:
        raise KernelCompilationError(str(exc)) from exc

    node_kinds = {str(node["kind"]) for node in graph["spec"]["nodes"]}
    unknown = node_kinds - CLOSED_NODE_KINDS
    if unknown:
        raise KernelCompilationError(
            "unknown node kind(s): " + ", ".join(sorted(unknown))
        )

    node_ids = {str(node["id"]) for node in graph["spec"]["nodes"]}
    capabilities = _normalize_capabilities(node_capabilities, node_ids)
    _assert_declared(
        capabilities,
        declared_credentials=declared_credentials,
        declared_side_effects=declared_side_effects,
    )
    _assert_bounded_loops(graph, loop_bounds)

    classification = _classification()
    required_gates = _required_gate_steps(classification)
    _assert_gates(
        graph,
        required_gates=required_gates,
        proposed_steps=proposed_steps,
    )

    canonical_graph = json.dumps(
        graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return {
        "kernelVersion": str(classification.get("kernelVersion", KERNEL_VERSION)),
        "graphHash": hashlib.sha256(canonical_graph).hexdigest(),
        "nodeKinds": sorted(node_kinds),
        "requiredGates": list(required_gates),
        "graph": graph,
        "capabilities": capabilities,
        "loopBounds": {
            key: dict(value) for key, value in sorted((loop_bounds or {}).items())
        },
    }
