"""Resume cardinality fixtures (PRD 081 R21)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver import list_deliver_runs, resolve_resume_cardinality


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def _write_scoped_state(tmp_path: Path, slug: str, verdict: str = "running") -> Path:
    state = {
        "verdict": verdict,
        "source_task_list": f"docs/prds/081-{slug}/tasks-081-{slug}.md",
        "target": {"branch": f"feat/{slug}", "slug": slug},
        "phases": {"1": {"status": "pending"}},
        "nextAction": "provision-phase",
    }
    path = tmp_path / ".cursor" / f"sw-deliver-state.{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return path


def test_zero_nonterminal_runs_fail_with_enumeration(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    with pytest.raises(SystemExit):
        resolve_resume_cardinality(tmp_path, [])
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_deliver.py"), str(tmp_path), "resume-locate"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout or proc.stderr)
    assert payload.get("halt") == "resume:none"
    assert "runs" in payload


def test_single_nonterminal_run_succeeds_without_run_id(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_scoped_state(tmp_path, "alpha")
    resolved = resolve_resume_cardinality(tmp_path, [])
    assert resolved["runId"] == "legacy-alpha"
    assert resolved["taskList"].endswith("tasks-081-alpha.md")


def test_multiple_nonterminal_runs_fail_with_enumeration(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_scoped_state(tmp_path, "alpha")
    _write_scoped_state(tmp_path, "beta")
    with pytest.raises(SystemExit):
        resolve_resume_cardinality(tmp_path, [])
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_deliver.py"), str(tmp_path), "resume-locate"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout or proc.stderr)
    assert payload.get("halt") == "resume:ambiguous"
    assert len(payload.get("runs") or []) == 2


def test_explicit_run_id_resolves_one_of_many(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_scoped_state(tmp_path, "alpha")
    _write_scoped_state(tmp_path, "beta")
    resolved = resolve_resume_cardinality(tmp_path, ["--run-id", "legacy-beta"])
    assert resolved["runId"] == "legacy-beta"


def test_list_marks_legacy_runs_requiring_adoption(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_scoped_state(tmp_path, "alpha")
    runs = list_deliver_runs(tmp_path)
    assert len(runs) == 1
    entry = runs[0]
    assert entry["requiresAdoption"] is True
    assert entry["targetBranch"] == "feat/alpha"
    assert entry["stage"] == "provision-phase"
    assert entry["unit"] == "tasks-081-alpha"
