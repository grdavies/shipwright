#!/usr/bin/env python3
"""PRD 272 phase-6 benchmark harness tests (R17, R18)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.benchmark.acceptance import TraceEvidence, evaluate_trace_acceptance  # noqa: E402
from graph.benchmark.manifest import (  # noqa: E402
    BenchmarkManifestError,
    REQUIRED_CASE_FIELDS,
    REQUIRED_MANIFEST_FIELDS,
    WORKFLOW_TYPES,
    corpus_coverage_report,
    default_manifest_path,
    load_manifest,
    validate_manifest,
)
from graph.benchmark.runner import (  # noqa: E402
    PairedEvalRunner,
    run_fake_provider_lane,
    run_paired_eval,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_benchmark_case_manifest_required_fields() -> None:
    manifest_path = default_manifest_path(_repo_root())
    manifest = load_manifest(manifest_path)
    raw = manifest.to_dict()
    assert REQUIRED_MANIFEST_FIELDS <= set(raw.keys())
    for case in manifest.cases:
        assert REQUIRED_CASE_FIELDS <= set(case.to_dict().keys())
    assert manifest.workflow_types_present() >= WORKFLOW_TYPES
    report = corpus_coverage_report(manifest)
    assert report["complete"] is True
    assert report["caseCount"] >= len(WORKFLOW_TYPES)
    assert manifest.holdout_cases()


def test_manifest_rejects_incomplete_corpus() -> None:
    manifest_path = default_manifest_path(_repo_root())
    manifest = load_manifest(manifest_path)
    broken = manifest.to_dict()
    broken["cases"] = [
        case
        for case in broken["cases"]
        if case["workflowType"] != "docs"
    ]
    from graph.benchmark.manifest import BenchmarkManifest

    with pytest.raises(BenchmarkManifestError, match="missing workflow types"):
        validate_manifest(BenchmarkManifest.from_dict(broken))


def test_paired_canonical_candidate_fake_provider_lane() -> None:
    manifest_path = default_manifest_path(_repo_root())
    head_sha = "abc123def456"
    lane_report = run_fake_provider_lane(
        manifest_path,
        lane="ci-fake-provider",
        head_sha=head_sha,
    )
    assert lane_report["lane"] == "ci-fake-provider"
    assert lane_report["holdoutExcluded"] is True
    assert lane_report["recordCount"] > 0
    report = run_paired_eval(manifest_path, head_sha=head_sha, include_holdout=False)
    assert report.canonical_lane == "canonical"
    assert report.candidate_lane == "candidate"
    assert report.holdout_case_ids
    assert len(report.eval_case_ids) < len(load_manifest(manifest_path).cases)
    assert report.canonical_metrics.acceptance_rate >= 0.0
    assert report.canonical_metrics.r24_acceptance_predicate


def test_holdout_split_excludes_cases_from_eval_lane() -> None:
    manifest = load_manifest(default_manifest_path(_repo_root()))
    runner = PairedEvalRunner(manifest, head_sha="head0001")
    report = runner.run(include_holdout=False)
    eval_ids = set(report.eval_case_ids)
    holdout_ids = set(report.holdout_case_ids)
    assert holdout_ids.isdisjoint(eval_ids)


def test_r24_acceptance_predicate_requires_verifier_class_at_headsha() -> None:
    evidence = TraceEvidence(
        trace_ref_id="trace:fixture",
        head_sha="head1111",
        verifier_class="mechanical",
        verdict="pass",
    )
    assert evaluate_trace_acceptance(
        evidence,
        current_head_sha="head1111",
        required_verifier_class="mechanical",
    )
    assert not evaluate_trace_acceptance(
        evidence,
        current_head_sha="head2222",
        required_verifier_class="mechanical",
    )
    stale = TraceEvidence(
        trace_ref_id="trace:fixture",
        head_sha="head1111",
        verifier_class="advisory",
        verdict="pass",
    )
    assert not evaluate_trace_acceptance(
        stale,
        current_head_sha="head1111",
        required_verifier_class="mechanical",
    )
