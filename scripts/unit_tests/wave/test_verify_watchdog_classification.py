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


# --- PRD 325 phase 3: blast-radius clear on green-merged dependents ---

from typing import Any

from wave_failure import cmd_blast_radius_dependents
from wave_phase_pr import phase_green_merged
from wave_state import record_blast_radius


def _blast_plan() -> dict[str, Any]:
    return {"edges": [{"from": "1", "to": "2"}, {"from": "1", "to": "3"}]}


def _blast_state() -> dict[str, Any]:
    return {
        "target": {"branch": "feat/deliver-finalize-consumer-resilience"},
        "planHash": "abc",
        "phases": {
            "1": {"slug": "upstream", "status": "blocked", "branch": "feat/upstream"},
            "2": {
                "slug": "dep-merged",
                "status": "green-merged",
                "branch": "feat/dep-merged",
                "openPrNumber": 101,
            },
            "3": {
                "slug": "dep-open",
                "status": "in-flight",
                "branch": "feat/dep-open",
                "openPrNumber": 102,
            },
        },
    }


def _host_merged(_root: Path, meta: dict[str, Any]) -> dict[str, Any]:
    number = meta.get("openPrNumber")
    if number == 101:
        return {"verdict": "ok", "merged": True}
    if number == 102:
        return {"verdict": "ok", "merged": False}
    return {"verdict": "indeterminate", "detail": "host-unavailable"}


@pytest.fixture()
def blast_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = _blast_state()
    saved: list[dict[str, Any]] = []

    monkeypatch.setattr("wave_failure.load_state", lambda _root: state)
    monkeypatch.setattr("wave_failure.load_state_for_deliver", lambda _root, target=None: state)
    monkeypatch.setattr("wave_failure.load_plan", lambda _root, _state=None: _blast_plan())
    monkeypatch.setattr(
        "wave_failure.save_state",
        lambda _root, new_state: saved.append(dict(new_state)),
    )
    monkeypatch.setattr("wave_failure.append_log", lambda *_a, **_k: None)
    monkeypatch.setattr("wave_phase_pr.phase_pr_host_merge_verdict", _host_merged)
    return tmp_path, state, saved


def test_phase_green_merged_conservative_on_indeterminate_host() -> None:
    meta = {"slug": "dep", "status": "green-merged", "branch": "feat/dep"}
    with patch("wave_phase_pr.phase_pr_host_merge_verdict", return_value={"verdict": "indeterminate"}):
        assert phase_green_merged(Path("/tmp"), meta) is False


def test_blast_radius_apply_clears_green_merged_dependent(blast_harness) -> None:
    tmp_path, _state, saved = blast_harness
    with pytest.raises(SystemExit) as exc:
        cmd_blast_radius_apply(tmp_path, ["--phase-slug", "upstream"])
    assert exc.value.code == 0
    final = saved[-1]
    assert final["phases"]["2"]["status"] == "green-merged"
    assert final["phases"]["3"]["status"] == "blocked"
    blast = final["blastRadius"]
    assert len(blast["cleared"]) == 1
    assert blast["cleared"][0]["reason"] == "green-merged"
    assert len(blast["applied"]) == 1


def test_blast_radius_apply_all_green_is_noop(blast_harness, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path, state, saved = blast_harness
    state["phases"]["3"]["status"] = "green-merged"
    state["phases"]["3"]["openPrNumber"] = 103
    monkeypatch.setattr(
        "wave_phase_pr.phase_pr_host_merge_verdict",
        lambda _r, _m: {"verdict": "ok", "merged": True},
    )
    with pytest.raises(SystemExit) as exc:
        cmd_blast_radius_apply(tmp_path, ["--phase-slug", "upstream"])
    assert exc.value.code == 0
    assert saved[-1]["blastRadius"]["applied"] == []
    assert len(saved[-1]["blastRadius"]["cleared"]) == 2


def test_blast_radius_dependents_reports_cleared(blast_harness, capsys: pytest.CaptureFixture[str]) -> None:
    tmp_path, _state, _saved = blast_harness
    with pytest.raises(SystemExit) as exc:
        cmd_blast_radius_dependents(tmp_path, ["--phase-slug", "upstream"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["blastRadius"]["cleared"][0]["reason"] == "green-merged"


def test_record_blast_radius_idempotent_moves_applied_to_cleared() -> None:
    state: dict[str, Any] = {
        "blastRadius": {
            "applied": [{"phaseId": "3", "phaseSlug": "dep-open"}],
            "cleared": [],
            "predicate": "phase_green_merged",
            "at": "2026-01-01T00:00:00Z",
        }
    }
    record_blast_radius(
        state,
        applied=[],
        cleared=[{"phaseId": "3", "phaseSlug": "dep-open", "reason": "green-merged"}],
        predicate="phase_green_merged",
        at="2026-01-02T00:00:00Z",
    )
    assert state["blastRadius"]["applied"] == []
    assert state["blastRadius"]["cleared"][0]["phaseId"] == "3"
