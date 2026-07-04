"""Shared pytest fixtures for Shipwright unit tests (PRD 054 R15)."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from _sw.vendor_paths import bootstrap_vendor_paths, repo_root as sw_repo_root

# Harness suites mutate shared orchestrator .cursor artifacts; restore after each test.


def _snapshot_cursor_tree(cursor_dir: Path) -> dict[str, bytes]:
    snap: dict[str, bytes] = {}
    if not cursor_dir.is_dir():
        return snap
    for path in cursor_dir.rglob("*"):
        if path.is_file():
            snap[path.relative_to(cursor_dir).as_posix()] = path.read_bytes()
    return snap


def _restore_cursor_tree(cursor_dir: Path, snap: dict[str, bytes]) -> None:
    if cursor_dir.is_dir():
        for path in cursor_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(cursor_dir).as_posix()
            if rel not in snap:
                path.unlink(missing_ok=True)
        for path in sorted(cursor_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
    for rel, data in snap.items():
        dest = cursor_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        os.chmod(dest, 0o600)


def _copy_dist_platform(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    if src.is_dir():
        shutil.copytree(src, dest)


def _restore_dist_platforms(repo_root: Path, snap_root: Path) -> None:
    dist = repo_root / "dist"
    for name in ("cursor", "claude-code"):
        _copy_dist_platform(snap_root / name, dist / name)


@pytest.fixture(scope="session")
def _dist_session_snapshot(repo_root: Path) -> Generator[Path, None, None]:
    """Baseline dist/ captured once; emitter harnesses regenerate in-repo during tests."""
    import tempfile

    snap_root = Path(tempfile.mkdtemp(prefix="sw-dist-snap-"))
    for name in ("cursor", "claude-code"):
        src = repo_root / "dist" / name
        if src.is_dir():
            shutil.copytree(src, snap_root / name)
    yield snap_root
    shutil.rmtree(snap_root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _guard_cursor_worktree_artifacts(repo_root: Path) -> Generator[None, None, None]:
    """Prevent cross-test pollution when embedded harnesses write under .cursor/."""
    cursor = repo_root / ".cursor"
    snap = _snapshot_cursor_tree(cursor)
    yield
    _restore_cursor_tree(cursor, snap)


@pytest.fixture(autouse=True)
def _restore_dist_after_test(
    repo_root: Path, _dist_session_snapshot: Path
) -> Generator[None, None, None]:
    yield
    _restore_dist_platforms(repo_root, _dist_session_snapshot)


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_vendored_deps() -> None:
    bootstrap_vendor_paths()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Repository root resolved via git or layout fallback."""
    return sw_repo_root()


def _hermetic_test_env(env: dict[str, str]) -> dict[str, str]:
    """Drop deliver phase-mode and broken interpreter hints from inherited agent env."""
    cleaned = dict(env)
    for key in list(cleaned):
        if key.startswith("SW_PHASE") or key in (
            "SW_RUN_DIR",
            "SW_REPO_ROOT",
            "SW_INTEGRATION_BRANCH",
            "PYTHONHOME",
        ):
            cleaned.pop(key, None)
    return cleaned


@pytest.fixture
def sw_env(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Environment with PYTHONPATH and repo roots for subprocess helpers."""
    base = os.environ.copy()
    strip_keys = [
        key
        for key in base
        if key.startswith("SW_PHASE")
        or key
        in (
            "SW_RUN_DIR",
            "SW_REPO_ROOT",
            "SW_INTEGRATION_BRANCH",
            "PYTHONHOME",
        )
    ]
    for key in strip_keys:
        monkeypatch.delenv(key, raising=False)
    env = _hermetic_test_env(base)
    scripts = str(repo_root / "scripts")
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in (scripts, existing) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["SW_REPO_ROOT"] = str(repo_root)
    env["ROOT"] = str(repo_root)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Ephemeral git repository for W1+ porting of legacy git fixture patterns."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "sw-test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Shipwright Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    yield repo
    shutil.rmtree(repo, ignore_errors=True)
