"""PRD 090 R2 — git-ref remote lease primitive and cross-clone race tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_remote_lease import (
    acquire_remote_lease,
    canonical_remote_url,
    probe_ref_update_capability,
    release_remote_lease,
    remote_lease_key_digest,
    remote_lease_ref,
)
from wave_target_lock import acquire_doc_to_feature_handoff_lock, acquire_target_lock


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, bare: bool = False) -> None:
    if bare:
        subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True, text=True)
        return
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "seed")


def _clone(bare: Path, dest: Path) -> None:
    subprocess.run(["git", "clone", str(bare), str(dest)], check=True, capture_output=True, text=True)
    _git(dest, "config", "user.email", "test@example.com")
    _git(dest, "config", "user.name", "Test")


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _init_repo(remote, bare=True)
    return remote


def test_canonical_remote_url_normalizes_ssh_and_https() -> None:
    ssh = "git@github.com:acme/demo.git"
    https = "https://github.com/acme/demo.git"
    assert canonical_remote_url(ssh) == canonical_remote_url(https)


def test_remote_lease_key_digest_stable() -> None:
    url = "https://github.com/acme/demo.git"
    assert remote_lease_key_digest(url, "feat/a") == remote_lease_key_digest(url, "feat/a")
    assert remote_lease_ref(remote_lease_key_digest(url, "feat/a")).startswith("refs/sw-locks/")


def test_two_clone_race_exactly_one_wins(bare_remote: Path, tmp_path: Path) -> None:
    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"
    _clone(bare_remote, clone_a)
    _clone(bare_remote, clone_b)
    target = "feat/race"
    os.environ["SW_REMOTE_LEASE_FORCE_REMOTE"] = "1"

    first = acquire_remote_lease(clone_a, target, "run-a")
    second = acquire_remote_lease(clone_b, target, "run-b")
    assert first["verdict"] == "pass"
    assert first.get("mode") == "remote"
    assert second["verdict"] == "fail"
    assert second.get("error") == "remote-lease-conflict"

    release_remote_lease(clone_a, target, "run-a")
    third = acquire_remote_lease(clone_b, target, "run-b")
    assert third["verdict"] == "pass"
    release_remote_lease(clone_b, target, "run-b")


def test_target_lock_wires_remote_lease_race(bare_remote: Path, tmp_path: Path) -> None:
    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"
    _clone(bare_remote, clone_a)
    _clone(bare_remote, clone_b)
    target = "feat/target-lock"
    os.environ["SW_REMOTE_LEASE_FORCE_REMOTE"] = "1"

    with patch("wave_lock._canonical_repo_root_for_locks", side_effect=lambda p: p):
        ok = acquire_target_lock(clone_a, target, "deliver-a")
        blocked = acquire_target_lock(clone_b, target, "deliver-b")
    assert ok["verdict"] == "pass"
    assert blocked["verdict"] == "fail"
    assert blocked.get("error") in ("target-lock-held", "remote-lease-conflict")


def test_handoff_lock_wires_remote_lease_race(bare_remote: Path, tmp_path: Path) -> None:
    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"
    _clone(bare_remote, clone_a)
    _clone(bare_remote, clone_b)
    target = "feat/handoff"
    os.environ["SW_REMOTE_LEASE_FORCE_REMOTE"] = "1"

    with patch("wave_lock._canonical_repo_root_for_locks", side_effect=lambda p: p):
        ok = acquire_doc_to_feature_handoff_lock(clone_a, target, "doc-loop:run-a")
        blocked = acquire_doc_to_feature_handoff_lock(clone_b, target, "doc-loop:run-b")
    assert ok["verdict"] == "pass"
    assert blocked["verdict"] == "fail"
    assert blocked.get("error") in ("doc-to-feature-handoff-lock-held", "remote-lease-conflict")


def test_missing_permission_falls_back_local_only(tmp_path: Path, bare_remote: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(bare_remote.resolve()))
    os.environ["SW_REMOTE_LEASE_FORCE_LOCAL"] = "1"
    out = acquire_remote_lease(repo, "feat/local", "run-local")
    assert out["verdict"] == "pass"
    assert out.get("mode") == "local-only"
    assert out.get("warning") == "ref-update-unavailable"
    assert probe_ref_update_capability(repo) is False
