"""PRD 274 R16 + D1–D3 — documentation surface for sync/build hygiene."""

from __future__ import annotations

from pathlib import Path


def test_docs_closeout_and_ship_gate_updated(repo_root: Path) -> None:
    """R16 — CONTRIBUTING and layout document closeout + dist/ship gates."""
    contributing = (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "dist_freshness" in contributing
    assert "python3 -m sw generate --all" in contributing
    assert ".sw/deliver-closeout" in contributing
    assert "dist_freshness_ship" in contributing

    layout = (repo_root / ".shipwright/layout.md").read_text(encoding="utf-8")
    assert "deliver-closeout" in layout
    assert "gitignored" in layout.lower()


def test_decision_cluster_sync_build_hygiene(repo_root: Path) -> None:
    """D1 — ship command acknowledges clustered sync+build hygiene."""
    ship_cmd = (repo_root / "core/commands/sw-ship.md").read_text(encoding="utf-8")
    assert "D1" in ship_cmd
    assert "274" in ship_cmd
    assert "hygiene" in ship_cmd.lower()


def test_decision_prefer_mechanical_fixes(repo_root: Path) -> None:
    """D2 — ship command prefers mechanical fixes over docs-only workarounds."""
    ship_cmd = (repo_root / "core/commands/sw-ship.md").read_text(encoding="utf-8")
    assert "D2" in ship_cmd
    assert "mechanical" in ship_cmd.lower()


def test_decision_fail_closed_auto_stage_when_safe(repo_root: Path) -> None:
    """D3 — ship skill documents fail-closed regen + bounded auto-stage."""
    skill = (repo_root / "core/skills/ship/SKILL.md").read_text(encoding="utf-8")
    assert "dist_freshness_ship" in skill
    assert "fail closed" in skill.lower()
    assert "python3 -m sw generate --all" in skill
    assert "D3" in skill
