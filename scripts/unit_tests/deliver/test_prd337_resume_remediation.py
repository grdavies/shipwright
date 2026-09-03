"""PRD 337 R15 — resume blocker classification and redaction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from phase_status_discovery import (  # noqa: E402
    CAUSE_AMBIGUOUS_RUN,
    CAUSE_DEAD_LEASE,
    CAUSE_RESUME_NONE,
    CAUSE_TOKEN_SCOPE,
    build_resume_blocker,
    classify_resume_blocker,
    redact_resume_blocker_context,
    resume_command_for_blocker,
)

_SECRET = "ghp_" + "A" * 36


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    return tmp_path


def _write_scoped_state(tmp_path: Path, slug: str, *, verdict: str = "running") -> None:
    state = {
        "verdict": verdict,
        "source_task_list": f"docs/prds/337-{slug}/tasks-337-{slug}.md",
        "target": {"branch": f"feat/{slug}", "slug": slug},
        "phases": {"1": {"status": "pending"}},
        "nextAction": "provision-phase",
    }
    path = tmp_path / ".cursor" / f"sw-deliver-state.{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def test_resume_blockers_are_actionable_Z_no_runs(tmp_path: Path) -> None:
    """Z — zero nonterminal runs emit resume:none with listable context."""
    repo = _init_repo(tmp_path)
    blocker = classify_resume_blocker(repo)
    assert blocker["verdict"] == "fail"
    assert blocker["cause"] == CAUSE_RESUME_NONE
    assert blocker["context"]["runs"] == []
    assert "wave_deliver.py" in blocker["resumeCommand"]


def test_resume_blockers_are_actionable_O_one_run(tmp_path: Path) -> None:
    """O — single nonterminal run resolves without blocker."""
    repo = _init_repo(tmp_path)
    _write_scoped_state(repo, "solo")
    result = classify_resume_blocker(repo)
    assert result["verdict"] == "pass"
    assert result.get("cause") is None
    assert result["runId"] == "legacy-solo"
    assert result["taskList"].endswith("tasks-337-solo.md")


def test_resume_blockers_are_actionable_M_ambiguous_runs(tmp_path: Path) -> None:
    """M — multiple nonterminal runs emit ambiguous-run with enumeration."""
    repo = _init_repo(tmp_path)
    _write_scoped_state(repo, "alpha")
    _write_scoped_state(repo, "beta")
    blocker = classify_resume_blocker(repo)
    assert blocker["verdict"] == "fail"
    assert blocker["cause"] == CAUSE_AMBIGUOUS_RUN
    assert set(blocker["context"]["runs"]) == {"legacy-alpha", "legacy-beta"}
    assert "resume-locate --run-id legacy-alpha" in blocker["resumeCommand"]


def test_resume_blockers_are_actionable_B_dead_pid_lease(tmp_path: Path) -> None:
    """B — stale run lease with dead PID surfaces dead-lease blocker."""
    repo = _init_repo(tmp_path)
    from wave_lock import lock_host, run_lease_locks_dir

    locks_dir = run_lease_locks_dir(repo)
    lock_path = locks_dir / "abc123-deliver-dead.lock"
    meta = {
        "kind": "deliver-run-lease",
        "runId": "deliver-dead",
        "generation": 1,
        "owner": f"{lock_host()}:999999",
        "host": lock_host(),
        "pid": 999999,
        "acquiredAt": "2020-01-01T00:00:00Z",
        "heartbeatAt": "2020-01-01T00:00:00Z",
    }
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    blocker = classify_resume_blocker(repo)
    assert blocker["verdict"] == "fail"
    assert blocker["cause"] == CAUSE_DEAD_LEASE
    assert blocker["context"]["runId"] == "deliver-dead"
    assert "run-lease acquire" in blocker["resumeCommand"]
    assert "deliver-dead" in blocker["resumeCommand"]


def test_resume_blockers_are_actionable_I_resume_command(tmp_path: Path) -> None:
    """I — every blocker cause maps to one executable resume command."""
    repo = _init_repo(tmp_path)
    for cause in (CAUSE_RESUME_NONE, CAUSE_AMBIGUOUS_RUN, CAUSE_DEAD_LEASE, CAUSE_TOKEN_SCOPE):
        cmd = resume_command_for_blocker(
            cause,
            repo,
            run_id="run-1",
            task_list="docs/prds/337-demo/tasks.md",
            token_env="GITHUB_TOKEN",
            candidate_run_id="run-1",
        )
        assert isinstance(cmd, str) and cmd.strip()
        assert _SECRET not in cmd
        assert "ghp_" not in cmd


def test_resume_blockers_are_actionable_E_token_scope(tmp_path: Path) -> None:
    """E — ambient token-scope denial emits typed blocker without secrets."""
    repo = _init_repo(tmp_path)
    (repo / ".cursor").mkdir(parents=True, exist_ok=True)
    (repo / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"host": {"provider": "github", "tokenEnv": "GITHUB_TOKEN"}}),
        encoding="utf-8",
    )
    with patch(
        "phase_status_discovery._detect_token_scope_blocker",
        return_value={
            "surface": "host",
            "tokenEnv": "GITHUB_TOKEN",
            "detail": f"ambient token {_SECRET} refused",
        },
    ):
        blocker = classify_resume_blocker(repo)
    assert blocker["verdict"] == "fail"
    assert blocker["cause"] == CAUSE_TOKEN_SCOPE
    assert _SECRET not in json.dumps(blocker)
    assert "selector-add" in blocker["resumeCommand"]


def test_resume_blockers_are_actionable_S_lease_recovery(tmp_path: Path) -> None:
    """S — dead-lease resume command re-acquires run lease for recovery."""
    repo = _init_repo(tmp_path)
    blocker = build_resume_blocker(
        CAUSE_DEAD_LEASE,
        repo,
        context={"runId": "deliver-recover", "lockPath": "/tmp/stale.lock"},
        run_id="deliver-recover",
        task_list="docs/prds/337-demo/tasks.md",
        lock_path="/tmp/stale.lock",
    )
    assert blocker["resumeCommand"].startswith("python3 scripts/wave_lock.py")
    assert "run-lease acquire --run-id deliver-recover" in blocker["resumeCommand"]
    assert "--task-list docs/prds/337-demo/tasks.md" in blocker["resumeCommand"]


def test_redact_resume_blocker_context_scrubs_secrets() -> None:
    """Secret-bearing holder metadata is redacted from blocker context."""
    raw = {
        "holder": {"token": _SECRET, "owner": "host:1"},
        "runs": ["legacy-alpha"],
    }
    redacted = redact_resume_blocker_context(raw)
    serialized = json.dumps(redacted)
    assert _SECRET not in serialized
    assert "ghp_" not in serialized
    assert redacted["runs"] == ["legacy-alpha"]
