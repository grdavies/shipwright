#!/usr/bin/env python3
"""Temporary, lossless bridges from legacy plan JSON into WorkflowGraph."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from graph.ir import validate_workflow_graph

SUPPORTED_PLAN_TYPES = frozenset(
    {"delivery", "execute", "ship", "doc", "debug", "feedback"}
)
ORCHESTRATOR_PLAN_TYPES = frozenset({"doc", "debug", "feedback"})
EPISODIC_ORCHESTRATORS = frozenset({"debug", "feedback"})
REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_PLAN_PATH = REPO_ROOT / "core" / "sw-reference" / "orchestrator-step-plan.json"
UNTRUSTED_PAYLOAD_KEYS = frozenset(
    {"signal_context", "signals", "payload", "data", "rawSignal", "raw_signal"}
)


# Per-orchestrator halt / confirmation / redaction / dispatch / durability contracts (R3).
ORCHESTRATOR_CONTRACTS: dict[str, dict[str, Any]] = {
    "delivery": {
        "humanHalt": "human-merge-gate",
        "confirmationToken": "merge-ready-green",
        "redactionBoundary": "status-telemetry-before-emit",
        "dispatchBoundary": "phase-executor",
        "durabilityRule": "runId-keyed-receipts",
        "safetyKernelCalls": (
            "verification-gate",
            "wave-lock",
            "human-merge-gate",
        ),
    },
    "doc": {
        "humanHalt": "afterTasks-checkpoint",
        "confirmationToken": "doc-review-halt",
        "redactionBoundary": "planning-visibility-before-emit",
        "dispatchBoundary": "doc-orchestrator-enqueue-only",
        "durabilityRule": "runId-keyed-receipts",
        "safetyKernelCalls": (
            "verification-gate",
            "memory-prework",
            "freeze-prd",
        ),
    },
    "debug": {
        "humanHalt": "route-confirm-halt",
        "confirmationToken": "rca-human-decision-halt",
        "redactionBoundary": "untrusted-payload-data-only",
        "dispatchBoundary": "debug-route-handoff",
        "durabilityRule": "runId-keyed-receipts",
        "safetyKernelCalls": (
            "verification-gate",
            "memory-prework",
            "route-confirm-halt",
        ),
    },
    "feedback": {
        "humanHalt": "human-confirm-halt",
        "confirmationToken": "hook-trigger-halt",
        "redactionBoundary": "untrusted-payload-data-only",
        "dispatchBoundary": "feedback-route-handoff",
        "durabilityRule": "runId-keyed-receipts",
        "safetyKernelCalls": (
            "verification-gate",
            "memory-prework",
            "redact",
        ),
    },
}


@dataclass(frozen=True)
class LegacyPlanCompilation:
    """Graph plus immutable source envelope needed for a lossless reverse bridge."""

    plan_type: str
    graph: dict[str, Any]
    source_plan: dict[str, Any]
    untrusted_payload: dict[str, Any]

    @property
    def run_id(self) -> str:
        raw = self.graph.get("metadata", {}).get("runId")
        return str(raw) if raw else ""

    @property
    def contracts(self) -> dict[str, Any]:
        key = self.plan_type if self.plan_type in ORCHESTRATOR_CONTRACTS else "delivery"
        return dict(ORCHESTRATOR_CONTRACTS[key])


def _node_id(value: str, index: int) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"step-{index}"
    return normalized[:55] + f"-{index}"


@lru_cache(maxsize=1)
def _orchestrator_plan_catalog() -> dict[str, Any]:
    try:
        data = json.loads(ORCHESTRATOR_PLAN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load orchestrator step plan: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("orchestrator step plan must be an object")
    return data


def _orchestrator_ordering_invariants(orchestrator_type: str) -> list[dict[str, str]]:
    catalog = _orchestrator_plan_catalog()
    spec = (catalog.get("orchestratorTypes") or {}).get(orchestrator_type)
    if not isinstance(spec, dict):
        return []
    invariants: list[dict[str, str]] = []
    for raw in spec.get("orderingInvariants") or []:
        if not isinstance(raw, dict):
            continue
        before = raw.get("before")
        after = raw.get("after")
        if isinstance(before, str) and isinstance(after, str):
            invariants.append({"before": before, "after": after})
    return invariants


def _extract_untrusted_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in UNTRUSTED_PAYLOAD_KEYS:
        if key in plan:
            payload[key] = copy.deepcopy(plan[key])
    return payload


def _resolve_run_id(plan: Mapping[str, Any], plan_type: str) -> str | None:
    for key in ("runId", "run_id"):
        raw = plan.get(key)
        if raw:
            return str(raw)
    if plan_type == "delivery":
        safety = plan.get("safety")
        if isinstance(safety, Mapping) and safety.get("lockOwner"):
            return str(safety["lockOwner"])
    orchestrator_id = plan.get("orchestratorId")
    if orchestrator_id:
        return str(orchestrator_id)
    return None


def _step_kind(step: str) -> str:
    if "halt" in step:
        return "gate"
    if step == "route":
        return "router"
    return "command"


def _steps(plan: Mapping[str, Any], plan_type: str) -> list[tuple[str, str]]:
    if plan_type in ORCHESTRATOR_PLAN_TYPES:
        raw_steps = plan.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError(f"{plan_type} orchestrator plan has no steps")
        return [
            (
                str(step),
                str(step),
            )
            for step in raw_steps
        ]
    if plan_type == "delivery":
        waves = plan.get("waves")
        if isinstance(waves, list) and waves:
            ordered: list[tuple[str, str]] = []
            seen: set[str] = set()
            for wave in waves:
                if not isinstance(wave, list):
                    continue
                for phase in wave:
                    identifier = str(phase)
                    if identifier in seen:
                        continue
                    seen.add(identifier)
                    slug = identifier
                    phases = plan.get("phases")
                    if isinstance(phases, list):
                        for entry in phases:
                            if not isinstance(entry, Mapping):
                                continue
                            pid = str(entry.get("id", ""))
                            if pid == identifier:
                                slug = str(
                                    entry.get("slug")
                                    or entry.get("name")
                                    or entry.get("id", identifier)
                                )
                                break
                    ordered.append((identifier, slug))
            if ordered:
                return ordered
        phases = plan.get("phases")
        if isinstance(phases, list):
            return [
                (
                    str(phase.get("id", index)),
                    str(phase.get("slug") or phase.get("name") or phase.get("id", index)),
                )
                for index, phase in enumerate(phases)
                if isinstance(phase, Mapping)
            ]
    raw_steps = plan.get("steps")
    if isinstance(raw_steps, list):
        return [
            (
                str(step.get("id", index)) if isinstance(step, Mapping) else str(index),
                str(step.get("command") or step.get("name") or step.get("id", index))
                if isinstance(step, Mapping)
                else str(step),
            )
            for index, step in enumerate(raw_steps)
        ]
    raise ValueError(f"{plan_type} plan has no supported steps")


def _edges_from_explicit(
    plan: Mapping[str, Any],
    step_to_node: Mapping[str, str],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for raw in plan.get("edges") or []:
        if not isinstance(raw, Mapping):
            continue
        source = str(raw.get("from", ""))
        target = str(raw.get("to", ""))
        if source not in step_to_node or target not in step_to_node:
            continue
        edges.append(
            {
                "from": step_to_node[source],
                "to": step_to_node[target],
                "required": raw.get("required", True) is not False,
            }
        )
    return edges


def _edges_from_waves(
    waves: list[list[str]],
    step_to_node: Mapping[str, str],
) -> list[dict[str, Any]]:
    if len(waves) < 2:
        return []
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for wave_index in range(1, len(waves)):
        previous = [str(item) for item in waves[wave_index - 1]]
        current = [str(item) for item in waves[wave_index]]
        for source in previous:
            if source not in step_to_node:
                continue
            for target in current:
                if target not in step_to_node:
                    continue
                key = (step_to_node[source], step_to_node[target])
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "from": key[0],
                        "to": key[1],
                        "required": True,
                    }
                )
    return edges


def _edges_from_ordering(
    steps: list[str],
    invariants: list[Mapping[str, Any]],
    step_to_node: Mapping[str, str],
) -> list[dict[str, Any]]:
    positions = {step: index for index, step in enumerate(steps)}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in invariants:
        before = str(raw.get("before", ""))
        after = str(raw.get("after", ""))
        if before not in positions or after not in positions:
            continue
        if positions[before] >= positions[after]:
            continue
        key = (step_to_node[before], step_to_node[after])
        if key in seen:
            continue
        seen.add(key)
        edges.append({"from": key[0], "to": key[1], "required": True})
    return edges


def _edges_from_serial(node_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {"from": source, "to": target, "required": True}
        for source, target in zip(node_ids, node_ids[1:], strict=False)
    ]


def _compile_edges(
    plan: Mapping[str, Any],
    plan_type: str,
    steps: list[tuple[str, str]],
    node_ids: list[str],
) -> list[dict[str, Any]]:
    step_names = [command for _, command in steps]
    step_to_node = {
        identifier: node_id
        for (identifier, _), node_id in zip(steps, node_ids, strict=True)
    }
    step_to_node.update(
        {
            command: node_id
            for (_, command), node_id in zip(steps, node_ids, strict=True)
        }
    )

    explicit = _edges_from_explicit(plan, step_to_node)
    if explicit:
        return explicit

    waves = plan.get("waves")
    if isinstance(waves, list) and waves:
        wave_edges = _edges_from_waves(
            [[str(item) for item in wave] for wave in waves if isinstance(wave, list)],
            step_to_node,
        )
        if wave_edges:
            return wave_edges

    partial_order = plan.get("partialOrder")
    invariants: list[Mapping[str, Any]] = []
    if isinstance(partial_order, list):
        invariants.extend(item for item in partial_order if isinstance(item, Mapping))
    if plan_type in ORCHESTRATOR_PLAN_TYPES:
        invariants.extend(_orchestrator_ordering_invariants(plan_type))
    ordering_edges = _edges_from_ordering(step_names, invariants, step_to_node)
    if ordering_edges:
        return ordering_edges

    return _edges_from_serial(node_ids)


def _max_concurrency(plan: Mapping[str, Any], steps: list[tuple[str, str]]) -> int:
    raw = plan.get("maxConcurrency")
    if raw is not None:
        try:
            return max(1, min(16, int(raw)))
        except (TypeError, ValueError):
            pass
    waves = plan.get("waves")
    if isinstance(waves, list) and waves:
        try:
            return max(1, min(16, max(len(wave) for wave in waves if isinstance(wave, list))))
        except ValueError:
            pass
    parallel_ceiling = plan.get("parallelCeiling")
    if parallel_ceiling is not None:
        try:
            return max(1, min(16, int(parallel_ceiling)))
        except (TypeError, ValueError):
            pass
    return max(1, min(16, len(steps)))


def _node_resources(step: str) -> dict[str, Any]:
    if step in {"memory-prework", "triage", "normalize", "redact", "dedup"}:
        return {
            "pool": "read-only-reviewers",
            "slots": 1,
            "timeoutSeconds": 1800,
        }
    return {
        "pool": "code-writers",
        "slots": 1,
        "timeoutSeconds": 3600,
    }


def _node_isolation(step: str, plan_type: str) -> dict[str, str]:
    if plan_type in EPISODIC_ORCHESTRATORS and step in {
        "memory-prework",
        "triage",
        "normalize",
        "redact",
        "dedup",
        "record",
    }:
        return {"mode": "process", "writeScope": "scoped"}
    if step in {"memory-prework", "triage", "normalize", "redact", "dedup"}:
        return {"mode": "process", "writeScope": "read-only"}
    return {"mode": "worktree", "writeScope": "worktree"}


def _attach_payload(
    target: dict[str, Any],
    *,
    step: str,
    plan_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if plan_type not in EPISODIC_ORCHESTRATORS or not payload:
        return target
    if step not in {"normalize", "redact", "route", "rca", "record"}:
        return target
    merged = dict(target)
    merged["data"] = copy.deepcopy(dict(payload))
    return merged


def compile_legacy_plan(
    plan: Mapping[str, Any],
    *,
    plan_type: str,
) -> LegacyPlanCompilation:
    """Compile a legacy plan without weakening or discarding its source constraints."""
    if plan_type not in SUPPORTED_PLAN_TYPES:
        raise ValueError(f"unsupported legacy plan type: {plan_type}")
    if plan_type in ORCHESTRATOR_PLAN_TYPES:
        declared = str(plan.get("orchestratorType") or plan_type)
        if declared != plan_type:
            raise ValueError(
                f"orchestratorType {declared!r} does not match plan_type {plan_type!r}"
            )
    steps = _steps(plan, plan_type)
    if not steps:
        raise ValueError("legacy plan must contain at least one step")
    untrusted_payload = _extract_untrusted_payload(plan)
    node_ids = [_node_id(identifier, index) for index, (identifier, _) in enumerate(steps)]
    nodes = [
        {
            "id": node_id,
            "kind": _step_kind(command),
            "target": _attach_payload(
                {"step": command},
                step=command,
                plan_type=plan_type,
                payload=untrusted_payload,
            ),
            "resources": _node_resources(command),
            "isolation": _node_isolation(command, plan_type),
            "verification": {"required": True, "strategy": "mechanical"},
        }
        for node_id, (_, command) in zip(node_ids, steps, strict=True)
    ]
    edges = _compile_edges(plan, plan_type, steps, node_ids)
    metadata: dict[str, Any] = {
        "name": f"legacy-{plan_type}-adapter",
    }
    run_id = _resolve_run_id(plan, plan_type)
    if run_id:
        metadata["runId"] = run_id
    if plan_type in ORCHESTRATOR_PLAN_TYPES:
        metadata["orchestratorType"] = plan_type
        metadata["durability"] = (
            "episodic" if plan_type in EPISODIC_ORCHESTRATORS else "durable"
        )
    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": metadata,
        "spec": {
            "nodes": nodes,
            "edges": edges,
            "resourceLimits": {
                "maxConcurrency": _max_concurrency(plan, steps),
                "maxDurationSeconds": max(
                    1, int(plan.get("maxDurationSeconds", 86400))
                ),
            },
            "verification": {"required": True, "failClosed": True},
        },
    }
    return LegacyPlanCompilation(
        plan_type=plan_type,
        graph=validate_workflow_graph(graph),
        source_plan=copy.deepcopy(dict(plan)),
        untrusted_payload=untrusted_payload,
    )


def restore_legacy_plan(compilation: LegacyPlanCompilation) -> dict[str, Any]:
    """Reverse the temporary bridge losslessly after checking the graph remains valid."""
    validate_workflow_graph(compilation.graph)
    if compilation.plan_type not in SUPPORTED_PLAN_TYPES:
        raise ValueError("adapter compilation has an unsupported plan type")
    return copy.deepcopy(compilation.source_plan)


def delivery_plan_to_workflow_graph(plan: Mapping[str, Any]) -> LegacyPlanCompilation:
    return compile_legacy_plan(plan, plan_type="delivery")


def execute_plan_to_workflow_graph(plan: Mapping[str, Any]) -> LegacyPlanCompilation:
    return compile_legacy_plan(plan, plan_type="execute")


def ship_plan_to_workflow_graph(plan: Mapping[str, Any]) -> LegacyPlanCompilation:
    return compile_legacy_plan(plan, plan_type="ship")


def orchestrator_plan_to_workflow_graph(
    plan: Mapping[str, Any],
    *,
    orchestrator_type: str,
) -> LegacyPlanCompilation:
    return compile_legacy_plan(plan, plan_type=orchestrator_type)


def doc_plan_to_workflow_graph(plan: Mapping[str, Any]) -> LegacyPlanCompilation:
    return compile_legacy_plan(plan, plan_type="doc")


def debug_plan_to_workflow_graph(plan: Mapping[str, Any]) -> LegacyPlanCompilation:
    return compile_legacy_plan(plan, plan_type="debug")


def feedback_plan_to_workflow_graph(plan: Mapping[str, Any]) -> LegacyPlanCompilation:
    return compile_legacy_plan(plan, plan_type="feedback")
