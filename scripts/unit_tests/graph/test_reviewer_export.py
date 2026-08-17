#!/usr/bin/env python3
"""Export surface tests — metadata only (PRD 273 R11)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.cohort import CohortIdentity  # noqa: E402
from graph.reviewer_metrics.elo import ReviewerRating  # noqa: E402
from graph.reviewer_metrics.export import ExportVerdict, build_export_report  # noqa: E402
from graph.reviewer_metrics.independence import ReviewerAxisIdentity  # noqa: E402


def _cohort() -> CohortIdentity:
    return CohortIdentity(
        persona_version="persona-v1",
        prompt_version="prompt-v1",
        model_version="model-v1",
        schema_version=1,
        policy_version="policy-v1",
    )


def _ratings(count: int) -> tuple[ReviewerRating, ...]:
    cohort = _cohort()
    return tuple(
        ReviewerRating(f"reviewer-{index}", 1500.0 + index, cohort)
        for index in range(count)
    )


def _identities(count: int) -> tuple[ReviewerAxisIdentity, ...]:
    return tuple(
        ReviewerAxisIdentity(
            persona_id=f"persona-{index}",
            model_id=f"model-{index % 2}",
            prompt_template_id=f"prompt-{index % 3}",
            cluster_id=f"cluster-{index % 4}",
        )
        for index in range(count)
    )


def test_export_top_bottom_without_transcripts() -> None:
    ratings = _ratings(12)
    identities = _identities(12)
    report = build_export_report(ratings, identities, top_n=3, bottom_n=3)
    payload = report.to_dict()
    assert report.verdict == ExportVerdict.OK
    assert len(report.top) == 3
    assert len(report.bottom) == 3
    forbidden = {"transcript", "findingBody", "prompt", "patch", "secret", "content"}
    assert forbidden.isdisjoint(set(payload.keys()))
    for item in payload["top"] + payload["bottom"]:
        assert forbidden.isdisjoint(set(item.keys()))
    assert "independenceWarnings" in payload


def test_export_unknown_when_insufficient_evidence() -> None:
    ratings = _ratings(4)
    identities = _identities(4)
    report = build_export_report(ratings, identities, top_n=2, bottom_n=2, min_n=10)
    assert report.verdict == ExportVerdict.UNKNOWN
    assert report.top == ()
    assert report.bottom == ()


def test_export_includes_independence_warnings() -> None:
    identities = (
        ReviewerAxisIdentity("persona-a", "shared-model", "prompt-a", "cluster-1"),
        ReviewerAxisIdentity("persona-b", "shared-model", "prompt-b", "cluster-2"),
    ) + _identities(10)
    report = build_export_report(_ratings(12), identities, top_n=1, bottom_n=1)
    assert any("correlated:" in warning for warning in report.independence_warnings)
