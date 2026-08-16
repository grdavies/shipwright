#!/usr/bin/env python3
"""PRD 272 phase-8 profiles, traceability, triage, and docs tests (R23–R26)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.detectors.registry import CAPABILITY_AUTH, CAPABILITY_STANDARD_REVIEW  # noqa: E402
from graph.profiles import (  # noqa: E402
    NON_READY_BUDGET_VERDICT,
    ProfileError,
    RunBudgetState,
    WorkflowProfile,
    apply_workflow_profile_capabilities,
    parse_workflow_profile,
    preserve_required_capabilities,
    reject_kernel_immutable_profile_fields,
)
from graph.traceability import (  # noqa: E402
    build_coverage_edge,
    evaluate_evidence_predicate,
    stable_trace_ref_id,
)
from triage_lib import classify_tier, merge_tier_monotonic, classify_mechanical  # noqa: E402


def test_profile_rejects_cache_loop_bounds_budget_halt_nonready() -> None:
    with pytest.raises(ProfileError, match="kernel immutables"):
        reject_kernel_immutable_profile_fields({"cache": {"enabled": False}})
    with pytest.raises(ProfileError, match="kernel immutables"):
        reject_kernel_immutable_profile_fields({"loop_bounds": {"maxRounds": 3}})

    profile = WorkflowProfile(optimization="fast", max_cost=10.0, max_tokens=100)
    state = RunBudgetState(profile=profile)
    state.record_node_spend("node-a", cost=6.0, tokens=40)
    state.record_node_spend("node-b", cost=5.0, tokens=30)
    assert state.budget_verdict() == NON_READY_BUDGET_VERDICT
    assert not state.is_ready()

    injected = frozenset({CAPABILITY_AUTH, CAPABILITY_STANDARD_REVIEW})
    adjusted = apply_workflow_profile_capabilities(
        injected,
        WorkflowProfile(optimization="balanced"),
        repo_root=_REPO_ROOT,
    )
    assert CAPABILITY_AUTH in adjusted
    preserve_required_capabilities(baseline=injected, proposed=adjusted)


def test_traceref_pass_requires_verifier_class_at_headsha() -> None:
    head = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    stale = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    edge = build_coverage_edge("R24", "mechanical", head, blocking=True)
    assert edge.trace_ref_id == stable_trace_ref_id("R24", "mechanical", head_sha=head)

    stale_verdict = evaluate_evidence_predicate(
        edge,
        observed_head_sha=stale,
        observed_verifier_class="mechanical",
        current_head_sha=head,
    )
    assert stale_verdict.passed is False
    assert stale_verdict.reason == "stale-head"
    assert stale_verdict.blocking

    wrong_class = evaluate_evidence_predicate(
        edge,
        observed_head_sha=head,
        observed_verifier_class="human",
        current_head_sha=head,
    )
    assert wrong_class.passed is False
    assert wrong_class.reason == "wrong-verifier-class"

    ok = evaluate_evidence_predicate(
        edge,
        observed_head_sha=head,
        observed_verifier_class="mechanical",
        current_head_sha=head,
    )
    assert ok.passed is True
    assert ok.reason == "ok"


def test_triage_monotonic_union_one_file_auth_not_quick() -> None:
    one_file_auth = classify_tier(description="rename auth middleware", file_count=1)
    assert one_file_auth.tier == "standard"
    assert "auth" in one_file_auth.matched_risk_triggers

    rename_only = classify_tier(description="rename variable in helper", file_count=1)
    assert rename_only.tier == "quick"

    mechanical = classify_mechanical(description="small tweak", file_count=6)
    assert mechanical.tier == "full"
    merged = merge_tier_monotonic(mechanical, advisory_tier="standard")
    assert merged.tier == "full"

    with pytest.raises(ValueError, match="reduction path"):
        merge_tier_monotonic(mechanical, advisory_tier="full", authorized_reduction_to="quick")

    reduced = merge_tier_monotonic(
        mechanical,
        advisory_tier="full",
        authorized_reduction_to="standard",
        reduction_path="human-waiver",
    )
    assert reduced.tier == "standard"
    assert reduced.reduction_path == "human-waiver"


def test_invariants_and_capability_docs_regenerated() -> None:
    invariants = (_REPO_ROOT / "INVARIANTS.md").read_text(encoding="utf-8")
    for token in (
        "required-capability nonskip",
        "monotone re-detect",
        "reduction authorization",
        "absolute floor",
    ):
        assert token.lower() in invariants.lower()

    capabilities = (_REPO_ROOT / "CAPABILITIES.md").read_text(encoding="utf-8")
    assert "capability-registry.json" in capabilities
    assert "capability_docs.py" in capabilities

    parsed = parse_workflow_profile({"optimization": "balanced", "budgets": {"maxCost": 50}})
    assert parsed.optimization == "balanced"
    assert parsed.max_cost == 50.0
