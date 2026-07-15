"""Publish-surface denylist — learnings/decision bodies must not ship (PRD 069 R4)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.git]

DECISION_INDEX_ALLOW = frozenset(
    {
        "docs/decisions/INDEX.md",
        "docs/decisions/SUPERSEDED.log",
    }
)


def git_tracked_paths(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def leaked_publish_paths(tracked: list[str]) -> list[str]:
    leaks: list[str] = []
    for path in tracked:
        if path.startswith("docs/learnings/"):
            leaks.append(path)
        elif path.startswith("docs/decisions/") and path not in DECISION_INDEX_ALLOW:
            leaks.append(path)
        elif path == ".cursor/sw-base-state.json":
            leaks.append(path)
        elif path.startswith(".cursor/tmp-") and path.endswith(".sh"):
            leaks.append(path)
        elif path.startswith(".cursor/hooks/state/") or "/.cursor/hooks/state/" in path:
            leaks.append(path)
    return sorted(leaks)


def test_publish_surface_denylist_no_leaked_paths(repo_root: Path) -> None:
    """Tracked index must not contain learnings, decision bodies, or .cursor runtime files."""
    leaks = leaked_publish_paths(git_tracked_paths(repo_root))
    assert leaks == [], f"publish-surface leaks in git index: {leaks}"


def test_publish_surface_denylist_detects_fixture_leak(tmp_git_repo: Path) -> None:
    """Denylist helper flags synthetic leaks for regression coverage."""
    tracked = [
        "README.md",
        "docs/learnings/sample-retro.md",
        "docs/decisions/001-sample-decision.md",
        ".cursor/sw-base-state.json",
        ".cursor/tmp-phase-ship.sh",
        "docs/decisions/INDEX.md",
    ]
    leaks = leaked_publish_paths(tracked)
    assert "docs/learnings/sample-retro.md" in leaks
    assert "docs/decisions/001-sample-decision.md" in leaks
    assert ".cursor/sw-base-state.json" in leaks
    assert ".cursor/tmp-phase-ship.sh" in leaks
    assert "docs/decisions/INDEX.md" not in leaks
    assert "README.md" not in leaks
