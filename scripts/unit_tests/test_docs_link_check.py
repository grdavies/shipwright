"""Tests for docs link transform + dual-context validation (PRD 345 R15–R17)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from docs_link_check import run_check
from docs_link_transform import transform_markdown, transform_tree


def test_rewrite_command_link_for_install_root() -> None:
    source = "[`/sw-deliver`](../../core/commands/sw-deliver.md)"
    assert "[`/sw-deliver`](../commands/sw-deliver.md)" == transform_markdown(source)


def test_strip_contributor_only_link() -> None:
    source = "See [`INVARIANTS.md`](../../INVARIANTS.md)."
    assert "See `INVARIANTS.md`." == transform_markdown(source)


def test_transform_tree_rewrites_dist_documentation(tmp_path: Path) -> None:
    docs = tmp_path / "documentation"
    docs.mkdir()
    sample = docs / "commands.md"
    sample.write_text("[cmd](../../core/commands/sw-ship.md)\n", encoding="utf-8")
    stats = transform_tree(docs)
    assert stats["changed"] == 1
    assert "[cmd](../commands/sw-ship.md)" in sample.read_text(encoding="utf-8")


def test_source_context_passes_on_repo_root(repo_root: Path) -> None:
    result = run_check(root=repo_root, include_prds=False, context="source")
    assert result["verdict"] == "pass"
    assert result["context"] == "source"


def test_install_root_context_after_transform(repo_root: Path) -> None:
    cursor_root = repo_root / "dist" / "cursor"
    if not (cursor_root / "documentation").is_dir():
        pytest.skip("dist/cursor documentation not present")

    transform_tree(cursor_root / "documentation")
    result = run_check(root=cursor_root, include_prds=False, context="install-root")
    assert result["verdict"] == "pass"
    assert result["context"] == "install-root"


def test_cli_dual_context_strict(repo_root: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "docs-link-check.py"), "--strict"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert payload["context"] == "source"
