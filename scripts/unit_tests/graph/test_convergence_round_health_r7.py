#!/usr/bin/env python3
"""Adaptive convergence with round-health attestation (PRD 270 R7)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.convergence_loop import (  # noqa: E402
    REASON_DRY_CLEAN,
    REASON_DRY_ERROR,
    REASON_DUPLICATE_RATE,
    REASON_MAX_ROUNDS,
    REASON_RATE_LIMITED,
    REASON_TOKEN_BUDGET,
    REASON_TRUNCATED,
    ConvergenceBudgets,
    ConvergencePolicy,
    DiscoveryRound,
    Finding,
    InMemoryFingerprintStore,
    RoundHealth,
    run_convergence_loop,
)
from graph.observability import (  # noqa: E402
    GraphObservability,
    convergence_outcome_from_result,
    outcome_to_payload,
)


def test_dry_clean_requires_successful_nonempty_evidence() -> None:
    store = InMemoryFingerprintStore()
    calls = {"n": 0}

    def discover(_round: int, seen: frozenset[str]) -> DiscoveryRound:
        calls["n"] += 1
        if not seen:
            return DiscoveryRound(
                (Finding({"id": 1}, tokens=1),),
                health=RoundHealth(status="success", evidence_nonempty=True),
            )
        return DiscoveryRound(
            (Finding({"id": 1}, tokens=1),),
            health=RoundHealth(status="success", evidence_nonempty=True),
        )

    result = run_convergence_loop(
        "ns",
        discover,
        budgets=ConvergenceBudgets(max_rounds=4, max_findings=5, max_tokens=20),
        fingerprint_store=store,
    )
    assert result.converged
    assert result.reason_code == REASON_DRY_CLEAN
    assert result.dry_kind == "clean"
    assert calls["n"] == 2


def test_dry_error_on_empty_first_round() -> None:
    store = InMemoryFingerprintStore()
    result = run_convergence_loop(
        "ns",
        lambda _round, _seen: DiscoveryRound((), RoundHealth("success", evidence_nonempty=False)),
        budgets=ConvergenceBudgets(max_rounds=3, max_findings=5, max_tokens=20),
        fingerprint_store=store,
    )
    assert not result.converged
    assert result.verdict == "failed"
    assert result.reason_code == REASON_DRY_ERROR
    assert result.dry_kind == "error"


def test_truncated_discovery_is_dry_error_not_converged() -> None:
    store = InMemoryFingerprintStore()
    result = run_convergence_loop(
        "ns",
        lambda _round, _seen: DiscoveryRound(
            (Finding({"id": 1}, tokens=1),),
            health=RoundHealth(status="truncated"),
        ),
        budgets=ConvergenceBudgets(max_rounds=3, max_findings=5, max_tokens=20),
        fingerprint_store=store,
    )
    assert result.verdict == "failed"
    assert result.reason_code == REASON_TRUNCATED


def test_rate_limited_discovery_halts() -> None:
    store = InMemoryFingerprintStore()
    result = run_convergence_loop(
        "ns",
        lambda _round, _seen: DiscoveryRound(
            (),
            health=RoundHealth(status="rate-limited"),
        ),
        budgets=ConvergenceBudgets(max_rounds=3, max_findings=5, max_tokens=20),
        fingerprint_store=store,
    )
    assert result.reason_code == REASON_RATE_LIMITED


def test_token_budget_with_outstanding_findings_not_converged() -> None:
    store = InMemoryFingerprintStore()
    result = run_convergence_loop(
        "ns",
        lambda _round, _seen: (Finding({"id": _round}, tokens=10),),
        budgets=ConvergenceBudgets(max_rounds=5, max_findings=10, max_tokens=15),
        fingerprint_store=store,
    )
    assert not result.converged
    assert result.verdict == "budget-exhausted"
    assert result.reason_code == REASON_TOKEN_BUDGET
    assert "outstanding" in result.reason


def test_max_rounds_halts_with_partial_output() -> None:
    store = InMemoryFingerprintStore()
    result = run_convergence_loop(
        "ns",
        lambda round_no, _seen: (Finding({"id": round_no}, tokens=1),),
        budgets=ConvergenceBudgets(max_rounds=2, max_findings=10, max_tokens=50),
        fingerprint_store=store,
    )
    assert result.verdict == "halted"
    assert result.reason_code == REASON_MAX_ROUNDS
    assert result.partial is True
    assert result.findings_seen == 2
    assert len(result.fingerprints) == 2


def test_duplicate_rate_discretionary_stop_shows_prior_progress() -> None:
    store = InMemoryFingerprintStore()
    policy = ConvergencePolicy(
        min_productive_rounds_for_discretionary=2,
        duplicate_rate_threshold=0.5,
    )
    rounds_seen: list[int] = []

    def discover(round_no: int, seen: frozenset[str]) -> DiscoveryRound:
        rounds_seen.append(round_no)
        if round_no == 1:
            return DiscoveryRound((Finding({"a": 1}, tokens=1), Finding({"b": 2}, tokens=1)))
        if round_no == 2:
            return DiscoveryRound((Finding({"c": 3}, tokens=1),))
        return DiscoveryRound(
            (
                Finding({"a": 1}, tokens=1),
                Finding({"b": 2}, tokens=1),
                Finding({"c": 3}, tokens=1),
                Finding({"d": 4}, tokens=1),
            )
        )

    result = run_convergence_loop(
        "ns",
        discover,
        budgets=ConvergenceBudgets(max_rounds=6, max_findings=10, max_tokens=50),
        fingerprint_store=store,
        policy=policy,
    )
    assert result.converged
    assert result.reason_code == REASON_DUPLICATE_RATE
    assert len(result.progress_on_prior_findings) >= 2


def test_observability_surfaces_convergence_outcome_on_explain() -> None:
    store = InMemoryFingerprintStore()
    result = run_convergence_loop(
        "ns",
        lambda _round, seen: (
            DiscoveryRound((Finding({"x": 1}, tokens=1),))
            if not seen
            else DiscoveryRound(
                (Finding({"x": 1}, tokens=1),),
                health=RoundHealth(status="success", evidence_nonempty=True),
            )
        ),
        budgets=ConvergenceBudgets(max_rounds=3, max_findings=5, max_tokens=20),
        fingerprint_store=store,
    )
    outcome = convergence_outcome_from_result(result, node_id="loop", run_id="run-1")
    payload = outcome_to_payload(outcome)
    assert payload["requirement"] == "R7"
    assert payload["reasonCode"] == REASON_DRY_CLEAN
    assert payload["nextAction"]["action"] == "none"

    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "conv"},
        "spec": {
            "nodes": [
                {
                    "id": "loop",
                    "kind": "convergence-loop",
                    "resources": {"pool": "read-only-reviewers", "slots": 1, "timeoutSeconds": 30},
                    "isolation": {"mode": "process", "writeScope": "read-only"},
                    "verification": {"required": True, "strategy": "mechanical"},
                }
            ],
            "edges": [],
            "resourceLimits": {"maxConcurrency": 1, "maxDurationSeconds": 60},
            "verification": {"required": True, "failClosed": True},
        },
    }
    receipt = {
        "state": "complete",
        "nodeId": "loop",
        "idempotencyKey": "run:loop",
        "model": "fixture",
        "attempts": 1,
        "tokens": result.tokens_used,
        "durationMs": 1,
        "inputHashes": [],
        "outputHashes": ["loop-hash"],
        "verdict": "pass",
        "coverage": {
            "convergence": {
                "verdict": result.verdict,
                "reason": result.reason,
                "reasonCode": result.reason_code,
                "findingsSeen": result.findings_seen,
                "tokensUsed": result.tokens_used,
                "fingerprints": list(result.fingerprints),
                "dryKind": result.dry_kind,
            }
        },
    }
    obs = GraphObservability(graph, [receipt], run_id="run-1")
    explained = obs.explain("loop")
    assert explained["reasonCode"] == REASON_DRY_CLEAN
    assert explained["outcome"]["requirement"] == "R7"
    status = obs.status()
    assert status["outcomes"][0]["reasonCode"] == REASON_DRY_CLEAN


def test_prd270_outcome_from_coverage_supports_r1_through_r6() -> None:
    from graph.observability import outcome_from_coverage

    for requirement in ("R1", "R2", "R3", "R4", "R5", "R6"):
        outcome = outcome_from_coverage(
            {
                "prd270Outcome": {
                    "requirement": requirement,
                    "reasonCode": f"{requirement.lower()}.fixture",
                    "verdict": "pass",
                    "responsible": {"nodeId": "n1"},
                    "explanation": "fixture",
                    "nextAction": {"action": "none", "command": None, "detail": "ok"},
                }
            },
            node_id="n1",
        )
        assert outcome is not None
        assert outcome.requirement == requirement
