#!/usr/bin/env python3
"""Compile WorkflowGraph IR through Shipwright's deterministic safety kernel."""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from graph.ir import (
    NODE_SCHEMA_PATH,
    WORKFLOW_SCHEMA_PATH,
    WorkflowGraphValidationError,
    validate_workflow_graph,
)
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
POLICY_CLASS_OPTIMIZABLE = "optimizable"
POLICY_CLASS_IMMUTABLE = "immutable"
_POLICY_CLASSES = frozenset({POLICY_CLASS_OPTIMIZABLE, POLICY_CLASS_IMMUTABLE})
# Deny-by-default: any field not marked optimizable is immutable. Every schema
# property and compile_workflow_graph option must have an explicit entry.
GRAPH_POLICY_FIELD_CLASSIFICATION: dict[str, str] = {
    "apiVersion": POLICY_CLASS_IMMUTABLE,
    "kind": POLICY_CLASS_IMMUTABLE,
    "metadata": POLICY_CLASS_IMMUTABLE,
    "metadata.name": POLICY_CLASS_OPTIMIZABLE,
    "metadata.phaseId": POLICY_CLASS_OPTIMIZABLE,
    "metadata.runId": POLICY_CLASS_IMMUTABLE,
    "metadata.orchestratorType": POLICY_CLASS_IMMUTABLE,
    "metadata.durability": POLICY_CLASS_IMMUTABLE,
    "spec": POLICY_CLASS_IMMUTABLE,
    "spec.nodes": POLICY_CLASS_OPTIMIZABLE,
    "spec.edges": POLICY_CLASS_OPTIMIZABLE,
    "spec.edges[].from": POLICY_CLASS_OPTIMIZABLE,
    "spec.edges[].to": POLICY_CLASS_OPTIMIZABLE,
    "spec.edges[].required": POLICY_CLASS_OPTIMIZABLE,
    "spec.resourceLimits": POLICY_CLASS_IMMUTABLE,
    "spec.resourceLimits.maxConcurrency": POLICY_CLASS_OPTIMIZABLE,
    "spec.resourceLimits.maxDurationSeconds": POLICY_CLASS_OPTIMIZABLE,
    "spec.verification": POLICY_CLASS_IMMUTABLE,
    "spec.verification.required": POLICY_CLASS_IMMUTABLE,
    "spec.verification.failClosed": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].id": POLICY_CLASS_OPTIMIZABLE,
    "spec.nodes[].kind": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].target": POLICY_CLASS_OPTIMIZABLE,
    "spec.nodes[].target.step": POLICY_CLASS_OPTIMIZABLE,
    "spec.nodes[].target.data": POLICY_CLASS_OPTIMIZABLE,
    "spec.nodes[].resources": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].resources.pool": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].resources.slots": POLICY_CLASS_OPTIMIZABLE,
    "spec.nodes[].resources.timeoutSeconds": POLICY_CLASS_OPTIMIZABLE,
    "spec.nodes[].isolation": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].isolation.mode": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].isolation.writeScope": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].verification": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].verification.required": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].verification.strategy": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution.purity": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution.cache": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution.templateDigest": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution.trust": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution.trust.trustDomain": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution.trust.repositoryIdentity": POLICY_CLASS_IMMUTABLE,
    "spec.nodes[].execution.trust.toolBinaryIdentity": POLICY_CLASS_IMMUTABLE,
}
KERNEL_COMPILER_OPTION_FIELDS: dict[str, str] = {
    "node_capabilities": POLICY_CLASS_IMMUTABLE,
    "declared_credentials": POLICY_CLASS_IMMUTABLE,
    "declared_side_effects": POLICY_CLASS_IMMUTABLE,
    "loop_bounds": POLICY_CLASS_IMMUTABLE,
    "transform_operators": POLICY_CLASS_IMMUTABLE,
    "proposed_steps": POLICY_CLASS_IMMUTABLE,
    "trusted_template": POLICY_CLASS_IMMUTABLE,
    "orchestrator": POLICY_CLASS_IMMUTABLE,
    "data_payloads": POLICY_CLASS_OPTIMIZABLE,
}


class KernelCompilationError(ValueError):
    """Raised when a graph attempts to bypass a safety-kernel constraint."""


def _validated_policy_class(value: str, path: str) -> str:
    if value not in _POLICY_CLASSES:
        raise KernelCompilationError(
            f"invalid classification for kernel-compiler policy field {path}: {value}"
        )
    return value


