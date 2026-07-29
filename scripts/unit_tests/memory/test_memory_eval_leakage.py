"""Leakage negative-control fixtures for memory-eval (PRD 082 R33)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
MEMORY_EVAL = SCRIPTS / "test" / "memory-eval"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(MEMORY_EVAL) not in sys.path:
    sys.path.insert(0, str(MEMORY_EVAL))

import leakage as me_leakage  # noqa: E402
import report as me_report  # noqa: E402


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return me_leakage.init_eval_repo(tmp_path)


def test_unauthorized_caller_negative_control_fails(repo: Path) -> None:
    with mock.patch("planning_cross_project_recall.redact_text", lambda text: text):
        result = me_leakage.run_unauthorized_caller(repo)
    assert result.blocked is True
    assert result.verdict == "denied"
    assert result.error == "cross-project-unauthorized"
    assert result.leakage_hits == 0


def test_inflated_authorized_projects_negative_control_fails(repo: Path) -> None:
    result = me_leakage.run_inflated_authorized_projects(repo)
    assert result.blocked is True
    assert result.verdict == "fail"
    assert result.error == "payload-widening-rejected"
    assert result.leakage_hits == 0


def test_spoofed_caller_project_key_negative_control_fails(repo: Path) -> None:
    with mock.patch("planning_cross_project_recall.redact_text", lambda text: text):
        result = me_leakage.run_spoofed_caller_project_key(repo)
    assert result.blocked is True
    assert result.verdict == "denied"
    assert result.error == "caller-project-key-mismatch"
    assert result.leakage_hits == 0


def test_passing_negative_control_fails_suite(repo: Path) -> None:
    with mock.patch("planning_cross_project_recall.redact_text", lambda text: text):
        with mock.patch.object(
            me_leakage.recall,
            "recall_cross_project",
            return_value={
                "verdict": "pass",
                "hits": [{"projectKey": "proj-z", "excerpt": "leaked"}],
            },
        ):
            result = me_leakage.run_unauthorized_caller(repo)
    assert result.blocked is False
    assert result.leakage_hits == 1


def test_all_negative_controls_blocked_in_metric(repo: Path) -> None:
    with mock.patch("planning_cross_project_recall.redact_text", lambda text: text):
        payload = me_leakage.compute_leakage_metrics(repo)
    assert payload["allNegativeControlsBlocked"] is True
    assert payload["positiveControlPassed"] is True
    assert payload["metrics"]["negative_controls_blocked"] == 3.0
    assert payload["metrics"]["cross_project_leakage"] == 0.0
    assert payload["metrics"]["authorized_recall_rate"] == 1.0


def test_unresolved_threshold_regression_exits_non_zero(repo: Path) -> None:
    with mock.patch("planning_cross_project_recall.redact_text", lambda text: text):
        payload = me_leakage.compute_leakage_metrics(repo)
    baseline = {
        "metrics": {
            "cross_project_leakage": {"max": 0.0},
            "negative_controls_blocked": {"min": 3.0},
            "authorized_recall_rate": {"min": 1.0},
        },
        "waivers": [],
    }
    report = me_report.compare_metrics(payload["metrics"], baseline)
    assert report["unresolved"] is False

    regressed = dict(payload["metrics"])
    regressed["cross_project_leakage"] = 1.0
    report = me_report.compare_metrics(regressed, baseline)
    assert report["unresolved"] is True
    assert report["maintainerActionRequired"] is True
    assert len(report["regressions"]) == 1


def test_report_cli_exits_non_zero_on_unresolved(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "metrics": {"cross_project_leakage": {"max": 0.0}},
                "waivers": [],
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(MEMORY_EVAL / "report.py"),
            "--metrics-json",
            json.dumps({"cross_project_leakage": 2.0}),
            "--baseline",
            str(baseline),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["unresolved"] is True


def test_expired_waiver_does_not_suppress_regression() -> None:
    baseline = {
        "metrics": {"cross_project_leakage": {"max": 0.0}},
        "waivers": [
            {
                "metric": "cross_project_leakage",
                "reason": "pilot investigation",
                "expires": "2000-01-01",
            }
        ],
    }
    report = me_report.compare_metrics({"cross_project_leakage": 1.0}, baseline)
    assert report["unresolved"] is True
    assert report["waived"] == []
