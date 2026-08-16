"""PRD 081 R18/R20 — run layout and lease fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_lock import target_lock_key_digest
from wave_run_paths import (
    PhaseIdRequiredError,
    RunIdRequiredError,
    mint_run_id,
    phase_directory,
    plan_path,
    require_phase_id,
    require_run_id,
    runs_index_path,
    state_path,
)
from wave_state import (
    discovery_entry_for_run,
    enumerate_run_scoped_dirs,
    load_run_scoped_state,
    read_run_local_lease,
    save_run_scoped_state,
    upsert_run_index_discovery,
    write_run_local_lease,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape",
        "foo/bar",
        "..",
        ".",
        "phase id",
        "phase\nid",
        "",
        "   ",
    ],
)
def test_require_phase_id_rejects_path_unsafe_values(repo: Path, unsafe: str) -> None:
    with pytest.raises(PhaseIdRequiredError):
        require_phase_id(unsafe)
    run_id = mint_run_id(repo)
    with pytest.raises(PhaseIdRequiredError):
        phase_directory(repo, run_id, unsafe)


@pytest.mark.parametrize("safe", ["1", "3", "7", "12", "phase-3"])
def test_require_phase_id_accepts_numeric_and_opaque_ids(repo: Path, safe: str) -> None:
    assert require_phase_id(safe) == safe
    run_id = mint_run_id(repo)
    path = phase_directory(repo, run_id, safe)
    assert path.name == safe


def test_missing_run_id_raises_instead_of_defaulting(repo: Path) -> None:
    with pytest.raises(RunIdRequiredError):
        require_run_id(None)
    with pytest.raises(RunIdRequiredError):
        require_run_id("")
    with pytest.raises(RunIdRequiredError):
        plan_path(repo, None)
    with pytest.raises(RunIdRequiredError):
        state_path(repo, "  ")


def test_repeated_minting_never_collides(repo: Path) -> None:
    ids = {mint_run_id(repo) for _ in range(32)}
    assert len(ids) == 32


def test_lease_resolves_back_to_lock_digest(repo: Path) -> None:
    run_id = mint_run_id(repo)
    target = "feat/workflow-state-machine-hardening"
    expected = target_lock_key_digest(repo, target)
    write_run_local_lease(repo, run_id, target)
    lease = read_run_local_lease(repo, run_id)
    assert lease["lockKeyDigest"] == expected
    assert lease["runId"] == run_id
    assert lease["targetBranch"] == target


def test_root_index_holds_no_run_payload(repo: Path) -> None:
    run_id = mint_run_id(repo)
    state = {
        "verdict": "running",
        "target": {"branch": "feat/demo"},
        "source_task_list": "docs/prds/081/tasks.md",
        "phases": {"1": {"status": "pending"}},
        "taskLedger": {"tasks": {"2.1": {"done": True}}},
    }
    save_run_scoped_state(repo, run_id, state)
    write_run_local_lease(repo, run_id, "feat/demo")
    upsert_run_index_discovery(repo, run_id, state)
    index = json.loads(runs_index_path(repo).read_text(encoding="utf-8"))
    assert index["runs"]
    entry = next(item for item in index["runs"] if item.get("runId") == run_id)
    assert "phases" not in entry
    assert "taskLedger" not in entry
    assert entry["statePath"].endswith(f"{run_id}/state.json")
    assert entry["lockKeyDigest"] == target_lock_key_digest(repo, "feat/demo")


def test_run_scoped_state_round_trip(repo: Path) -> None:
    run_id = mint_run_id(repo)
    payload = {"verdict": "running", "target": {"branch": "feat/demo"}}
    save_run_scoped_state(repo, run_id, payload)
    loaded = load_run_scoped_state(repo, run_id)
    assert loaded["runId"] == run_id
    assert loaded["verdict"] == "running"


def test_discovery_entry_is_sanitized(repo: Path) -> None:
    run_id = mint_run_id(repo)
    entry = discovery_entry_for_run(
        repo,
        run_id,
        {"verdict": "running", "phases": {"1": {}}, "mergeJournal": {"open": True}},
    )
    assert "phases" not in entry
    assert "mergeJournal" not in entry


def test_enumerate_run_scoped_dirs_skips_invalid_run_ids(repo: Path) -> None:
    """Bookkeeping dirs under sw-deliver-runs must not crash enumeration."""
    from wave_run_paths import runs_root

    run_id = mint_run_id(repo)
    save_run_scoped_state(
        repo,
        run_id,
        {"verdict": "running", "target": {"branch": "feat/demo"}},
    )
    base = runs_root(repo)
    for reserved in ("_archived", "_progress-projections", "_foo"):
        (base / reserved).mkdir(parents=True, exist_ok=True)
        (base / reserved / "state.json").write_text("{}", encoding="utf-8")

    entries = enumerate_run_scoped_dirs(repo)
    ids = {str(e.get("runId") or "") for e in entries}
    assert run_id in ids
    assert "_archived" not in ids
    assert "_progress-projections" not in ids
    assert "_foo" not in ids
    assert all(not rid.startswith("_") for rid in ids if rid)
