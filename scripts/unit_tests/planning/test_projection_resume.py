"""Integration tests for resumable projection state (PRD 344 R3–R4)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import projection_state as ps
import wave_living_docs as living


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=path,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git_init(root)
    # Avoid ambient deliver env redirecting projection root during unit tests.
    for key in ("SW_ORCHESTRATOR_WORKTREE", "SW_REPO_ROOT"):
        monkeypatch.delenv(key, raising=False)
    return root


def test_projection_state_persists_partial_progress_and_resume_order(repo: Path) -> None:
    """R4 / O: one resume — completed steps stay done; pending continue in order."""
    scope = ps.projection_scope(prd="344", slug="demo", action="reconcile")
    state = ps.empty_projection_state(
        scope=scope,
        prd="344",
        slug="demo",
        worktree=str(repo),
    )
    ps.mark_step_complete(state, "index", {"verdict": "pass", "prd": "344"})
    ps.record_interrupt(
        state,
        cause="projection-rate-limited",
        error="429 rate limited",
        resume_command=ps.build_projection_resume_command(repo),
        step="gap-resolve",
    )
    path = ps.save_projection_state(repo, state)
    assert path.is_file()
    assert path.parent.name == "sw-projection-state"

    loaded = ps.load_projection_state(repo, scope)
    assert loaded["status"] == "interrupted"
    assert loaded["completedSteps"] == ["index"]
    assert loaded["pendingSteps"] == ["gap-resolve"]
    assert ps.next_pending_step(loaded) == "gap-resolve"
    assert loaded["interrupt"]["resumeCommand"]

    # Resume: finish remaining step then clear.
    ps.mark_step_complete(loaded, "gap-resolve", {"verdict": "pass"})
    assert ps.is_projection_complete(loaded)
    ps.save_projection_state(repo, loaded)
    assert ps.clear_projection_state(repo, scope) is True
    assert not ps.projection_state_path(repo, scope).is_file()


def test_prefer_worktree_projection_when_primary(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 / E: primary vs worktree detection prefers non-primary worktree."""
    alt = tmp_path / "phase-wt"
    alt.mkdir()
    # Add as linked worktree via git worktree add when possible; else emulate env preference.
    branch = "feat/projection-phase"
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(alt)],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Primary root + explicit non-primary worktree → prefer the worktree (R3).
    decision = ps.prefer_worktree_projection_root(repo, alt)
    assert decision["onPrimary"] is True  # root is primary checkout
    assert decision["preferred"] is True
    assert decision["reason"] == "explicit-non-primary-worktree"
    assert Path(decision["projectionRoot"]) == alt.resolve()

    # From primary alone, env alternate wins.
    monkeypatch.setenv("SW_ORCHESTRATOR_WORKTREE", str(alt))
    decision2 = ps.prefer_worktree_projection_root(repo, repo)
    assert decision2["onPrimary"] is True
    assert decision2["preferred"] is True
    assert Path(decision2["projectionRoot"]) == alt.resolve()


def test_reconcile_resumes_from_partial_projection_state(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4 / S: reconcile skips completed index step and finishes gap-resolve."""
    calls: list[str] = []

    scope = ps.projection_scope(prd="344", slug="resume-demo", action="reconcile")
    prior = ps.empty_projection_state(
        scope=scope,
        prd="344",
        slug="resume-demo",
        worktree=str(repo),
    )
    ps.mark_step_complete(prior, "index", {"verdict": "pass", "cached": True})
    ps.save_projection_state(repo, prior)

    def fake_index(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls.append("index")
        return {"verdict": "pass", "fresh": True}

    def fake_gap(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls.append("gap-resolve")
        return {"verdict": "pass", "gaps": []}

    monkeypatch.setattr(living, "_run_index_projection_step", fake_index)
    monkeypatch.setattr(living, "facade_gap_resolve_with_retry", fake_gap)
    monkeypatch.setattr(living, "living_doc_write_banned", lambda _root: True)
    monkeypatch.setattr(living, "target_merge_detected", lambda *_a, **_k: True)
    monkeypatch.setattr(living, "derive_index_status", lambda *_a, **_k: "complete")
    monkeypatch.setattr(living, "resolve_worktree", lambda root, _args: root)
    monkeypatch.setattr(
        living,
        "prefer_worktree_for_projection",
        lambda root, worktree: (worktree, {"onPrimary": False, "projectionRoot": str(worktree)}),
    )
    monkeypatch.setattr(
        living,
        "git_commit_living_docs",
        lambda *_a, **_k: None,
    )

    class _Dirs:
        planning = "docs/other"

    monkeypatch.setattr(living.planning_paths, "load_planning_dirs", lambda _root: _Dirs())

    emitted: dict[str, Any] = {}

    def fake_emit(payload: dict[str, Any], exit_code: int = 0) -> None:
        emitted.update(payload)
        emitted["_exit"] = exit_code

    monkeypatch.setattr(living, "emit", fake_emit)

    state = {"target": {"slug": "resume-demo"}, "terminalPr": {"number": 1}}
    plan = {"slug": "resume-demo"}
    living._cmd_reconcile_locked(repo, [], state, plan, "344")

    assert calls == ["gap-resolve"], f"index should be skipped on resume; got {calls}"
    assert emitted.get("verdict") == "pass"
    assert emitted.get("projectionResumed") is True
    assert emitted.get("index", {}).get("resumed") is True
    # Successful completion clears durable state.
    assert not ps.projection_state_path(repo, scope).is_file()


def test_projection_interrupt_surfaces_resume_command(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2/R4: rate-limit during index persists state and surfaces resumeCommand."""
    from issues_lib import IssueRateLimited

    scope = ps.projection_scope(prd="344", slug="halt-demo", action="reconcile")

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise IssueRateLimited(
            "github-issues search API rate limited",
            cumulative_wait_ms=1000,
            reason="rate-limited",
            status_code=429,
            retryable=True,
        )

    monkeypatch.setattr(living, "_run_index_projection_step", boom)
    monkeypatch.setattr(living, "target_merge_detected", lambda *_a, **_k: False)
    monkeypatch.setattr(living, "derive_index_status", lambda *_a, **_k: "in-progress")
    monkeypatch.setattr(living, "resolve_worktree", lambda root, _args: root)
    monkeypatch.setattr(
        living,
        "prefer_worktree_for_projection",
        lambda root, worktree: (worktree, {"onPrimary": True, "preferred": False}),
    )

    halted: dict[str, Any] = {}

    def fake_fail(error: str, exit_code: int = 2, **extra: Any) -> None:
        halted["error"] = error
        halted["exit_code"] = exit_code
        halted.update(extra)
        raise SystemExit(exit_code)

    monkeypatch.setattr(living, "fail", fake_fail)

    with pytest.raises(SystemExit) as excinfo:
        living._cmd_reconcile_locked(
            repo,
            [],
            {"target": {"slug": "halt-demo"}},
            {"slug": "halt-demo"},
            "344",
        )
    assert excinfo.value.code == 30
    assert halted.get("resumeCommand")
    assert "living-docs reconcile" in str(halted["resumeCommand"])
    assert halted.get("halt") == "projection-rate-limited"

    loaded = ps.load_projection_state(repo, scope)
    assert loaded["status"] == "interrupted"
    assert loaded["interrupt"]["resumeCommand"] == halted["resumeCommand"]
    assert json.loads(ps.projection_state_path(repo, scope).read_text(encoding="utf-8"))
