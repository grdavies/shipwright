#!/usr/bin/env python3
"""Guarded WorkflowGraph proposals with deterministic canonical fallback."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from graph.cutover import CutoverStage, DogfoodEvidence
from graph.kernel_compiler import KernelCompilationError, compile_workflow_graph


class DynamicProposalError(ValueError):
    """Raised when the canonical fallback itself is not safe to compile."""


@dataclass(frozen=True)
class ProposalBudget:
    """Hard limits applied before a proposed graph reaches the scheduler."""

    max_nodes: int
    max_edges: int
    max_concurrency: int
    max_duration_seconds: int
    max_total_slots: int

    def __post_init__(self) -> None:
        for name, value in (
            ("max_nodes", self.max_nodes),
            ("max_edges", self.max_edges),
            ("max_concurrency", self.max_concurrency),
            ("max_duration_seconds", self.max_duration_seconds),
            ("max_total_slots", self.max_total_slots),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ProposalDecision:
    """A proposal verdict containing only validated graph data, never code."""

    verdict: str
    graph: Mapping[str, Any]
    compiled: Mapping[str, Any]
    used_fallback: bool
    reason: str


REQUIRED_CAPABILITY_KINDS = frozenset({"gate", "verifier"})
REQUIRED_CAPABILITY_TOKENS = (
    "merge-gate",
    "human-merge-gate",
    "human-terminal-merge-gate",
    "credential-broker",
    "write-isolation-lease",
    "mechanical-verification",
    "verification-gate",
)


def is_required_capability_node(node: Mapping[str, Any]) -> bool:
    """True for merge-gate, verifier, credential-broker, and isolation-lease nodes."""
    kind = str(node.get("kind") or "")
    if kind in REQUIRED_CAPABILITY_KINDS:
        return True
    node_id = str(node.get("id") or "")
    step = str((node.get("target") or {}).get("step") or "")
    blob = f"{node_id} {step}"
    return any(token in blob for token in REQUIRED_CAPABILITY_TOKENS)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def host_slot_total(document: Mapping[str, Any]) -> int:
    """Sum of node resource slots — host-level accounting, not per-pool."""
    try:
        nodes = document["spec"]["nodes"]
        return sum(int(node["resources"]["slots"]) for node in nodes)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("proposal host-slot inputs are malformed") from exc


def _assert_required_capability_invariant(
    proposal: Mapping[str, Any],
    canonical_graph: Mapping[str, Any],
) -> None:
    canonical_nodes = {
        str(node["id"]): node for node in canonical_graph["spec"]["nodes"]
    }
    proposal_nodes = {str(node["id"]): node for node in proposal["spec"]["nodes"]}
    for node_id, canonical_node in canonical_nodes.items():
        if not is_required_capability_node(canonical_node):
            continue
        proposed = proposal_nodes.get(node_id)
        if proposed is None:
            raise ValueError(
                f"proposal rejected: required-capability node {node_id} missing"
            )
        if _canonical_bytes(proposed) != _canonical_bytes(canonical_node):
            raise ValueError(
                "proposal rejected: required-capability node "
                f"{node_id} must stay byte-identical"
            )

    canonical_slots = host_slot_total(canonical_graph)
    proposed_slots = host_slot_total(proposal)
    if proposed_slots > canonical_slots:
        raise ValueError(
            f"proposal rejected: host slots {proposed_slots}>{canonical_slots}"
        )

    canonical_concurrency = int(
        canonical_graph["spec"]["resourceLimits"]["maxConcurrency"]
    )
    proposed_concurrency = int(proposal["spec"]["resourceLimits"]["maxConcurrency"])
    if proposed_concurrency > canonical_concurrency:
        raise ValueError(
            "proposal rejected: concurrency "
            f"{proposed_concurrency} exceeds host ceiling {canonical_concurrency}"
        )


def admit_host_slot_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    host_slot_ceiling: int,
) -> list[str]:
    """Admit, queue, or reject candidates that share one host slot ceiling.

    A single candidate whose demand exceeds the ceiling is rejected. Two
    otherwise valid candidates that jointly exceed remaining demand are
    queued rather than silently oversubscribed.
    """
    if (
        not isinstance(host_slot_ceiling, int)
        or isinstance(host_slot_ceiling, bool)
        or host_slot_ceiling <= 0
    ):
        raise ValueError("host_slot_ceiling must be a positive integer")
    reserved = 0
    verdicts: list[str] = []
    for candidate in candidates:
        demand = host_slot_total(candidate)
        if demand > host_slot_ceiling:
            verdicts.append("rejected")
            continue
        if reserved + demand > host_slot_ceiling:
            verdicts.append("queued")
            continue
        reserved += demand
        verdicts.append("admitted")
    return verdicts


def _assert_budget(document: Mapping[str, Any], budget: ProposalBudget) -> None:
    try:
        spec = document["spec"]
        nodes = spec["nodes"]
        edges = spec["edges"]
        limits = spec["resourceLimits"]
        total_slots = sum(int(node["resources"]["slots"]) for node in nodes)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("proposal budget inputs are malformed") from exc
    failures = []
    if len(nodes) > budget.max_nodes:
        failures.append(f"nodes {len(nodes)}>{budget.max_nodes}")
    if len(edges) > budget.max_edges:
        failures.append(f"edges {len(edges)}>{budget.max_edges}")
    if int(limits["maxConcurrency"]) > budget.max_concurrency:
        failures.append(
            f"concurrency {limits['maxConcurrency']}>{budget.max_concurrency}"
        )
    if int(limits["maxDurationSeconds"]) > budget.max_duration_seconds:
        failures.append(
            f"duration {limits['maxDurationSeconds']}>{budget.max_duration_seconds}"
        )
    if total_slots > budget.max_total_slots:
        failures.append(f"slots {total_slots}>{budget.max_total_slots}")
    if failures:
        raise ValueError("proposal exceeds budget: " + ", ".join(failures))


def _cutover_is_green(
    stage: CutoverStage,
    evidence: DogfoodEvidence | None,
) -> bool:
    return stage is CutoverStage.FULL and evidence is not None and evidence.passed


def evaluate_dynamic_proposal(
    proposal: Mapping[str, Any] | None,
    *,
    canonical_graph: Mapping[str, Any],
    plan_policy: str,
    cutover_stage: CutoverStage,
    cutover_evidence: DogfoodEvidence | None,
    budget: ProposalBudget,
    kernel_options: Mapping[str, Any] | None = None,
) -> ProposalDecision:
    """Select a guarded proposal or compile and return the canonical graph.

    Ambiguous, disabled, invalid, or over-budget proposals never escape as
    executable orchestration. They deterministically fall back to the canonical
    graph after that graph independently passes the same safety kernel.
    """
    options = dict(kernel_options or {})
    try:
        canonical_compiled = compile_workflow_graph(canonical_graph, **options)
    except KernelCompilationError as exc:
        raise DynamicProposalError(
            f"canonical graph failed the safety kernel: {exc}"
        ) from exc

    reason = ""
    if plan_policy != "proposed":
        reason = "dynamic proposals require orchestration.planPolicy=proposed"
    elif not _cutover_is_green(cutover_stage, cutover_evidence):
        reason = "dynamic proposals remain inactive until cutover is green"
    elif proposal is None:
        reason = "proposal is absent or ambiguous"
    elif not isinstance(proposal, Mapping):
        reason = "proposal must be a WorkflowGraph document"
    else:
        try:
            _assert_budget(proposal, budget)
            _assert_required_capability_invariant(proposal, canonical_graph)
            compiled = compile_workflow_graph(proposal, **options)
        except (KernelCompilationError, ValueError) as exc:
            reason = f"proposal rejected: {exc}"
        else:
            return ProposalDecision(
                verdict="accepted",
                graph=compiled["graph"],
                compiled=compiled,
                used_fallback=False,
                reason="proposal passed schema, catalog, kernel, and budget checks",
            )

    return ProposalDecision(
        verdict="canonical-fallback",
        graph=canonical_compiled["graph"],
        compiled=canonical_compiled,
        used_fallback=True,
        reason=reason,
    )
