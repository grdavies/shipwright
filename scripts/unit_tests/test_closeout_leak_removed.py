"""PRD 274 R3 — leaked core/sw-reference/deliver-closeout trees must be absent."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_gitignore_covers_closeout_paths(repo_root: Path) -> None:
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert ".sw/deliver-closeout/" in text
    assert "core/sw-reference/deliver-closeout/" in text


def test_leaked_closeout_trees_removed(repo_root: Path) -> None:
    proc = subprocess.run(
        ["git", "ls-files", "core/sw-reference/deliver-closeout"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    tracked = [line for line in proc.stdout.splitlines() if line.strip()]
    assert tracked == [], f"tracked closeout leak must be removed: {tracked}"

    leaked = repo_root / "core" / "sw-reference" / "deliver-closeout"
    if leaked.exists():
        remaining = list(leaked.rglob("*"))
        assert remaining == [], f"on-disk closeout leak must be removed: {remaining}"
