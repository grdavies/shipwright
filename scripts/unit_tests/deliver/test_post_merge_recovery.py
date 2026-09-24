"""Fail-closed recovery for a verified merge whose normal closeout was interrupted."""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import wave_merge
from wave_merge import prepare_recovery_cursor, recover_verified_merge_state, recovery_pr_close_acceptable


def blocked_state() -> dict:
    return {
        "verdict": "blocked",
        "cause": "remediation-budget-exhausted",
        "mergeQueue": [],
        "mergeJournal": None,
        "completedMerges": [{"phase": "p2", "mergeCommit": "merge-sha"}],
        "mergedPhases": [{"phaseSlug": "p2", "mergeCommit": "merge-sha"}],
        "phases": {
            "1": {"slug": "p1", "status": "teardown-complete"},
            "2": {"slug": "p2", "status": "blocked", "cause": "verify:failed", "mergeCommit": "merge-sha"},
            "3": {"slug": "p3", "status": "blocked", "cause": "blast-radius:upstream-blocked:p2"},
            "4": {"slug": "p4", "status": "blocked", "cause": "blast-radius:upstream-blocked:p2"},
        },
        "blastRadius": {"applied": [{"phaseId": "3", "phaseSlug": "p3"}, {"phaseId": "4", "phaseSlug": "p4"}]},
    }


def test_recovery_preserves_prior_closeout_and_restores_only_scoped_dependents() -> None:
    before = blocked_state()
    original = copy.deepcopy(before)
    after, restored = recover_verified_merge_state(before, "p2", "merge-sha")
    assert before == original
    assert restored == ["3", "4"]
    assert after["phases"]["1"]["status"] == "teardown-complete"
    assert after["phases"]["2"]["status"] == "teardown-pending"
    assert all(after["phases"][pid]["status"] == "pending" for pid in restored)
    assert after["verdict"] == "running" and "cause" not in after
    assert after["blastRadius"]["applied"] == []


def test_cursor_discards_only_stale_halt_and_recomputes_next_action(monkeypatch, tmp_path: Path) -> None:
    import wave_deliver_loop

    state, _ = recover_verified_merge_state(blocked_state(), "p2", "merge-sha")
    state.update(budgetHalt=True, blockerReport="old-report", haltResume={"old": True}, lockReleased=False, nextAction="terminal", lastProgressKey="old", noProgressStreak=4)
    state["remediationAttempts"] = {"2": 2}
    state.update(target="feat/example", orchestratorWorktree={"path": str(tmp_path)}, baseCapture={"ok": True}, currentWave=2)
    monkeypatch.setattr(wave_deliver_loop, "load_plan", lambda *_: {"mode": "phase", "waves": [["1"], ["2"], ["3", "4"]], "edges": []})
    # No Git worktree exists in this unit fixture; the desync probe is tested separately.
    monkeypatch.setattr(wave_deliver_loop, "check_deliver_hang_desync", lambda *_: None)
    assert prepare_recovery_cursor(tmp_path, state) == "phase-teardown-run"
    assert state["nextAction"] == "phase-teardown-run"
    assert state["remediationAttempts"] == {"2": 2}
    assert state["noProgressStreak"] == 0 and state["lastProgressKey"] is None
    assert all(key not in state for key in ("budgetHalt", "blockerReport", "haltResume", "lockReleased"))


def test_pr_close_accepts_only_actual_benign_skip_shape(tmp_path: Path) -> None:
    from wave_phase_pr import close_superseded_phase_prs

    skipped = close_superseded_phase_prs(
        tmp_path,
        {"phases": {"2": {"slug": "p2", "status": "blocked"}}},
        phase_slug="p2",
    )
    assert skipped == {"verdict": "skip", "reason": "phase-not-green-merged", "phase": "p2", "closed": []}
    assert recovery_pr_close_acceptable(skipped, "p2")
    assert not recovery_pr_close_acceptable({**skipped, "phase": "other"}, "p2")
    assert not recovery_pr_close_acceptable({**skipped, "reason": "host-error"}, "p2")
    assert not recovery_pr_close_acceptable({"verdict": "partial"}, "p2")


@pytest.mark.parametrize("change", [
    lambda s: s["phases"]["2"].update(cause="verify:environmental"),
    lambda s: s["phases"]["2"].update(mergeCommit="other-sha"),
    lambda s: s.update(verdict="running"),
    lambda s: s.update(mergeQueue=[{"phaseSlug": "p3"}]),
    lambda s: s.update(mergeJournal={"phase": "p3"}),
    lambda s: s.update(completedMerges=[]),
    lambda s: s.update(mergedPhases=[]),
    lambda s: s["phases"]["3"].update(cause="blast-radius:upstream-blocked:p1"),
])
def test_recovery_rejects_changed_or_unrelated_blocked_state(change) -> None:
    state = blocked_state()
    change(state)
    with pytest.raises(ValueError):
        recover_verified_merge_state(state, "p2", "merge-sha")


