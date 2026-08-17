#!/usr/bin/env python3
"""Calibration and cost reporter tests (PRD 273 R3, R4, R14, R17)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.calibration import (  # noqa: E402
    CalibrationVerdict,
    FindingCalibrationInput,
    report_calibration,
)
from graph.reviewer_metrics.cost import (  # noqa: E402
    CostProvenance,
    CostSignal,
    CostVerdict,
    FindingCostInput,
    report_cost,
)
from graph.reviewer_metrics.eval_report import (  # noqa: E402
    EvalInput,
    EvalVerdict,
    report_eval_uncertainty,
)
from graph.reviewer_metrics.surviving import CouplingEvidence  # noqa: E402


def test_calibration_confidence_vs_exogenous_tp() -> None:
    findings = (
        FindingCalibrationInput(
            finding_id="f-high-tp",
            confidence=0.9,
            attribution_window="2026-08-01/2026-08-16",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
        FindingCalibrationInput(
            finding_id="f-high-fp",
            confidence=0.85,
            attribution_window="2026-08-01/2026-08-16",
            evidence=[CouplingEvidence("exogenous-human", "rejected")],
        ),
        FindingCalibrationInput(
            finding_id="f-low-tp",
            confidence=0.2,
            attribution_window="2026-08-01/2026-08-16",
            evidence=[CouplingEvidence("exogenous-post-merge", "confirmed")],
        ),
        FindingCalibrationInput(
            finding_id="f-other-window",
            confidence=0.5,
            attribution_window="2026-07-01/2026-07-31",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
    )
    reports = report_calibration(findings, bucket_size=0.5)
    august = next(
        report
        for report in reports
        if report.attribution_window == "2026-08-01/2026-08-16"
    )
    assert august.verdict == CalibrationVerdict.OK
    assert august.labeled_count == 3
    assert august.exogenous_tp_count == 2
    assert august.exogenous_tp_rate == 2 / 3
    high_bucket = next(
        bucket for bucket in august.buckets if bucket.confidence_floor >= 0.5
    )
    assert high_bucket.labeled_count == 2
    assert high_bucket.exogenous_tp_count == 1
    assert high_bucket.exogenous_tp_rate == 0.5


def test_calibration_censored_excluded_from_rates() -> None:
    findings = (
        FindingCalibrationInput(
            finding_id="f-unlabeled",
            confidence=0.95,
            attribution_window="window-a",
            evidence=[],
        ),
        FindingCalibrationInput(
            finding_id="f-tp",
            confidence=0.8,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
    )
    report = report_calibration(findings, windows=("window-a",), bucket_size=0.5)[0]
    assert report.labeled_count == 1
    assert report.exogenous_tp_count == 1
    assert report.exogenous_tp_rate == 1.0


def test_cost_per_surviving_finding_with_proxy() -> None:
    findings = (
        FindingCostInput(
            finding_id="surv-1",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
            costs=(
                CostSignal(1.0, CostProvenance.DIRECT.value),
                CostSignal(0.5, CostProvenance.PROXY.value),
            ),
        ),
        FindingCostInput(
            finding_id="surv-2",
            evidence=[CouplingEvidence("exogenous-human", "confirmed")],
            costs=(
                CostSignal(0.5, CostProvenance.CACHE.value),
                CostSignal(0.25, CostProvenance.RETRY.value),
            ),
        ),
        FindingCostInput(
            finding_id="censored",
            evidence=[],
            costs=(CostSignal(9.0, CostProvenance.DIRECT.value),),
        ),
    )
    report = report_cost(findings)
    assert report.verdict == CostVerdict.OK
    assert report.surviving_count == 2
    assert report.total_cost == 2.25
    assert report.cost_per_surviving == 1.125
    assert report.provenance_breakdown[CostProvenance.DIRECT.value] == 1.0
    assert report.provenance_breakdown[CostProvenance.PROXY.value] == 0.5
    assert report.provenance_breakdown[CostProvenance.CACHE.value] == 0.5
    assert report.provenance_breakdown[CostProvenance.RETRY.value] == 0.25


def test_cost_zero_denominator_unknown() -> None:
    findings = (
        FindingCostInput(
            finding_id="censored-only",
            evidence=[],
            costs=(CostSignal(1.0, CostProvenance.DIRECT.value),),
        ),
        FindingCostInput(
            finding_id="missing-cost",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
            costs=(CostSignal(None, CostProvenance.PROXY.value),),
        ),
    )
    report = report_cost(findings)
    assert report.surviving_count == 0
    assert report.cost_per_surviving is None
    assert report.verdict == CostVerdict.UNKNOWN


def test_cost_mixed_missing_and_proxy_excluded() -> None:
    findings = (
        FindingCostInput(
            finding_id="surv-direct",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
            costs=(CostSignal(2.0, CostProvenance.DIRECT.value),),
        ),
        FindingCostInput(
            finding_id="surv-no-cost",
            evidence=[CouplingEvidence("exogenous-human", "confirmed")],
            costs=(CostSignal(None, CostProvenance.PROXY.value),),
        ),
    )
    report = report_cost(findings)
    assert report.surviving_count == 1
    assert report.excluded_count == 1
    assert report.cost_per_surviving == 2.0


def test_offline_eval_unknown_when_insufficient_evidence() -> None:
    findings = (
        EvalInput(
            finding_id="only-one",
            confidence=0.7,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
            rank=1,
        ),
    )
    report = report_eval_uncertainty(findings, min_evidence=5)
    assert report.verdict == EvalVerdict.UNKNOWN
    assert report.label_coverage is None
    assert report.calibration_error is None


def test_offline_eval_reports_coverage_and_calibration_error() -> None:
    findings = tuple(
        EvalInput(
            finding_id=f"f-{index}",
            confidence=0.8 if index % 2 == 0 else 0.3,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
            rank=index,
        )
        for index in range(6)
    )
    report = report_eval_uncertainty(findings, min_evidence=5)
    assert report.verdict == EvalVerdict.OK
    assert report.label_coverage == 1.0
    assert report.unresolved_rate == 0.0
    assert report.calibration_error is not None
    assert report.ranking_stability is not None
