#!/usr/bin/env python3
"""Guarded WorkflowGraph proposals with deterministic canonical fallback."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from graph.absolute_floor import (
    AbsoluteFloorError,
    apply_optimization_profile,
    enforce_absolute_floor,
    required_capabilities_from_graph,
)
from graph.cutover import CutoverStage, DogfoodEvidence
from graph.isolation_policy import (
    ShadowDispatchDecision,
    ShadowReceiptEstimate,
    classify_shadow_dispatch,
    estimate_mutating_from_receipt,
    shadow_kind_is_mutating,
    shadow_refuse_credential_resolution,
    shadow_refuse_write_lease,
)
from graph.kernel_compiler import KernelCompilationError, compile_workflow_graph
from graph.scheduler import GraphScheduler, NodeExecutionResult
from graph.detectors.registry import CAPABILITY_AUTH
from graph.verifier_policies import VerifierKind


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
IMPLEMENT_NODE_KINDS = frozenset(
    {"command", "agent", "barrier", "convergence-loop", "router", "transform"}
)
AUTH_SECURITY_CAPABILITIES = frozenset({CAPABILITY_AUTH})
REQUIRED_CAPABILITY_TOKENS = (
    "merge-gate",
    "human-merge-gate",
    "human-terminal-merge-gate",
    "credential-broker",
    "write-isolation-lease",
    "mechanical-verification",
    "verification-gate",
)

PROPOSAL_METRIC_FIELD_KEYS = frozenset(
    {
        "metrics",
        "predictedLatency",
        "predictedLatencyMs",
        "predictedCost",
        "predictedParallelism",
        "predictedNodeCount",
        "predictedResourceDemand",
        "verificationCoverage",
        "shadowScore",
    }
)

_VERIFIER_STRATEGY_TO_CLASS = {
    "mechanical": VerifierKind.MECHANICAL.value,
    "evidence": VerifierKind.EVIDENCE.value,
    "judgment": VerifierKind.JUDGMENT.value,
    "synthesis": VerifierKind.SYNTHESIS.value,
}
_VERIFIER_STRENGTH = {
    VerifierKind.MECHANICAL.value: 1,
    VerifierKind.EVIDENCE.value: 2,
    VerifierKind.JUDGMENT.value: 3,
    VerifierKind.SYNTHESIS.value: 4,
}

_VERIFIER_CLASS_RANK = {
    VerifierKind.MECHANICAL.value: 0,
    VerifierKind.EVIDENCE.value: 1,
    VerifierKind.JUDGMENT.value: 2,
    VerifierKind.SYNTHESIS.value: 3,
}


@dataclass(frozen=True)
class CoverageRequirement:
    """One detected requirement plus acceptance criterion for promotion coverage."""

    capability_id: str
    acceptance_criterion_id: str
    required_verifier_class: str


@dataclass(frozen=True)
class CoverageEvidenceRecord:
    """Executed verifier evidence bound to a headSha for one AC."""

    capability_id: str
    acceptance_criterion_id: str
    verifier_class: str
    passed: bool
    head_sha: str


@dataclass(frozen=True)
class RequiredCapabilityCoverage:
    """Coverage over required capabilities and ACs — not kernel verification.required."""

    aggregate: float
    by_capability_id: Mapping[str, float]
    by_acceptance_criterion: Mapping[str, float]
    head_sha: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate": self.aggregate,
            "byCapabilityId": dict(self.by_capability_id),
            "byAcceptanceCriterion": dict(self.by_acceptance_criterion),
            "headSha": self.head_sha,
        }


def verifier_class_meets_requirement(
    observed_class: str,
    required_class: str,
) -> bool:
    """True when observed verifier class is at least as strong as required."""
    observed_rank = _VERIFIER_CLASS_RANK.get(observed_class)
    required_rank = _VERIFIER_CLASS_RANK.get(required_class)
    if observed_rank is None or required_rank is None:
        return False
    return observed_rank >= required_rank


def compute_required_capability_coverage(
    requirements: Sequence[CoverageRequirement],
    evidence: Sequence[CoverageEvidenceRecord],
    *,
    head_sha: str,
) -> RequiredCapabilityCoverage:
    """Measure AC coverage from executed passing verifiers at the current headSha."""
    normalized_head = head_sha.strip().lower()
    if not requirements:
        return RequiredCapabilityCoverage(
            aggregate=0.0,
            by_capability_id={},
            by_acceptance_criterion={},
            head_sha=normalized_head,
        )

    by_capability: dict[str, list[float]] = {}
    by_ac: dict[str, float] = {}
    for requirement in requirements:
        covered = False
        for record in evidence:
            if record.head_sha.strip().lower() != normalized_head:
                continue
            if (
                record.capability_id != requirement.capability_id
                or record.acceptance_criterion_id
                != requirement.acceptance_criterion_id
            ):
                continue
            if not record.passed:
                continue
            if verifier_class_meets_requirement(
                record.verifier_class,
                requirement.required_verifier_class,
            ):
                covered = True
                break
        score = 1.0 if covered else 0.0
        by_ac[requirement.acceptance_criterion_id] = score
        by_capability.setdefault(requirement.capability_id, []).append(score)

    by_capability_id = {
        capability_id: sum(scores) / len(scores)
        for capability_id, scores in sorted(by_capability.items())
    }
    aggregate = sum(by_ac.values()) / len(by_ac)
    return RequiredCapabilityCoverage(
        aggregate=aggregate,
        by_capability_id=by_capability_id,
        by_acceptance_criterion=dict(sorted(by_ac.items())),
        head_sha=normalized_head,
    )


def measure_verifier_substitution_regression(
    *,
    requirements: Sequence[CoverageRequirement],
    strong_evidence: Sequence[CoverageEvidenceRecord],
    weak_evidence: Sequence[CoverageEvidenceRecord],
    head_sha: str,
) -> float:
    """Return coverage delta when substituting a weaker verifier arm."""
    strong = compute_required_capability_coverage(
        requirements,
        strong_evidence,
        head_sha=head_sha,
    )
    weak = compute_required_capability_coverage(
        requirements,
        weak_evidence,
        head_sha=head_sha,
    )
    return weak.aggregate - strong.aggregate


def promotion_coverage_gate(
    coverage: RequiredCapabilityCoverage,
    *,
    regression_ceiling: float = 0.0,
    reference_aggregate: float = 1.0,
) -> tuple[bool, str]:
    """Fail closed when required-capability coverage regresses beyond ceiling."""
    allowed = reference_aggregate - regression_ceiling
    if coverage.aggregate + 1e-9 < allowed:
        return (
            False,
            f"coverage aggregate {coverage.aggregate} below allowed {allowed}",
        )
    return True, ""


def coverage_requirements_from_graph(
    graph: Mapping[str, Any],
) -> tuple[CoverageRequirement, ...]:
    """Derive promotion coverage requirements from a WorkflowGraph."""
    requirements: list[CoverageRequirement] = []
    seen: set[tuple[str, str]] = set()
    for node in graph["spec"]["nodes"]:
        if not isinstance(node, Mapping):
            continue
        cap_id = str((node.get("metadata") or {}).get("requiredCapabilityId") or "")
        if not cap_id:
            step = str((node.get("target") or {}).get("step") or "")
            if "auth" in step:
                cap_id = CAPABILITY_AUTH
        if not cap_id:
            continue
        strategy = str(
            (node.get("verification") or {}).get("strategy")
            or VerifierKind.MECHANICAL.value
        )
        ac_id = f"{cap_id}:default"
        key = (cap_id, ac_id)
        if key in seen:
            continue
        seen.add(key)
        requirements.append(
            CoverageRequirement(
                capability_id=cap_id,
                acceptance_criterion_id=ac_id,
                required_verifier_class=strategy,
            )
        )
    for cap_id in sorted(required_capabilities_from_graph(graph)):
        ac_id = f"{cap_id}:default"
        key = (cap_id, ac_id)
        if key in seen:
            continue
        default_class = (
            VerifierKind.JUDGMENT.value
            if cap_id == CAPABILITY_AUTH
            else VerifierKind.EVIDENCE.value
        )
        requirements.append(
            CoverageRequirement(
                capability_id=cap_id,
                acceptance_criterion_id=ac_id,
                required_verifier_class=default_class,
            )
        )
    return tuple(requirements)


def coverage_evidence_from_graph(
    graph: Mapping[str, Any],
    *,
    head_sha: str = "proposal",
) -> tuple[CoverageEvidenceRecord, ...]:
    """Treat declared verifier nodes as executed evidence at the current headSha."""
    records: list[CoverageEvidenceRecord] = []
    for node in graph["spec"]["nodes"]:
        if not isinstance(node, Mapping):
            continue
        cap_id = str((node.get("metadata") or {}).get("requiredCapabilityId") or "")
        if not cap_id:
            step = str((node.get("target") or {}).get("step") or "")
            if "auth" in step:
                cap_id = CAPABILITY_AUTH
        if not cap_id:
            continue
        strategy = str((node.get("verification") or {}).get("strategy") or "")
        verifier_class = _VERIFIER_STRATEGY_TO_CLASS.get(strategy, strategy)
        records.append(
            CoverageEvidenceRecord(
                capability_id=cap_id,
                acceptance_criterion_id=f"{cap_id}:default",
                verifier_class=verifier_class,
                passed=True,
                head_sha=head_sha,
            )
        )
    return tuple(records)


def compute_graph_capability_coverage(
    graph: Mapping[str, Any],
    *,
    reference_graph: Mapping[str, Any] | None = None,
    head_sha: str = "proposal",
) -> RequiredCapabilityCoverage:
    """Graph-facing wrapper over required-capability coverage semantics."""
    reference = reference_graph or graph
    requirements = coverage_requirements_from_graph(reference)
    return compute_required_capability_coverage(
        requirements,
        coverage_evidence_from_graph(graph, head_sha=head_sha),
        head_sha=head_sha,
    )


def assert_coverage_regression_gate(
    proposal: Mapping[str, Any],
    *,
    canonical_graph: Mapping[str, Any],
) -> None:
    """Reject proposals that weaken required-capability verifier coverage."""
    canonical = compute_graph_capability_coverage(
        canonical_graph,
        reference_graph=canonical_graph,
    )
    proposed = compute_graph_capability_coverage(
        proposal,
        reference_graph=canonical_graph,
    )
    ok, reason = promotion_coverage_gate(
        proposed,
        reference_aggregate=canonical.aggregate,
    )
    if not ok:
        raise ValueError(f"proposal rejected: coverage regression ({reason})")


def template_required_independent_votes(template: Mapping[str, Any]) -> int:
    """Read the template-declared independent judgment vote floor."""
    verification = template.get("spec", {}).get("verification", {})
    if not isinstance(verification, Mapping):
        return 0
    if "requiredIndependentVotes" in verification:
        return int(verification["requiredIndependentVotes"])
    count = 0
    for node in template.get("spec", {}).get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        strategy = str((node.get("verification") or {}).get("strategy") or "")
        if strategy == VerifierKind.JUDGMENT.value:
            count += 1
    return count


def _count_judgment_nodes(graph: Mapping[str, Any]) -> int:
    count = 0
    for node in graph.get("spec", {}).get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        strategy = str((node.get("verification") or {}).get("strategy") or "")
        if strategy == VerifierKind.JUDGMENT.value:
            count += 1
    return count


def assert_judgment_independence_floor(
    proposal: Mapping[str, Any],
    *,
    template: Mapping[str, Any],
) -> None:
    """Reject optimizer proposals that drop judgment reviewers below the template floor."""
    required = template_required_independent_votes(template)
    if required < 1:
        return
    proposed = _count_judgment_nodes(proposal)
    if proposed < required:
        raise ValueError(
            "proposal rejected: judgment reviewers "
            f"{proposed} below template floor {required}"
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


def _is_implement_node(node: Mapping[str, Any]) -> bool:
    kind = str(node.get("kind") or "")
    if kind in IMPLEMENT_NODE_KINDS:
        return True
    return not is_required_capability_node(node) and kind not in {"gate", "verifier"}


def _graph_predecessors(graph: Mapping[str, Any]) -> dict[str, set[str]]:
    preds: dict[str, set[str]] = {
        str(node["id"]): set() for node in graph["spec"]["nodes"]
    }
    for edge in graph["spec"]["edges"]:
        target = str(edge["to"])
        source = str(edge["from"])
        preds.setdefault(target, set()).add(source)
    return preds


def _transitive_predecessors(
    graph: Mapping[str, Any],
    node_id: str,
) -> set[str]:
    preds = _graph_predecessors(graph)
    seen: set[str] = set()
    frontier = set(preds.get(node_id, set()))
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        frontier.update(preds.get(current, set()) - seen)
    return seen


def _canonical_inbound_edges(
    graph: Mapping[str, Any],
    node_id: str,
) -> tuple[tuple[str, str, bool], ...]:
    inbound: list[tuple[str, str, bool]] = []
    for edge in graph["spec"]["edges"]:
        if str(edge["to"]) != node_id:
            continue
        inbound.append(
            (
                str(edge["from"]),
                str(edge["to"]),
                bool(edge.get("required", False)),
            )
        )
    return tuple(sorted(inbound))


def _required_implement_ancestors(
    graph: Mapping[str, Any],
    node_id: str,
) -> set[str]:
    by_id = {str(node["id"]): node for node in graph["spec"]["nodes"]}
    ancestors = _transitive_predecessors(graph, node_id)
    return {
        ancestor
        for ancestor in ancestors
        if ancestor in by_id and _is_implement_node(by_id[ancestor])
    }


def assert_required_capability_topology(
    proposal: Mapping[str, Any],
    canonical_graph: Mapping[str, Any],
) -> None:
    """Reachability-scoped required-capability invariant (PRD 272 R3)."""
    canonical_nodes = {
        str(node["id"]): node for node in canonical_graph["spec"]["nodes"]
    }
    proposal_nodes = {str(node["id"]): node for node in proposal["spec"]["nodes"]}
    for node_id, canonical_node in canonical_nodes.items():
        if not is_required_capability_node(canonical_node):
            continue
        if node_id not in proposal_nodes:
            raise ValueError(
                f"proposal rejected: required-capability node {node_id} missing"
            )
        canonical_inbound = _canonical_inbound_edges(canonical_graph, node_id)
        proposal_inbound = _canonical_inbound_edges(proposal, node_id)
        if proposal_inbound != canonical_inbound:
            raise ValueError(
                "proposal rejected: inbound edges to required-capability node "
                f"{node_id} are immutable"
            )
        required_ancestors = _required_implement_ancestors(canonical_graph, node_id)
        proposal_ancestors = _transitive_predecessors(proposal, node_id)
        missing = sorted(required_ancestors - proposal_ancestors)
        if missing:
            raise ValueError(
                "proposal rejected: required-capability node "
                f"{node_id} lost implement ancestors {missing}"
            )


def assert_auth_capabilities_nonskippable(
    *,
    baseline: frozenset[str],
    proposed: frozenset[str],
    control_path: str,
) -> None:
    """Control paths cannot skip or downgrade auth/security capabilities (R10)."""
    dropped = (baseline & AUTH_SECURITY_CAPABILITIES) - proposed
    if dropped:
        raise ValueError(
            f"{control_path} cannot skip required auth capabilities: {sorted(dropped)}"
        )


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
    assert_required_capability_topology(proposal, canonical_graph)
    canonical_nodes = {
        str(node["id"]): node for node in canonical_graph["spec"]["nodes"]
    }
    proposal_nodes = {str(node["id"]): node for node in proposal["spec"]["nodes"]}
    for node_id, canonical_node in canonical_nodes.items():
        if not is_required_capability_node(canonical_node):
            continue
        proposed = proposal_nodes[node_id]
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
    injected_capability_ids: frozenset[str] | None = None,
    optimization_profile: str = "balanced",
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
            assert_coverage_regression_gate(proposal, canonical_graph=canonical_graph)
            _assert_required_capability_invariant(proposal, canonical_graph)
            assert_judgment_independence_floor(
                proposal,
                template=canonical_graph,
            )
            if injected_capability_ids is not None:
                profile_adjusted = apply_optimization_profile(
                    injected_capability_ids,
                    optimization_profile,
                )
                enforce_absolute_floor(
                    injected_capability_ids=injected_capability_ids,
                    profile_adjusted_capability_ids=profile_adjusted,
                    profile=optimization_profile,
                )
                proposed_caps = required_capabilities_from_graph(proposal)
                missing = profile_adjusted - proposed_caps
                if missing:
                    raise AbsoluteFloorError(
                        "proposal missing profile-adjusted capabilities: "
                        f"{sorted(missing)}"
                    )
            compiled = compile_workflow_graph(proposal, **options)
        except (KernelCompilationError, ValueError, AbsoluteFloorError) as exc:
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


@dataclass(frozen=True)
class VerificationCoverage:
    """Aggregate and per-class verification coverage derived from kernel nodes."""

    aggregate: float
    by_verifier_class: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate": self.aggregate,
            "byVerifierClass": dict(self.by_verifier_class),
        }


@dataclass(frozen=True)
class ShadowKernelMetrics:
    """Kernel-derived shadow metrics; proposal-supplied metric fields are ignored."""

    predicted_latency_ms: int
    predicted_cost: float
    parallelism: int
    node_count: int
    resource_demand_slots: int
    verification_coverage: VerificationCoverage

    def to_dict(self) -> dict[str, Any]:
        return {
            "predictedLatencyMs": self.predicted_latency_ms,
            "predictedCost": self.predicted_cost,
            "parallelism": self.parallelism,
            "nodeCount": self.node_count,
            "resourceDemandSlots": self.resource_demand_slots,
            "verificationCoverage": self.verification_coverage.to_dict(),
        }


@dataclass(frozen=True)
class ShadowMetricDelta:
    """Predicted versus canonical kernel metrics with persisted deltas."""

    candidate: ShadowKernelMetrics
    canonical: ShadowKernelMetrics
    deltas: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "canonical": self.canonical.to_dict(),
            "deltas": dict(self.deltas),
        }


@dataclass
class ShadowDispatchRecord:
    """One shadow node outcome including realized telemetry when executed."""

    decision: ShadowDispatchDecision
    predicted: ShadowReceiptEstimate | None = None
    realized: ShadowReceiptEstimate | None = None
    executed: bool = False
    refused_write_lease: bool = False
    refused_credentials: bool = False

    @property
    def delta_latency_ms(self) -> int | None:
        if self.predicted is None or self.realized is None:
            return None
        return self.realized.duration_ms - self.predicted.duration_ms

    @property
    def delta_cost(self) -> float | None:
        if self.predicted is None or self.realized is None:
            return None
        return self.realized.cost - self.predicted.cost


@dataclass
class ShadowEvaluationResult:
    """Shadow comparison of candidate versus canonical without mutating dispatch."""

    comparison: ShadowMetricDelta
    records: tuple[ShadowDispatchRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison": self.comparison.to_dict(),
            "records": [
                {
                    "nodeId": record.decision.node_id,
                    "mode": record.decision.mode,
                    "reason": record.decision.reason,
                    "executed": record.executed,
                    "refusedWriteLease": record.refused_write_lease,
                    "refusedCredentials": record.refused_credentials,
                    "predicted": (
                        None
                        if record.predicted is None
                        else {
                            "durationMs": record.predicted.duration_ms,
                            "tokens": record.predicted.tokens,
                            "cost": record.predicted.cost,
                        }
                    ),
                    "realized": (
                        None
                        if record.realized is None
                        else {
                            "durationMs": record.realized.duration_ms,
                            "tokens": record.realized.tokens,
                            "cost": record.realized.cost,
                        }
                    ),
                    "deltaLatencyMs": record.delta_latency_ms,
                    "deltaCost": record.delta_cost,
                }
                for record in self.records
            ],
        }


def _strip_proposal_metric_fields(document: Mapping[str, Any]) -> dict[str, Any]:
    """Ignore proposal-supplied metric fields when scoring shadow outcomes."""
    stripped = json.loads(json.dumps(document))
    for key in list(stripped.keys()):
        if key in PROPOSAL_METRIC_FIELD_KEYS:
            stripped.pop(key, None)
    metadata = stripped.get("metadata")
    if isinstance(metadata, dict):
        for key in list(metadata.keys()):
            if key in PROPOSAL_METRIC_FIELD_KEYS:
                metadata.pop(key, None)
    return stripped


def _verifier_class_for_node(node: Mapping[str, Any]) -> str | None:
    kind = str(node.get("kind") or "")
    if kind not in {"verifier", "gate"}:
        return None
    if shadow_kind_is_mutating(kind):
        return None
    strategy = str((node.get("verification") or {}).get("strategy") or "")
    return _VERIFIER_STRATEGY_TO_CLASS.get(strategy)


def compute_verification_coverage(
    graph: Mapping[str, Any],
    *,
    reference_graph: Mapping[str, Any] | None = None,
) -> VerificationCoverage:
    """Required-capability coverage mapped into verifier-class buckets."""
    capability_coverage = compute_graph_capability_coverage(
        graph,
        reference_graph=reference_graph or graph,
    )
    if not capability_coverage.by_capability_id:
        return VerificationCoverage(aggregate=0.0, by_verifier_class={})
    by_class: dict[str, float] = {}
    for node in graph["spec"]["nodes"]:
        cap_id = str((node.get("metadata") or {}).get("requiredCapabilityId") or "")
        if not cap_id or cap_id not in capability_coverage.by_capability_id:
            continue
        strategy = str((node.get("verification") or {}).get("strategy") or "")
        verifier_class = _VERIFIER_STRATEGY_TO_CLASS.get(
            strategy,
            VerifierKind.MECHANICAL.value,
        )
        score = capability_coverage.by_capability_id[cap_id]
        by_class[verifier_class] = min(by_class.get(verifier_class, 1.0), score)
    aggregate = (
        sum(by_class.values()) / len(by_class) if by_class else capability_coverage.aggregate
    )
    return VerificationCoverage(aggregate=aggregate, by_verifier_class=by_class)


def compute_shadow_kernel_metrics(
    compiled: Mapping[str, Any],
    *,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
    token_cost: float = 0.0,
) -> ShadowKernelMetrics:
    """Score a compiled graph from kernel metrics only."""
    graph = compiled["graph"]
    spec = graph["spec"]
    nodes = spec["nodes"]
    limits = spec["resourceLimits"]
    predicted_latency_ms = 0
    predicted_cost = 0.0
    resource_demand_slots = 0
    receipt_map = receipts or {}
    for node in nodes:
        node_id = str(node["id"])
        timeout_seconds = int(node["resources"]["timeoutSeconds"])
        slots = int(node["resources"]["slots"])
        resource_demand_slots += slots
        if shadow_kind_is_mutating(str(node.get("kind") or "")):
            estimate = estimate_mutating_from_receipt(
                node_id,
                receipt_map.get(node_id),
                token_cost=token_cost,
            )
            predicted_latency_ms += estimate.duration_ms or timeout_seconds * 1000
            predicted_cost += estimate.cost
        else:
            predicted_latency_ms += timeout_seconds * 1000
    return ShadowKernelMetrics(
        predicted_latency_ms=predicted_latency_ms,
        predicted_cost=predicted_cost,
        parallelism=int(limits["maxConcurrency"]),
        node_count=len(nodes),
        resource_demand_slots=resource_demand_slots,
        verification_coverage=compute_verification_coverage(graph),
    )


def compare_shadow_metrics(
    candidate_compiled: Mapping[str, Any],
    canonical_compiled: Mapping[str, Any],
    *,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
    token_cost: float = 0.0,
) -> ShadowMetricDelta:
    """Compare candidate and canonical shadow metrics with persisted deltas."""
    candidate = compute_shadow_kernel_metrics(
        candidate_compiled,
        receipts=receipts,
        token_cost=token_cost,
    )
    canonical = compute_shadow_kernel_metrics(
        canonical_compiled,
        receipts=receipts,
        token_cost=token_cost,
    )
    deltas = {
        "predictedLatencyMs": candidate.predicted_latency_ms
        - canonical.predicted_latency_ms,
        "predictedCost": candidate.predicted_cost - canonical.predicted_cost,
        "parallelism": candidate.parallelism - canonical.parallelism,
        "nodeCount": candidate.node_count - canonical.node_count,
        "resourceDemandSlots": candidate.resource_demand_slots
        - canonical.resource_demand_slots,
        "verificationCoverageAggregate": (
            candidate.verification_coverage.aggregate
            - canonical.verification_coverage.aggregate
        ),
        "verificationCoverageByClass": {
            key: candidate.verification_coverage.by_verifier_class.get(key, 0.0)
            - canonical.verification_coverage.by_verifier_class.get(key, 0.0)
            for key in sorted(
                set(candidate.verification_coverage.by_verifier_class)
                | set(canonical.verification_coverage.by_verifier_class)
            )
        },
    }
    return ShadowMetricDelta(candidate=candidate, canonical=canonical, deltas=deltas)


class ShadowExecutorGuard:
    """Spy wrapper ensuring off-allowlist kinds never execute mutating work."""

    def __init__(
        self,
        inner: Any,
        *,
        receipts: Mapping[str, Mapping[str, Any]] | None = None,
        token_cost: float = 0.0,
    ) -> None:
        self._inner = inner
        self._receipts = dict(receipts or {})
        self._token_cost = token_cost
        self.executed_node_ids: list[str] = []
        self.refused_write_lease: list[str] = []
        self.refused_credentials: list[str] = []
        self.records: list[ShadowDispatchRecord] = []

    def __call__(self, node: Mapping[str, Any]) -> NodeExecutionResult:
        node_id = str(node["id"])
        decision = classify_shadow_dispatch(node)
        refused_write = shadow_refuse_write_lease(node)
        refused_credentials = shadow_refuse_credential_resolution(node)
        if refused_write:
            self.refused_write_lease.append(node_id)
        if refused_credentials:
            self.refused_credentials.append(node_id)
        if decision.mode != "execute-read-only":
            predicted = estimate_mutating_from_receipt(
                node_id,
                self._receipts.get(node_id),
                token_cost=self._token_cost,
            )
            self.records.append(
                ShadowDispatchRecord(
                    decision=decision,
                    predicted=predicted,
                    realized=predicted,
                    executed=False,
                    refused_write_lease=refused_write,
                    refused_credentials=refused_credentials,
                )
            )
            return NodeExecutionResult(
                verdict="pass",
                output={"shadow": "estimated", "nodeId": node_id},
                model="shadow-estimate",
                duration_ms=predicted.duration_ms,
                tokens=predicted.tokens,
                coverage={
                    "shadow": True,
                    "estimated": True,
                    "refusedWriteLease": refused_write,
                    "refusedCredentials": refused_credentials,
                },
            )
        self.executed_node_ids.append(node_id)
        result = self._inner(dict(node))
        realized = ShadowReceiptEstimate(
            node_id=node_id,
            duration_ms=int(result.duration_ms),
            tokens=int(result.tokens),
            cost=float(result.tokens) * self._token_cost,
        )
        self.records.append(
            ShadowDispatchRecord(
                decision=decision,
                predicted=ShadowReceiptEstimate(
                    node_id=node_id,
                    duration_ms=int(node["resources"]["timeoutSeconds"]) * 1000,
                    tokens=0,
                    cost=0.0,
                ),
                realized=realized,
                executed=True,
                refused_write_lease=refused_write,
                refused_credentials=refused_credentials,
            )
        )
        return result


def run_shadow_evaluation(
    candidate_compiled: Mapping[str, Any],
    canonical_compiled: Mapping[str, Any],
    *,
    scheduler: GraphScheduler,
    run_id: str,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
    token_cost: float = 0.0,
    kernel_options: Mapping[str, Any] | None = None,
) -> ShadowEvaluationResult:
    """Execute read-only shadow dispatch and score candidate versus canonical."""
    comparison = compare_shadow_metrics(
        candidate_compiled,
        canonical_compiled,
        receipts=receipts,
        token_cost=token_cost,
    )
    options = dict(kernel_options or {})
    if candidate_compiled.get("transformOperators"):
        options.setdefault(
            "transform_operators",
            dict(candidate_compiled["transformOperators"]),
        )
    graph = _strip_proposal_metric_fields(candidate_compiled["graph"])
    guard = ShadowExecutorGuard(
        scheduler._executor,
        receipts=receipts,
        token_cost=token_cost,
    )
    shadow_scheduler = GraphScheduler(
        guard,
        receipts=scheduler._receipts,
        pools=scheduler._pools,
        convergence_executor=scheduler._convergence_executor,
        lease_releaser=scheduler._lease_releaser,
        compensation=scheduler._compensation,
        clock=scheduler._clock,
        cache_enabled=False,
    )
    shadow_scheduler.run(
        graph,
        run_id=f"{run_id}:shadow",
        internal_only=True,
        kernel_options=options,
    )
    return ShadowEvaluationResult(comparison=comparison, records=tuple(guard.records))


def evaluate_shadow_proposal(
    proposal: Mapping[str, Any],
    *,
    canonical_graph: Mapping[str, Any],
    scheduler: GraphScheduler,
    run_id: str,
    kernel_options: Mapping[str, Any] | None = None,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
    token_cost: float = 0.0,
) -> ShadowEvaluationResult:
    """Compile candidate + canonical and run non-mutating shadow scoring."""
    assert_judgment_independence_floor(
        proposal,
        template=canonical_graph,
    )
    options = dict(kernel_options or {})
    stripped = _strip_proposal_metric_fields(proposal)
    candidate_compiled = compile_workflow_graph(stripped, **options)
    canonical_compiled = compile_workflow_graph(canonical_graph, **options)
    return run_shadow_evaluation(
        candidate_compiled,
        canonical_compiled,
        scheduler=scheduler,
        run_id=run_id,
        receipts=receipts,
        token_cost=token_cost,
    )


def export_shadow_evaluation_inputs(
    candidates: Sequence[Mapping[str, Any]] | None,
    *,
    canonical_graph: Mapping[str, Any],
    shadow_enabled: bool = True,
) -> dict[str, Any]:
    """Export read-only shadow evaluation inputs from optimization candidates (PRD 280 R9)."""
    read_only_payload = {
        "readOnlyAssert": True,
        "mutatingBackendCalls": 0,
    }
    if not shadow_enabled:
        return {
            "verdict": "skipped",
            "action": "export-shadow-inputs",
            "reason": "shadow-disabled",
            "inputs": [],
            **read_only_payload,
        }
    if not candidates:
        return {
            "verdict": "pass",
            "action": "export-shadow-inputs",
            "candidateCount": 0,
            "inputs": [],
            **read_only_payload,
        }

    inputs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    canonical_stripped = _strip_proposal_metric_fields(canonical_graph)
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            errors.append({"index": index, "error": "candidate must be a mapping"})
            continue
        try:
            stripped = _strip_proposal_metric_fields(candidate)
            assert_judgment_independence_floor(stripped, template=canonical_graph)
            digest = hashlib.sha256(
                json.dumps(dict(stripped), sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            inputs.append(
                {
                    "candidateDigest": digest,
                    "proposal": stripped,
                    "canonicalGraph": canonical_stripped,
                    "readOnly": True,
                    "mutatingBackendCalls": 0,
                    "shadowMode": "read-only-export",
                }
            )
        except (TypeError, ValueError) as exc:
            errors.append({"index": index, "error": str(exc)})

    if errors and not inputs:
        return {
            "verdict": "fail",
            "action": "export-shadow-inputs",
            "errors": errors,
            "inputs": [],
            **read_only_payload,
        }
    return {
        "verdict": "pass",
        "action": "export-shadow-inputs",
        "candidateCount": len(inputs),
        "inputs": inputs,
        "errors": errors or None,
        **read_only_payload,
    }