def test_command_reverifies_exact_target_before_saving(monkeypatch, tmp_path: Path) -> None:
    state = blocked_state()
    state["target"] = "feat/example"
    state["orchestratorWorktree"] = {"path": str(tmp_path)}
    state["phases"]["2"]["branch"] = "feat/p2"
    monkeypatch.setattr(wave_merge, "load_state", lambda _root: copy.deepcopy(state))
    monkeypatch.setattr(wave_merge, "resolve_orchestrator_worktree", lambda *_: tmp_path)
    monkeypatch.setattr(wave_merge, "load_workflow_config", lambda *_: {})
    monkeypatch.setattr(wave_merge, "remote_name", lambda *_: "origin")
    monkeypatch.setattr(wave_merge, "remote_ref", lambda *_: "origin/feat/example")

    def git_ok(args, **_kwargs):
        if args[0] == "fetch":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "merge-base":
            return subprocess.CompletedProcess(args, 0, "", "")
        ref = args[-1]
        sha = {"feat/example": "target-sha", "HEAD": "target-sha", "origin/feat/example": "target-sha", "feat/p2": "phase-sha"}[ref]
        return subprocess.CompletedProcess(args, 0, sha + "\n", "")

    monkeypatch.setattr(wave_merge, "git_run", git_ok)
    import wave_failure
    import wave_post_merge
    import wave_phase_pr
    import planning_progress
    import wave_terminal
    import wave_deliver_loop
    import wave_state

    monkeypatch.setattr(wave_failure, "post_merge_verify_scope", lambda *_: "phase")
    verifier = Mock(return_value={"verdict": "pass", "results": [{"command": "test", "exitCode": 0}]})
    monkeypatch.setattr(wave_post_merge, "run_post_merge_verify", verifier)
    monkeypatch.setattr(wave_terminal, "phase_ack_cadence", lambda *_: 0)
    monkeypatch.setattr(wave_deliver_loop, "load_plan", lambda *_: {"mode": "phase"})
    monkeypatch.setattr(wave_deliver_loop, "compute_next_action", lambda *_: {"action": "phase-teardown-run"})
    monkeypatch.setattr(wave_phase_pr, "close_superseded_phase_prs", lambda *_args, **_kwargs: {"verdict": "ok"})
    monkeypatch.setattr(planning_progress, "sync_phase_done", lambda *_: {"verdict": "ok", "skipped": True})
    monkeypatch.setattr(wave_state, "append_log", lambda *_args, **_kwargs: None)
    saved = []
    monkeypatch.setattr(wave_merge, "save_state", lambda _root, value: saved.append(copy.deepcopy(value)))
    monkeypatch.setattr(wave_merge, "emit", lambda value, *_args: None)
    wave_merge.cmd_merge_recover_after_verify(tmp_path, ["--phase-slug", "p2"])
    assert verifier.call_count == 1
    assert len(saved) == 1
    assert saved[0]["phases"]["2"]["status"] == "teardown-pending"
    assert saved[0]["phases"]["1"]["status"] == "teardown-complete"
    assert saved[0]["nextAction"] == "phase-teardown-run"

    saved.clear()
    monkeypatch.setattr(wave_phase_pr, "close_superseded_phase_prs", lambda *_args, **_kwargs: {"verdict": "skip", "reason": "phase-not-green-merged", "phase": "p2", "closed": []})
    wave_merge.cmd_merge_recover_after_verify(tmp_path, ["--phase-slug", "p2"])
    assert len(saved) == 1

    # Closeout runs before the state transition; failures leave the blocked state retryable.
    saved.clear()
    monkeypatch.setattr(wave_merge, "fail", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("closeout blocked")))
    monkeypatch.setattr(wave_phase_pr, "close_superseded_phase_prs", lambda *_args, **_kwargs: {"verdict": "partial"})
    with pytest.raises(ValueError, match="closeout blocked"):
        wave_merge.cmd_merge_recover_after_verify(tmp_path, ["--phase-slug", "p2"])
    assert saved == []
    monkeypatch.setattr(wave_phase_pr, "close_superseded_phase_prs", lambda *_args, **_kwargs: {"verdict": "ok"})
    monkeypatch.setattr(planning_progress, "sync_phase_done", lambda *_: {"verdict": "fail"})
    with pytest.raises(ValueError, match="closeout blocked"):
        wave_merge.cmd_merge_recover_after_verify(tmp_path, ["--phase-slug", "p2"])
    assert saved == []


def test_command_refuses_failed_verification_without_state_write(monkeypatch, tmp_path: Path) -> None:
    state = blocked_state()
    state["target"] = "feat/example"
    state["phases"]["2"]["branch"] = "feat/p2"
    monkeypatch.setattr(wave_merge, "load_state", lambda _root: copy.deepcopy(state))
    monkeypatch.setattr(wave_merge, "resolve_orchestrator_worktree", lambda *_: tmp_path)
    monkeypatch.setattr(wave_merge, "load_workflow_config", lambda *_: {})
    monkeypatch.setattr(wave_merge, "remote_name", lambda *_: "origin")
    monkeypatch.setattr(wave_merge, "remote_ref", lambda *_: "origin/feat/example")
    monkeypatch.setattr(wave_merge, "git_run", lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, "same-sha\n", ""))
    import wave_failure
    import wave_post_merge
    import wave_deliver_loop

    monkeypatch.setattr(wave_failure, "post_merge_verify_scope", lambda *_: "phase")
    monkeypatch.setattr(wave_post_merge, "run_post_merge_verify", lambda *_args, **_kwargs: {"verdict": "fail", "results": [{"exitCode": 1}]})
    monkeypatch.setattr(wave_deliver_loop, "load_plan", lambda *_: {"mode": "phase"})
    monkeypatch.setattr(wave_deliver_loop, "compute_next_action", lambda *_: {"action": "phase-teardown-run"})
    saved = Mock()
    monkeypatch.setattr(wave_merge, "save_state", saved)
    monkeypatch.setattr(wave_merge, "fail", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("blocked")))
    with pytest.raises(ValueError, match="blocked"):
        wave_merge.cmd_merge_recover_after_verify(tmp_path, ["--phase-slug", "p2"])
    saved.assert_not_called()
