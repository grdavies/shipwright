"""PRD 069 R5 — docs/prds absent from publish surface; materialize fail-closed."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.git]

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_store as ps


def git_tracked_paths(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def docs_prds_tracked(tracked: list[str]) -> list[str]:
    return sorted(p for p in tracked if p == "docs/prds" or p.startswith("docs/prds/"))


def test_docs_prds_absent_from_git_index(repo_root: Path) -> None:
    """Public tree must not publish docs/prds; bodies materialize at deliver entry."""
    tracked = docs_prds_tracked(git_tracked_paths(repo_root))
    assert tracked == [], f"docs/prds must not be tracked: {tracked}"


def test_docs_prds_absent_detects_fixture_leak() -> None:
    tracked = [
        "README.md",
        "docs/prds/069-test/tasks-069-test.md",
        "docs/guides/commands.md",
    ]
    leaks = docs_prds_tracked(tracked)
    assert leaks == ["docs/prds/069-test/tasks-069-test.md"]
    assert "README.md" not in leaks


def test_materialize_missing_frozen_body_typed(tmp_path: Path) -> None:
    backend = ps.InRepoPublicBackend(tmp_path, {})
    dest = tmp_path / ".cursor/planning-materialized/docs/prds/x/tasks-x.md"
    result = backend.materialize("tasks-x", "docs/prds/x/tasks-x.md", dest)
    assert result.verdict == "missing"
    assert result.reason == ps.MATERIALIZE_MISSING_FROZEN_BODY
    assert not dest.exists()


def test_materialize_empty_body_typed_fail(tmp_path: Path) -> None:
    body_rel = "docs/prds/x/tasks-x.md"
    body_path = tmp_path / body_rel
    body_path.parent.mkdir(parents=True)
    body_path.write_text("   \n", encoding="utf-8")
    backend = ps.InRepoPublicBackend(tmp_path, {})
    dest = tmp_path / ".cursor/planning-materialized" / body_rel
    result = backend.materialize("tasks-x", body_rel, dest)
    assert result.verdict == "missing"
    assert result.reason == ps.MATERIALIZE_MISSING_FROZEN_BODY
    assert not dest.exists()