def _schema_field_paths(
    schema: Mapping[str, Any],
    *,
    prefix: str = "",
    node_schema: Mapping[str, Any] | None = None,
) -> set[str]:
    paths: set[str] = set()
    if "$ref" in schema and node_schema is not None:
        return _schema_field_paths(node_schema, prefix=prefix, node_schema=node_schema)
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return paths
    for name, child in properties.items():
        path = f"{prefix}.{name}" if prefix else str(name)
        paths.add(path)
        if not isinstance(child, Mapping):
            continue
        if "$ref" in child and node_schema is not None:
            paths.update(
                _schema_field_paths(node_schema, prefix=path, node_schema=node_schema)
            )
            continue
        paths.update(_schema_field_paths(child, prefix=path, node_schema=node_schema))
        items = child.get("items")
        if isinstance(items, Mapping):
            item_prefix = f"{path}[]"
            if "$ref" in items and node_schema is not None:
                paths.update(
                    _schema_field_paths(
                        node_schema, prefix=item_prefix, node_schema=node_schema
                    )
                )
            else:
                paths.update(
                    _schema_field_paths(
                        items, prefix=item_prefix, node_schema=node_schema
                    )
                )
    return paths


def _parent_policy_paths(path: str) -> list[str]:
    parents: list[str] = []
    current = path
    while current:
        if current.endswith("[]"):
            current = current[:-2]
        elif "." in current:
            current = current.rsplit(".", 1)[0]
        else:
            break
        if current:
            parents.append(current)
    return parents


def classify_policy_field(path: str) -> str:
    """Return optimizable or immutable. Unclassified paths fail closed."""
    if path in GRAPH_POLICY_FIELD_CLASSIFICATION:
        return _validated_policy_class(GRAPH_POLICY_FIELD_CLASSIFICATION[path], path)
    if path in KERNEL_COMPILER_OPTION_FIELDS:
        return _validated_policy_class(KERNEL_COMPILER_OPTION_FIELDS[path], path)
    for parent in _parent_policy_paths(path):
        if parent in GRAPH_POLICY_FIELD_CLASSIFICATION:
            parent_class = GRAPH_POLICY_FIELD_CLASSIFICATION[parent]
            if parent_class == POLICY_CLASS_OPTIMIZABLE:
                return POLICY_CLASS_OPTIMIZABLE
            raise KernelCompilationError(
                f"unclassified kernel-compiler policy field: {path}"
            )
    raise KernelCompilationError(f"unclassified kernel-compiler policy field: {path}")


def _compiler_option_names() -> tuple[str, ...]:
    params = inspect.signature(compile_workflow_graph).parameters
    return tuple(
        name
        for name, param in params.items()
        if name != "document" and param.kind is not inspect.Parameter.VAR_KEYWORD
    )


def _document_field_paths(value: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths.update(_document_field_paths(child, path))
        return paths
    if isinstance(value, list):
        item_prefix = f"{prefix}[]"
        for item in value:
            if isinstance(item, (Mapping, list)):
                paths.update(_document_field_paths(item, item_prefix))
    return paths


def assert_document_policy_fields_classified(document: Mapping[str, Any]) -> None:
    """Fail closed when a live document carries an unclassified policy field."""
    for path in sorted(_document_field_paths(document)):
        classify_policy_field(path)


@functools.lru_cache(maxsize=1)
def assert_policy_schema_coverage() -> None:
    """CI fails when a schema or compiler option ships without classification."""
    try:
        workflow_schema = json.loads(WORKFLOW_SCHEMA_PATH.read_text(encoding="utf-8"))
        node_schema = json.loads(NODE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KernelCompilationError(
            f"cannot load workflow schemas for policy classification: {exc}"
        ) from exc
    schema_paths = _schema_field_paths(workflow_schema, node_schema=node_schema)
    classified = set(GRAPH_POLICY_FIELD_CLASSIFICATION)
    missing = sorted(schema_paths - classified)
    extra = sorted(classified - schema_paths)
    if missing or extra:
        details = []
        if missing:
            details.append("unclassified=" + ", ".join(missing))
        if extra:
            details.append("unknown=" + ", ".join(extra))
        raise KernelCompilationError(
            "kernel-compiler policy field classification drift: "
            + "; ".join(details)
        )
    option_names = set(_compiler_option_names())
    classified_options = set(KERNEL_COMPILER_OPTION_FIELDS)
    missing_opts = sorted(option_names - classified_options)
    extra_opts = sorted(classified_options - option_names)
    if missing_opts or extra_opts:
        details = []
        if missing_opts:
            details.append("unclassified-options=" + ", ".join(missing_opts))
        if extra_opts:
            details.append("unknown-options=" + ", ".join(extra_opts))
        raise KernelCompilationError(
            "kernel-compiler option classification drift: " + "; ".join(details)
        )


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

    assert_policy_schema_coverage()
    assert_document_policy_fields_classified(graph)

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
