"""PRD 081 R18 — run-scoped plan persistence and hash verification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wave_run_paths import plan_path
from wave_run_plan import (
    PlanCommitShaMismatchError,
    PlanHashMismatchError,
    ensure_run_id,
    load_verified_plan,
    persist_plan,
    verify_plan_hash,
)


def _sample_plan() -> dict:
    return {
        "mode": "phase",
        "target": {"branch": "feat/demo", "slug": "demo"},
        "items": [{"id": "1", "slug": "alpha"}],
        "waves": [["1"]],
        "edges": [],
    }


def _init_git(path: Path) -> str:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def test_second_run_does_not_mutate_first_plan(tmp_path: Path) -> None:
    _init_git(tmp_path)
    state_a: dict = {}
    state_b: dict = {}
    run_a = ensure_run_id(tmp_path, state_a)
    persist_plan(tmp_path, run_a, _sample_plan(), state_a)

    run_b = ensure_run_id(tmp_path, state_b)
    other = {**_sample_plan(), "target": {"branch": "feat/other", "slug": "other"}}
    persist_plan(tmp_path, run_b, other, state_b)

    loaded_a = load_verified_plan(tmp_path, run_a, state_a)
    assert loaded_a["target"]["branch"] == "feat/demo"
    loaded_b = load_verified_plan(tmp_path, run_b, state_b)
    assert loaded_b["target"]["branch"] == "feat/other"


def test_tampered_plan_rejected(tmp_path: Path) -> None:
    _init_git(tmp_path)
    state: dict = {}
    run_id = ensure_run_id(tmp_path, state)
    persist_plan(tmp_path, run_id, _sample_plan(), state)
    tampered = {**_sample_plan(), "tampered": True}
    plan_path(tmp_path, run_id).write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(PlanHashMismatchError):
        verify_plan_hash(tmp_path, run_id, state)


def test_stale_commit_sha_rejected(tmp_path: Path) -> None:
    head = _init_git(tmp_path)
    state: dict = {}
    run_id = ensure_run_id(tmp_path, state)
    persist_plan(tmp_path, run_id, _sample_plan(), state)
    assert state.get("planCommitSha") == head
    with pytest.raises(PlanCommitShaMismatchError):
        load_verified_plan(tmp_path, run_id, state, expected_head="b" * 40)
