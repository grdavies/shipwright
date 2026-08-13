#!/usr/bin/env python3
"""Guarded WorkflowGraph proposals with deterministic canonical fallback."""
from __future__ import annotations

from collections.abc import Mapping
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
