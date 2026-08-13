"""Pytest port of run_cleanup_fixtures.py (PRD 054 W4 behavioral)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/w4"
_HARNESS = "harness_cleanup.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_cleanup", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

@pytest.mark.git
def test_cleanup_tmp_git_repo_ready(tmp_git_repo: Path) -> None:
    assert (tmp_git_repo / ".git").is_dir()


@pytest.mark.git
def test_cleanup_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_cleanup_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()


# --- PRD 094 R10/R11/R15 string-or-object cleanup targets ---
import json
import subprocess
import cleanup_lib
from wave_state import enumerate_scoped_runs, target_branch_from_state

def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_scoped_state(
    root: Path,
    slug: str,
    *,
    verdict: str,
    target: object,
) -> Path:
    path = root / ".cursor" / f"sw-deliver-state.{slug}.json"
    _write_json(path, {"verdict": verdict, "updatedAt": "2026-08-12T00:00:00Z", "target": target})
    return path


def test_cleanup_string_target_no_attributeerror(tmp_git_repo: Path) -> None:
    """R10 — string target shape does not break scoped-run enumeration or cleanup."""
    subprocess.run(
        ["git", "checkout", "-b", "feat/string-target"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    _write_scoped_state(
        tmp_git_repo,
        "string-target",
        verdict="complete",
        target="feat/string-target",
    )
    runs = enumerate_scoped_runs(tmp_git_repo)
    assert runs
    assert runs[0]["target"] == "feat/string-target"
    report = cleanup_lib.enumerate_cleanup(tmp_git_repo)
    assert report.errors == []


def test_cleanup_uses_target_branch_helper(tmp_git_repo: Path) -> None:
    """R11 — target reads route through target_branch_from_state."""
    state = {"target": "feat/helper", "verdict": "running"}
    assert target_branch_from_state(state) == "feat/helper"
    state_obj = {"target": {"branch": "feat/helper-obj"}, "verdict": "running"}
    assert target_branch_from_state(state_obj) == "feat/helper-obj"


def test_cleanup_breadcrumb_inflight_protect(tmp_git_repo: Path) -> None:
    """R12/R15 — live run on B blocks when legacy breadcrumb points at stale A."""
    subprocess.run(
        ["git", "checkout", "-b", "feat/live-b"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    stale_a = tmp_git_repo / ".cursor" / "sw-deliver-state.stale-a.json"
    _write_json(
        stale_a,
        {
            "verdict": "complete",
            "updatedAt": "2026-01-01T00:00:00Z",
            "target": {"branch": "feat/stale-a"},
        },
    )
    _write_json(
        tmp_git_repo / ".cursor" / "sw-deliver-state.json",
        {
            "migrated": True,
            "migratedAt": "2026-08-12T00:00:00Z",
            "scopedPath": str(stale_a.relative_to(tmp_git_repo)),
            "target": "feat/stale-a",
        },
    )
    _write_scoped_state(
        tmp_git_repo,
        "live-b",
        verdict="running",
        target="feat/live-b",
    )

    inflight, reason = cleanup_lib.deliver_inflight(tmp_git_repo)
    assert inflight is True
    assert "running" in reason

    report = cleanup_lib.enumerate_cleanup(tmp_git_repo)
    protected = [item for item in report.protected if item.kind == "run-state"]
    assert any("live-b" in item.name for item in protected)


def test_breadcrumb_scoped_file_fail_closed(tmp_git_repo: Path) -> None:
    """R11/R15 — breadcrumb scoped state file is protected when unresolvable."""
    subprocess.run(
        ["git", "checkout", "-b", "feat/breadcrumb-only"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    _write_json(
        tmp_git_repo / ".cursor" / "sw-deliver-state.breadcrumb-only.json",
        {
            "migrated": True,
            "migratedAt": "2026-08-12T00:00:00Z",
            "target": "feat/missing-target",
        },
    )
    inflight, reason = cleanup_lib.deliver_inflight(tmp_git_repo)
    assert inflight is True
    assert "breadcrumb" in reason
