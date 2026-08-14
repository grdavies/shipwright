#!/usr/bin/env python3
"""Compile WorkflowGraph IR through Shipwright's deterministic safety kernel."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from graph.ir import WorkflowGraphValidationError, validate_workflow_graph
from graph.scheduling_modes import (
    ExternalDispatchAuthorization,
    authorize_external_dispatch,
)
from graph.transform_ops import TRANSFORM_OPERATOR_NAMES

if TYPE_CHECKING:
    from graph.legacy_adapters import LegacyPlanCompilation
    from graph.scheduler import GraphScheduler, SchedulerRun

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
UNTRUSTED_ORCHESTRATORS = frozenset({"debug", "feedback"})
UNTRUSTED_PAYLOAD_KEYS = frozenset(
    {"signal_context", "signals", "payload", "data", "rawSignal", "raw_signal"}
)
GRAPH_STRUCTURE_KEYS = frozenset(
    {"apiVersion", "kind", "metadata", "spec", "nodes", "edges", "resourceLimits"}
)
SECURITY_RELEVANT_PAYLOAD_KEYS = frozenset(
    {
        "purity",
        "cache",
        "isolation",
        "writeScope",
        "writePaths",
        "credentials",
        "humanMergeGate",
        "execution",
        "resources",
        "verification",
        "kind",
        "pool",
        "slots",
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


def _assert_transform_operators(
    graph: Mapping[str, Any],
    transform_operators: Mapping[str, str] | None,
) -> dict[str, str]:
    declared = dict(transform_operators or {})
    transform_nodes = {
        str(node["id"]) for node in graph["spec"]["nodes"] if node["kind"] == "transform"
    }
    unknown_nodes = set(declared) - transform_nodes
    if unknown_nodes:
        raise KernelCompilationError(
            "transform operators reference non-transform node(s): "
            + ", ".join(sorted(unknown_nodes))
        )
    missing = transform_nodes - set(declared)
    if missing:
        raise KernelCompilationError(
            "transform node(s) must declare a closed-catalog operator: "
            + ", ".join(sorted(missing))
        )
    unknown_operators = set(declared.values()) - TRANSFORM_OPERATOR_NAMES
    if unknown_operators:
        raise KernelCompilationError(
            "unknown transform operator(s): " + ", ".join(sorted(unknown_operators))
        )
    return {node_id: declared[node_id] for node_id in sorted(declared)}


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


def assert_untrusted_payload_boundary(
    plan: Mapping[str, Any],
    *,
    orchestrator_type: str | None = None,
) -> None:
    """Fail closed when untrusted orchestrator input attempts to own graph structure."""
    if orchestrator_type not in UNTRUSTED_ORCHESTRATORS:
        return
    for key in GRAPH_STRUCTURE_KEYS:
        if key in plan:
            raise KernelCompilationError(
                f"untrusted {orchestrator_type} content cannot supply graph structure: {key}"
            )
    spec = plan.get("spec")
    if isinstance(spec, Mapping) and any(
        field in spec for field in ("nodes", "edges", "resourceLimits", "verification")
    ):
        raise KernelCompilationError(
            f"untrusted {orchestrator_type} content cannot supply graph spec fields"
        )


def extract_untrusted_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the data-plane fields allowed from untrusted orchestrator input."""
    payload: dict[str, Any] = {}
    for key in UNTRUSTED_PAYLOAD_KEYS:
        if key in plan:
            payload[key] = plan[key]
    return payload


def resolve_graph_run_id(
    document: Mapping[str, Any],
    *,
    fallback_run_id: str,
) -> str:
    metadata = document.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("runId"):
        return str(metadata["runId"])
    return fallback_run_id


def sanitize_data_payloads(
    payloads: Mapping[str, Any],
    *,
    orchestrator: str | None,
) -> dict[str, Any]:
    """Admit untrusted payloads as data only; reject security-relevant keys (R3/R15)."""
    if not payloads:
        return {}
    if orchestrator not in UNTRUSTED_ORCHESTRATORS:
        return json.loads(json.dumps(payloads))

    sanitized: dict[str, Any] = {}
    for key, value in payloads.items():
        key_str = str(key)
        if key_str in SECURITY_RELEVANT_PAYLOAD_KEYS:
            raise KernelCompilationError(
                f"untrusted {orchestrator} content cannot set security field: {key_str}"
            )
        if isinstance(value, Mapping):
            banned = sorted(set(value) & SECURITY_RELEVANT_PAYLOAD_KEYS)
            if banned:
                raise KernelCompilationError(
                    f"untrusted {orchestrator} payload {key_str} sets "
                    f"security field(s): {', '.join(banned)}"
                )
        sanitized[key_str] = json.loads(json.dumps(value))
    return sanitized


