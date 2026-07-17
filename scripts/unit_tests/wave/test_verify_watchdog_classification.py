"""PRD 072 R2 — solely-watchdog vs mixed verify classification."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_failure import (
    classify_verify_failure,
    cmd_blast_radius_apply,
    enrich_verify_result,
    verify_blast_radius_applies,
    verify_failure_cause,
)


def _watchdog_stdout() -> str:
    return json.dumps(
        {
            "verdict": "fail",
            "halt": "verify-watchdog-exhausted",
            "watchdogExhausted": True,
            "lastSuiteId": "slow-suite",
        }
    )


def test_solely_watchdog_structured_field_is_environmental() -> None:
    outcome = {
        "verdict": "fail",
        "results": [
            {
                "command": "pytest",
                "exitCode": 1,
                "watchdogExhausted": True,
                "stdoutTail": _watchdog_stdout(),
            }
        ],
    }
    assert classify_verify_failure(outcome) == "environmental"
    assert verify_failure_cause(outcome) == "verify:environmental"
    assert verify_blast_radius_applies(outcome) is False


def test_solely_watchdog_marker_without_product_assertion_is_environmental() -> None:
    outcome = {
        "verdict": "fail",
        "results": [
            {
                "command": "bash verify",
                "exitCode": 1,
                "stderrTail": "verify-watchdog-exhausted after budget",
            }
        ],
    }
    assert classify_verify_failure(outcome) == "environmental"
    assert verify_blast_radius_applies(outcome) is False


def test_mixed_watchdog_and_assertion_is_product_regression() -> None:
    outcome = {
        "verdict": "fail",
        "results": [
            {
                "command": "pytest scripts/unit_tests/wave",
                "exitCode": 1,
                "watchdogExhausted": True,
                "stdoutTail": _watchdog_stdout(),
            },
            {
                "command": "pytest scripts/unit_tests/other",
                "exitCode": 1,
                "stderrTail": "AssertionError: expected True",
            },
        ],
    }
    assert classify_verify_failure(outcome) == "regression"
    assert verify_failure_cause(outcome) == "verify:failed"
    assert verify_blast_radius_applies(outcome) is True


def test_first_marker_wins_regression_when_mixed_environmental_and_assertion() -> None:
    """Environmental marker in one command must not mask product assertion in another (R2)."""
    outcome = {
        "verdict": "fail",
        "results": [
            {
                "command": "build-chain-sync --check",
                "exitCode": 1,
                "stderrTail": "build-chain-sync drift",
            },
            {
                "command": "pytest",
                "exitCode": 1,
                "stderrTail": "FAILED scripts/unit_tests/foo.py::test_bar - AssertionError",
            },
        ],
    }
    assert classify_verify_failure(outcome) == "regression"
    assert verify_blast_radius_applies(outcome) is True


def test_enrich_verify_result_prefers_structured_watchdog_json() -> None:
    result = enrich_verify_result(
        {
            "command": "verify",
            "exitCode": 1,
            "stdoutTail": _watchdog_stdout(),
        }
    )
    assert result.get("watchdogExhausted") is True


def test_solely_watchdog_verify_after_merge_skips_blast_radius(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wave_failure import cmd_verify_run_after_merge

    state = {
        "target": {"branch": "feat/x"},
        "phases": {"1": {"slug": "upstream", "status": "green-merged"}},
        "verifyRemediationAttempts": {},
    }
    outcome = {
        "verdict": "fail",
        "results": [{"command": "verify", "exitCode": 1, "watchdogExhausted": True}],
    }
    calls: list[list[str]] = []

    def _run(cmd, **kwargs):
        calls.append(list(cmd))
        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Proc()

    monkeypatch.setattr("wave_failure.load_state", lambda _root: state)
    monkeypatch.setattr("wave_failure.load_state_for_deliver", lambda _root, target=None: state)
    monkeypatch.setattr("wave_failure.run_verify_suite", lambda *_a, **_k: outcome)
    monkeypatch.setattr("wave_failure.resolve_orchestrator_worktree", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr("wave_failure.post_merge_verify_scope", lambda _root: "phase")
    monkeypatch.setattr("wave_failure.save_state", lambda *_a, **_k: None)
    monkeypatch.setattr("wave_failure.subprocess.run", _run)

    with pytest.raises(SystemExit) as exc:
        cmd_verify_run_after_merge(tmp_path, ["--phase-slug", "upstream"])
    assert exc.value.code == 10
    assert not any("blast-radius" in " ".join(cmd) for cmd in calls)


def test_mixed_verify_after_merge_applies_blast_radius(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wave_failure import cmd_verify_run_after_merge

    state = {
        "target": {"branch": "feat/x"},
        "phases": {"1": {"slug": "upstream", "status": "green-merged"}},
    }
    outcome = {
        "verdict": "fail",
        "results": [
            {"command": "verify", "exitCode": 1, "watchdogExhausted": True},
            {"command": "pytest", "exitCode": 1, "stderrTail": "AssertionError: boom"},
        ],
    }
    calls: list[list[str]] = []

    def _run(cmd, **kwargs):
        calls.append(list(cmd))
        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Proc()

    monkeypatch.setattr("wave_failure.load_state", lambda _root: state)
    monkeypatch.setattr("wave_failure.load_state_for_deliver", lambda _root, target=None: state)
    monkeypatch.setattr("wave_failure.run_verify_suite", lambda *_a, **_k: outcome)
    monkeypatch.setattr("wave_failure.resolve_orchestrator_worktree", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr("wave_failure.post_merge_verify_scope", lambda _root: "phase")
    monkeypatch.setattr("wave_failure.save_state", lambda *_a, **_k: None)
    monkeypatch.setattr("wave_failure.subprocess.run", _run)

    with pytest.raises(SystemExit) as exc:
        cmd_verify_run_after_merge(tmp_path, ["--phase-slug", "upstream"])
    assert exc.value.code == 20
    assert any("blast-radius" in " ".join(cmd) for cmd in calls)
