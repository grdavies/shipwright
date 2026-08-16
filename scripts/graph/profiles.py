#!/usr/bin/env python3
"""Workflow optimization profiles and run budgets (PRD 272 R23)."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from graph.absolute_floor import (
    AbsoluteFloorError,
    evaluate_after_profile_and_inject,
    OPTIMIZATION_PROFILES,
)

KERNEL_IMMUTABLE_PROFILE_FIELDS = frozenset(
    {
        "cache",
        "loop_bounds",
        "loopBounds",
        "maxConcurrency",
        "maxDurationSeconds",
    }
)
READY_VERDICTS = frozenset({"merge-ready-green", "ready"})
NON_READY_BUDGET_VERDICT = "budget-halt-non-ready"


class ProfileError(ValueError):
    """Raised when a workflow profile violates kernel immutables or budget policy."""


@dataclass(frozen=True)
class WorkflowProfile:
    """Operator-tunable optimization profile — never overrides kernel immutables."""

    optimization: str = "balanced"
    max_cost: float = 1000.0
    max_tokens: int = 1_000_000

    def __post_init__(self) -> None:
        if self.optimization not in OPTIMIZATION_PROFILES:
            raise ProfileError(f"unknown optimization profile: {self.optimization}")
        if self.max_cost <= 0:
            raise ProfileError("max_cost must be positive")
        if self.max_tokens <= 0:
            raise ProfileError("max_tokens must be positive")


@dataclass
class NodeBudgetAccount:
    """Per-node spend ledger entry."""

    node_id: str
    cost: float = 0.0
    tokens: int = 0


@dataclass
class RunBudgetState:
    """Accumulated spend against a workflow profile budget."""

    profile: WorkflowProfile
    accounts: dict[str, NodeBudgetAccount] = field(default_factory=dict)
    total_cost: float = 0.0
    total_tokens: int = 0
    halt_reason: str | None = None

    def record_node_spend(
        self,
        node_id: str,
        *,
        cost: float = 0.0,
        tokens: int = 0,
    ) -> None:
        if cost < 0 or tokens < 0:
            raise ProfileError("node spend must be non-negative")
        account = self.accounts.setdefault(node_id, NodeBudgetAccount(node_id=node_id))
        account.cost += cost
        account.tokens += tokens
        self.total_cost += cost
        self.total_tokens += tokens
        if self.total_cost > self.profile.max_cost:
            self.halt_reason = f"cost {self.total_cost}>{self.profile.max_cost}"
        elif self.total_tokens > self.profile.max_tokens:
            self.halt_reason = f"tokens {self.total_tokens}>{self.profile.max_tokens}"

    def budget_verdict(self) -> str:
        if self.halt_reason:
            return NON_READY_BUDGET_VERDICT
        return "within-budget"

    def is_ready(self) -> bool:
        return self.halt_reason is None


def reject_kernel_immutable_profile_fields(document: Mapping[str, Any]) -> None:
    """Fail closed when profile payloads attempt to override kernel immutables."""
    offenders = sorted(
        key
        for key in document.keys()
        if key in KERNEL_IMMUTABLE_PROFILE_FIELDS
    )
    if offenders:
        raise ProfileError(
            "profile cannot set kernel immutables: "
            + ", ".join(offenders)
        )
    nested = document.get("resourceLimits")
    if isinstance(nested, Mapping):
        nested_offenders = sorted(
            key
            for key in nested.keys()
            if key in KERNEL_IMMUTABLE_PROFILE_FIELDS
        )
        if nested_offenders:
            raise ProfileError(
                "profile resourceLimits cannot set kernel immutables: "
                + ", ".join(nested_offenders)
            )


def parse_workflow_profile(document: Mapping[str, Any] | None) -> WorkflowProfile:
    """Parse and validate a workflow profile document from config."""
    if document is None:
        return WorkflowProfile()
    reject_kernel_immutable_profile_fields(document)
    optimization = str(document.get("optimization") or document.get("optimizationProfile") or "balanced")
    budgets = document.get("budgets") or {}
    max_cost = float(budgets.get("maxCost") or document.get("maxCost") or 1000.0)
    max_tokens = int(budgets.get("maxTokens") or document.get("maxTokens") or 1_000_000)
    return WorkflowProfile(
        optimization=optimization,
        max_cost=max_cost,
        max_tokens=max_tokens,
    )


def apply_workflow_profile_capabilities(
    injected_capability_ids: frozenset[str],
    profile: WorkflowProfile | Mapping[str, Any] | None,
    *,
    repo_root: Any = None,
) -> frozenset[str]:
    """Apply optimization profile after injection; required caps are never shed."""
    parsed = (
        profile
        if isinstance(profile, WorkflowProfile)
        else parse_workflow_profile(profile)
    )
    try:
        return evaluate_after_profile_and_inject(
            injected_capability_ids=injected_capability_ids,
            profile=parsed.optimization,
            repo_root=repo_root,
        )
    except AbsoluteFloorError as exc:
        raise ProfileError(str(exc)) from exc


def preserve_required_capabilities(
    *,
    baseline: frozenset[str],
    proposed: frozenset[str],
) -> None:
    """Required capabilities cannot be shed by profile or budget paths."""
    dropped = baseline - proposed
    if dropped:
        raise ProfileError(
            f"required capabilities cannot be shed: {sorted(dropped)}"
        )


def profile_document_digest(document: Mapping[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summarize_budget_state(state: RunBudgetState) -> dict[str, Any]:
    return {
        "optimization": state.profile.optimization,
        "totalCost": state.total_cost,
        "totalTokens": state.total_tokens,
        "maxCost": state.profile.max_cost,
        "maxTokens": state.profile.max_tokens,
        "verdict": state.budget_verdict(),
        "haltReason": state.halt_reason,
        "perNode": [
            {
                "nodeId": account.node_id,
                "cost": account.cost,
                "tokens": account.tokens,
            }
            for account in sorted(state.accounts.values(), key=lambda a: a.node_id)
        ],
    }
