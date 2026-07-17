"""PRD 072 R4 — version.txt follows release-please manifest (KD8)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest


def _write_manifest(worktree: Path, version: str) -> None:
    (worktree / ".release-please-manifest.json").write_text(
        json.dumps({".": version}) + "\n",
        encoding="utf-8",
    )


def _bootstrap_bookkeeping_repo(repo: Path) -> None:
    changelog = """# Changelog

## [Unreleased]

## [1.2.2] - 2025-01-01
"""
    (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (repo / "version.txt").write_text("1.2.2\n", encoding="utf-8")
    _write_manifest(repo, "1.2.2")
    (repo / ".cursor").mkdir(parents=True, exist_ok=True)
    state = {
        "target": {"branch": "feat/demo"},
        "mergedPhases": [],
        "orchestratorWorktree": {"path": str(repo)},
    }
    (repo / ".cursor/sw-deliver-state.json").write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init bookkeeping fixture"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_maybe_sync_unchanged_manifest_leaves_version_txt(tmp_path: Path) -> None:
    from wave_bookkeeping import maybe_sync_version_txt

    version_path = tmp_path / "version.txt"
    version_path.write_text("1.2.2\n", encoding="utf-8")
    _write_manifest(tmp_path, "1.2.2")

    result = maybe_sync_version_txt(
        tmp_path,
        version_path,
        manifest_version_before="1.2.2",
    )

    assert result["versionTxtTouched"] is False
    assert result["reason"] == "manifest-unchanged"
    assert version_path.read_text(encoding="utf-8") == "1.2.2\n"


def test_maybe_sync_changed_manifest_aligns_version_txt(tmp_path: Path) -> None:
    from wave_bookkeeping import maybe_sync_version_txt

    version_path = tmp_path / "version.txt"
    version_path.write_text("1.2.2\n", encoding="utf-8")
    _write_manifest(tmp_path, "1.3.0")

    result = maybe_sync_version_txt(
        tmp_path,
        version_path,
        manifest_version_before="1.2.2",
    )

    assert result["versionTxtTouched"] is True
    assert result["manifestVersion"] == "1.3.0"
    assert version_path.read_text(encoding="utf-8") == "1.3.0\n"


def test_record_unchanged_manifest_does_not_bump_version_txt(
    tmp_git_repo: Path,
    repo_root: Path,
    sw_env: dict[str, str],
) -> None:
    _bootstrap_bookkeeping_repo(tmp_git_repo)
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/wave_bookkeeping.py"),
            str(tmp_git_repo),
            "record",
            "--phase-slug",
            "alpha",
            "--message",
            "phase alpha",
            "--type",
            "feat",
            "--worktree",
            str(tmp_git_repo),
        ],
        cwd=tmp_git_repo,
        env=sw_env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["projectedVersion"] == "1.3.0"
    assert payload["versionSync"]["versionTxtTouched"] is False
    assert tmp_git_repo.joinpath("version.txt").read_text(encoding="utf-8") == "1.2.2\n"


def test_revert_unchanged_manifest_leaves_version_txt(
    tmp_git_repo: Path,
    repo_root: Path,
    sw_env: dict[str, str],
) -> None:
    _bootstrap_bookkeeping_repo(tmp_git_repo)
    record = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/wave_bookkeeping.py"),
            str(tmp_git_repo),
            "record",
            "--phase-slug",
            "alpha",
            "--message",
            "phase alpha",
            "--type",
            "feat",
            "--worktree",
            str(tmp_git_repo),
        ],
        cwd=tmp_git_repo,
        env=sw_env,
        text=True,
        capture_output=True,
    )
    assert record.returncode == 0, record.stderr

    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/wave_bookkeeping.py"),
            str(tmp_git_repo),
            "revert",
            "--phase-slug",
            "alpha",
            "--worktree",
            str(tmp_git_repo),
        ],
        cwd=tmp_git_repo,
        env=sw_env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["versionSync"]["versionTxtTouched"] is False
    assert tmp_git_repo.joinpath("version.txt").read_text(encoding="utf-8") == "1.2.2\n"
