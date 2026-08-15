#!/usr/bin/env python3
"""Fixed Quick-tier /sw-ship WorkflowGraph compiler (PRD 271 R7/R7a/R8/R27)."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from graph.ir import validate_workflow_graph
from graph.legacy_adapters import LegacyPlanCompilation, _node_id, _node_isolation, _node_resources
from kernel_classification import canonical_ship_chain, load_classification, normalize_step

PLAN_TYPE = "ship"
TOPOLOGY_SOURCE = "canonicalPhaseChains.sw-ship"
JUDGMENT_QUORUM = 1

GATE_STEPS = frozenset({"verification-gate", "gap-check"})
VERIFIER_STEPS = frozenset({"sw-review"})
AGENT_STEPS = frozenset({"sw-execute", "sw-review", "sw-simplify", "sw-stabilize"})
MECHANICAL_STEPS = frozenset(
    {
        "sw-tmp-init",
        "sw-tmp-clean",
        "sw-verify",
        "verification-gate",
        "behavioral-anomaly",
        "build-chain",
        "pre-pr-smoke",
        "decision-log",
        "gap-check",
        "sw-commit",
        "sw-pr",
        "sw-watch-ci",
        "sw-ready",
        "check-gate",
        "secret-scan",
    }
)

# R8 parity matrix — PR and no-PR paths share one fixed graph; gates stay unconditional.
QUICK_SHIP_PARITY_MATRIX: dict[str, Any] = {
    "version": 1,
    "resumeAuthority": "ship-steps.json",
    "rollbackMapping": {
        "graphNodeStep": "ship-steps.currentStep",
        "legacySubstrate": "ship_loop.step_dispatch until cutover evidence green",
    },
    "paths": {
        "withPr": {
            "terminal": "merge-ready-green",
            "merge": "never",
            "prSteps": ["sw-pr", "sw-watch-ci", "sw-stabilize", "sw-ready"],
            "readyGate": "unconditional",
            "verificationGate": "unconditional",
        },
        "noPr": {
            "terminal": "merge-ready-green",
            "merge": "never",
            "prSteps": ["sw-pr", "sw-watch-ci", "sw-stabilize", "sw-ready"],
            "readyGate": "unconditional",
            "verificationGate": "unconditional",
            "note": "PR steps still run; open PR may be absent until sw-pr creates one",
        },
    },
    "flags": {
        "--fast": {"skips": ["gap-check", "sw-simplify"], "mandatoryGates": "unchanged"},
        "--skip-local": {"skips": ["sw-review"], "mandatoryGates": "unchanged"},
        "--skip-simplify": {"skips": ["sw-simplify"], "mandatoryGates": "unchanged"},
    },
    "retries": {"agentAttemptBudget": 2, "resume": "--from <step> or ship-steps.json"},
    "cutover": {
        "legacySubstrateRemoval": "after R8 dogfood evidence only",
        "adaptiveSelection": "deferred to PRD 272 — rejected here",
    },
}


@dataclass(frozen=True)
class QuickShipCompileOptions:
    run_id: str
    phase_slug: str = ""
    resume_step: str | None = None
    has_pr: bool | None = None


def fixed_quick_ship_steps(root: Path | None = None) -> list[str]:
    """Return the config-declared Quick ship chain — never adaptive PRD 272 selection."""
    return canonical_ship_chain(root or Path.cwd())


def assert_topology_fixed(plan: Mapping[str, Any]) -> None:
    """Reject adaptive / PRD-272-style plan mutation on Quick ship."""
    if plan.get("adaptiveSelection") is True:
        raise ValueError("quick ship rejects adaptive capability selection (PRD 272)")
    topology = plan.get("topology")
    if isinstance(topology, Mapping) and topology.get("adaptiveSelection") is True:
        raise ValueError("quick ship rejects adaptive topology selection (PRD 272)")
    if plan.get("partialOrder") or plan.get("waves"):
        raise ValueError("quick ship rejects adaptive partial-order plans")


def _node_kind(step: str) -> str:
    if step in GATE_STEPS:
        return "gate"
    if step in VERIFIER_STEPS:
        return "verifier"
    return "command"


def _verification_strategy(step: str) -> str:
    if step in VERIFIER_STEPS:
        return "judgment"
    if step in GATE_STEPS:
        return "mechanical"
    return "mechanical"


def _node_target(step: str) -> dict[str, Any]:
    target: dict[str, Any] = {"step": step}
    data: dict[str, Any] = {}
    if step == "sw-ready":
        data["humanMergeGate"] = True
    if step in VERIFIER_STEPS:
        data["independenceFloor"] = JUDGMENT_QUORUM
    if data:
        target["data"] = data
    return target


def build_quick_ship_plan(
    root: Path,
    options: QuickShipCompileOptions,
) -> dict[str, Any]:
    steps = fixed_quick_ship_steps(root)
    resume = normalize_step(options.resume_step or steps[0])
    if resume not in steps:
        raise ValueError(f"resume step not in quick ship chain: {resume!r}")
    plan: dict[str, Any] = {
        "version": 1,
        "planType": "quick-ship",
        "runId": options.run_id,
        "phaseSlug": options.phase_slug,
        "steps": list(steps),
        "topology": {
            "fixed": True,
            "adaptiveSelection": False,
            "source": TOPOLOGY_SOURCE,
        },
        "safety": {
            "humanMergeGate": True,
            "lockOwner": options.run_id,
            "resumeCursor": resume,
            "mergeQueue": [],
            "contentionSerialized": [],
        },
        "maxConcurrency": 1,
        "parity": copy.deepcopy(QUICK_SHIP_PARITY_MATRIX),
    }
    if options.has_pr is not None:
        plan["parity"]["activePath"] = "withPr" if options.has_pr else "noPr"
    assert_topology_fixed(plan)
    return plan


def compile_quick_ship_graph(
    root: Path,
    options: QuickShipCompileOptions,
) -> LegacyPlanCompilation:
    """Compile Quick /sw-ship to a fixed WorkflowGraph through merge-ready (never merges)."""
    plan = build_quick_ship_plan(root, options)
    steps = [(str(index), command) for index, command in enumerate(plan["steps"])]
    node_ids = [_node_id(identifier, index) for index, (identifier, _) in enumerate(steps)]
    nodes = [
        {
            "id": node_id,
            "kind": _node_kind(command),
            "target": _node_target(command),
            "resources": _node_resources(command),
            "isolation": _node_isolation(command, PLAN_TYPE),
            "verification": {
                "required": True,
                "strategy": _verification_strategy(command),
            },
        }
        for node_id, (_, command) in zip(node_ids, steps, strict=True)
    ]
    edges = [
        {"from": source, "to": target, "required": True}
        for source, target in zip(node_ids, node_ids[1:], strict=False)
    ]
    metadata: dict[str, Any] = {
        "name": "quick-sw-ship",
        "orchestratorType": "ship",
        "durability": "durable",
        "runId": options.run_id,
    }
    if options.phase_slug:
        metadata["phaseId"] = options.phase_slug
    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": metadata,
        "spec": {
            "nodes": nodes,
            "edges": edges,
            "resourceLimits": {
                "maxConcurrency": 1,
                "maxDurationSeconds": max(1, int(plan.get("maxDurationSeconds", 86400))),
            },
            "verification": {"required": True, "failClosed": True},
        },
    }
    validated = validate_workflow_graph(graph)
    _assert_lifecycle_parity(validated, plan["steps"], plan)
    return LegacyPlanCompilation(
        plan_type=PLAN_TYPE,
        graph=validated,
        source_plan=plan,
        untrusted_payload={},
    )


def _assert_lifecycle_parity(
    graph: Mapping[str, Any],
    steps: list[str],
    plan: Mapping[str, Any],
) -> None:
    ordered_steps = tuple(str(node["target"]["step"]) for node in graph["spec"]["nodes"])
    if ordered_steps != tuple(steps):
        raise ValueError("quick ship graph lost lifecycle step parity")
    required_tail = (
        "sw-execute",
        "sw-verify",
        "verification-gate",
        "sw-review",
        "gap-check",
        "sw-commit",
        "sw-pr",
        "sw-watch-ci",
        "sw-stabilize",
        "sw-ready",
    )
    positions = {step: index for index, step in enumerate(ordered_steps)}
    last = -1
    for step in required_tail:
        if step not in positions:
            raise ValueError(f"quick ship lifecycle missing required step: {step}")
        if positions[step] < last:
            raise ValueError(f"quick ship lifecycle order violated at {step}")
        last = positions[step]
    if not plan.get("safety", {}).get("humanMergeGate"):
        raise ValueError("quick ship must retain human merge gate (never auto-merge)")


def compile_quick_ship_kernel(
    root: Path,
    options: QuickShipCompileOptions,
    **kernel_options: Any,
) -> dict[str, Any]:
    from graph.kernel_compiler import compile_orchestrator_graph

    compilation = compile_quick_ship_graph(root, options)
    return compile_orchestrator_graph(
        compilation,
        proposed_steps=fixed_quick_ship_steps(root),
        **kernel_options,
    )


def graph_step_for_ship_step(step: str) -> str:
    """Map ship-loop step names to graph node target steps (identity for Quick ship)."""
    return normalize_step(step)


def resume_step_from_ship_steps(doc: Mapping[str, Any], chain: list[str]) -> str:
    """ship-steps.json is the sole resume authority for Quick ship (R8)."""
    current = normalize_step(str(doc.get("currentStep") or ""))
    if current and current in chain:
        return current
    return chain[0] if chain else "sw-tmp-init"


def parity_matrix_for_path(*, has_pr: bool) -> Mapping[str, Any]:
    key = "withPr" if has_pr else "noPr"
    return QUICK_SHIP_PARITY_MATRIX["paths"][key]


def classification_fingerprint(root: Path) -> str:
    data = load_classification(root)
    return str(data.get("kernelVersion", ""))