def compile_workflow_graph(
    document: Mapping[str, Any],
    *,
    node_capabilities: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    declared_credentials: Iterable[str] = (),
    declared_side_effects: Iterable[str] = (),
    loop_bounds: Mapping[str, Mapping[str, int]] | None = None,
    transform_operators: Mapping[str, str] | None = None,
    proposed_steps: Sequence[str] | None = None,
    trusted_template: bool = True,
    orchestrator: str | None = None,
    data_payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and compile a graph to a non-executable, kernel-stamped artifact.

    Kernel compilation is the only admitted path onto GraphScheduler (R3).
    Untrusted debug/feedback content may populate ``data_payloads`` only.
    """
    if orchestrator in UNTRUSTED_ORCHESTRATORS:
        trusted_template = False
    try:
        graph = validate_workflow_graph(
            document, trusted_template=trusted_template
        )
    except WorkflowGraphValidationError as exc:
        raise KernelCompilationError(str(exc)) from exc

    sanitized_payloads = sanitize_data_payloads(
        data_payloads or {},
        orchestrator=orchestrator,
    )

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
    registered_transform_operators = _assert_transform_operators(
        graph, transform_operators
    )

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
        "transformOperatorCatalog": sorted(TRANSFORM_OPERATOR_NAMES),
        "transformOperators": registered_transform_operators,
        "trustedTemplate": trusted_template,
        "orchestrator": orchestrator,
        "dataPayloads": sanitized_payloads,
        "safetyKernelCalls": list(required_gates),
    }


def compile_orchestrator_graph(
    compilation: LegacyPlanCompilation,
    **kernel_options: Any,
) -> dict[str, Any]:
    """Compile an orchestrator LegacyPlanCompilation through the safety kernel (R3)."""
    orchestrator = compilation.plan_type
    assert_untrusted_payload_boundary(
        compilation.source_plan,
        orchestrator_type=orchestrator,
    )
    options = dict(kernel_options)
    options.setdefault("orchestrator", orchestrator)
    options.setdefault("data_payloads", compilation.untrusted_payload)
    if orchestrator in UNTRUSTED_ORCHESTRATORS:
        options["trusted_template"] = False
    return compile_workflow_graph(compilation.graph, **options)


def dispatch_compiled_graph(
    compiled: Mapping[str, Any],
    *,
    scheduler: GraphScheduler,
    run_id: str,
    internal_only: bool = True,
    external_authorization: ExternalDispatchAuthorization | None = None,
    **scheduler_options: Any,
) -> SchedulerRun:
    """Dispatch a kernel-compiled graph through GraphScheduler (R3 sole path)."""
    if "graphHash" not in compiled or "graph" not in compiled or "kernelVersion" not in compiled:
        raise KernelCompilationError(
            "scheduler dispatch requires a kernel-compiled artifact"
        )
    graph = compiled["graph"]
    graph_run_id = resolve_graph_run_id(graph, fallback_run_id=run_id)
    kernel_options = {
        "trusted_template": compiled.get("trustedTemplate", True),
        "orchestrator": compiled.get("orchestrator"),
        "data_payloads": compiled.get("dataPayloads") or {},
    }
    return scheduler.run(
        graph,
        run_id=graph_run_id,
        internal_only=internal_only,
        external_authorization=external_authorization,
        kernel_options=kernel_options,
        **scheduler_options,
    )


def compile_and_dispatch(
    document: Mapping[str, Any],
    *,
    scheduler: GraphScheduler,
    run_id: str,
    internal_only: bool = True,
    external_authorization: ExternalDispatchAuthorization | None = None,
    kernel_options: Mapping[str, Any] | None = None,
    **scheduler_options: Any,
) -> tuple[dict[str, Any], SchedulerRun]:
    """Kernel-compile then dispatch; the only supported production admission path."""
    compiled = compile_workflow_graph(document, **dict(kernel_options or {}))
    result = dispatch_compiled_graph(
        compiled,
        scheduler=scheduler,
        run_id=run_id,
        internal_only=internal_only,
        external_authorization=external_authorization,
        **scheduler_options,
    )
    return compiled, result
