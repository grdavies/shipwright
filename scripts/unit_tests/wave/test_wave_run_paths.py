"""PRD 081 R18/R20 — run layout and lease fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_lock import target_lock_key_digest
from wave_run_paths import (
    RunIdRequiredError,
    mint_run_id,
    plan_path,
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
