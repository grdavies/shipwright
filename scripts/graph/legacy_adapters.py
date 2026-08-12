#!/usr/bin/env python3
"""Temporary, lossless bridges from legacy plan JSON into WorkflowGraph."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping

from graph.ir import validate_workflow_graph

SUPPORTED_PLAN_TYPES = frozenset({"delivery", "execute", "ship"})


@dataclass(frozen=True)
class LegacyPlanCompilation:
    """Graph plus immutable source envelope needed for a lossless reverse bridge."""

    plan_type: str
    graph: dict[str, Any]
    source_plan: dict[str, Any]


def _node_id(value: str, index: int) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"step-{index}"
    return normalized[:55] + f"-{index}"


def _steps(plan: Mapping[str, Any], plan_type: str) -> list[tuple[str, str]]:
    if plan_type == "delivery":
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


def compile_legacy_plan(
    plan: Mapping[str, Any],
    *,
    plan_type: str,
) -> LegacyPlanCompilation:
    """Compile a legacy plan without weakening or discarding its source constraints."""
    if plan_type not in SUPPORTED_PLAN_TYPES:
        raise ValueError(f"unsupported legacy plan type: {plan_type}")
    steps = _steps(plan, plan_type)
    if not steps:
        raise ValueError("legacy plan must contain at least one step")
    node_ids = [_node_id(identifier, index) for index, (identifier, _) in enumerate(steps)]
    nodes = [
        {
            "id": node_id,
            "kind": "command",
            "target": {"step": command},
            "resources": {
                "pool": "code-writers",
                "slots": 1,
                "timeoutSeconds": 3600,
            },
            "isolation": {"mode": "worktree", "writeScope": "worktree"},
            "verification": {"required": True, "strategy": "mechanical"},
        }
        for node_id, (_, command) in zip(node_ids, steps, strict=True)
    ]
    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": f"legacy-{plan_type}-adapter"},
        "spec": {
            "nodes": nodes,
            "edges": [
                {"from": source, "to": target, "required": True}
                for source, target in zip(node_ids, node_ids[1:])
            ],
            "resourceLimits": {
                "maxConcurrency": max(1, min(16, int(plan.get("maxConcurrency", 1)))),
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
