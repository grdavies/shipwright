#!/usr/bin/env python3
"""Independence negative suite — report-only, non-gating (PRD 273 R5, R15)."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics import independence  # noqa: E402
from graph.reviewer_metrics.independence import (  # noqa: E402
    CorrelationKind,
    ReviewerAxisIdentity,
    score_independence,
)
from graph.verifier_policies import (  # noqa: E402
    VerifierKind,
    VerifierResult,
    evaluate_verifiers,
)

FORBIDDEN_SYMBOLS = frozenset(
    {
        "evaluate_verifiers",
        "kernel",
        "escalation",
        "binding",
        "quorum",
        "promote",
        "gate_plan",
    }
)


def _judgment_dispatch() -> dict[str, str]:
    return {
        "dispatch": {
            "modelFamily": "gpt-4",
            "persona": "security",
            "promptTemplate": "panel-v1",
            "contextSource": "diff",
            "evidenceSource": "ci",
        }
    }


def test_independence_flags_correlated_pair() -> None:
    identities = (
        ReviewerAxisIdentity("persona-a", "model-x", prompt_template_id="prompt-v1"),
        ReviewerAxisIdentity("persona-b", "model-x", prompt_template_id="prompt-v2"),
        ReviewerAxisIdentity("persona-c", "model-y", prompt_template_id="prompt-v1"),
        ReviewerAxisIdentity("persona-d", "model-z", cluster_id="cluster-1"),
        ReviewerAxisIdentity("persona-e", "model-w", cluster_id="cluster-1"),
    )
    report = score_independence(identities)
    shared_model = next(
        pair
        for pair in report.correlated_pairs
        if {pair.persona_a, pair.persona_b} == {"persona-a", "persona-b"}
    )
    assert CorrelationKind.SHARED_MODEL.value in shared_model.reasons
    shared_prompt = next(
        pair
        for pair in report.correlated_pairs
        if {pair.persona_a, pair.persona_b} == {"persona-a", "persona-c"}
    )
    assert CorrelationKind.SHARED_PROMPT.value in shared_prompt.reasons
    cluster_pair = next(
        pair
        for pair in report.correlated_pairs
        if {pair.persona_a, pair.persona_b} == {"persona-d", "persona-e"}
    )
    assert CorrelationKind.IDENTICAL_CLUSTER.value in cluster_pair.reasons
    assert report.advisory_only is True


def test_independence_cannot_change_quorum_or_kernel() -> None:
    source = inspect.getsource(independence)
    lowered = source.lower()
    for symbol in FORBIDDEN_SYMBOLS:
        assert symbol not in lowered

    shared = _judgment_dispatch()
    results = [
        VerifierResult(
            f"review-{index}",
            VerifierKind.JUDGMENT,
            True,
            dispatch_record=shared,
        )
        for index in range(3)
    ]
    before = evaluate_verifiers(results, judgment_quorum=2)
    report = score_independence(
        (
            ReviewerAxisIdentity("persona-a", "model-x"),
            ReviewerAxisIdentity("persona-b", "model-x"),
        )
    )
    after = evaluate_verifiers(results, judgment_quorum=2)
    assert before == after
    assert before.passed is False
    assert report.advisory_only is True
    assert len(report.correlated_pairs) == 1
