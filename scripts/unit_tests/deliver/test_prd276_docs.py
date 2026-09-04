"""PRD 276 R17/R19 + D1–D5 — documentation surfaces for deliver driver resilience."""

from __future__ import annotations

from pathlib import Path


def test_absorb_map_698_704_705_documented(repo_root: Path) -> None:
    """R17 — sw-deliver documents absorb map for #698/#704/#705."""
    deliver = (repo_root / "core/commands/sw-deliver.md").read_text(encoding="utf-8")
    assert "Absorb map" in deliver
    assert "#698" in deliver
    assert "#704" in deliver
    assert "#705" in deliver
    assert "276" in deliver


def test_docs_deliver_lease_adopt_finalize_updated(repo_root: Path) -> None:
    """R19 — deliver + layout cover adopt, lease halt/reclaim, and primary finalize."""
    deliver = (repo_root / "core/commands/sw-deliver.md").read_text(encoding="utf-8")
    assert "auto-adopt" in deliver.lower() or "auto-adopts" in deliver.lower()
    assert "lease-held" in deliver.lower() or "Lease held" in deliver
    assert "stale" in deliver.lower() and "reclaim" in deliver.lower()
    assert "finalize" in deliver.lower()
    assert "squash" in deliver.lower()

    layout = (repo_root / ".shipwright/layout.md").read_text(encoding="utf-8")
    assert "sw-deliver-run-locks" in layout
    assert "Exclusive runId lease taxonomy" in layout or "runId lease" in layout


def test_decision_cluster_driver_resilience(repo_root: Path) -> None:
    """D1 — conductor skill acknowledges clustered finalize+cwd+lease."""
    skill = (repo_root / "core/skills/conductor/SKILL.md").read_text(encoding="utf-8")
    assert "D1" in skill
    assert "276" in skill
    assert "finalize" in skill.lower()
    assert "lease" in skill.lower()


def test_decision_prefer_auto_adopt(repo_root: Path) -> None:
    """D2 — conductor skill prefers auto-adopt over message-only halt."""
    skill = (repo_root / "core/skills/conductor/SKILL.md").read_text(encoding="utf-8")
    assert "D2" in skill
    assert "auto-adopt" in skill.lower()


def test_decision_durable_lease(repo_root: Path) -> None:
    """D3 — conductor rule prefers durable lease over heartbeat-only."""
    rule = (repo_root / "core/rules/sw-conductor.mdc").read_text(encoding="utf-8")
    assert "D3" in rule
    assert "durable" in rule.lower()
    assert "lease" in rule.lower()
    assert "heartbeat" in rule.lower()


def test_decision_generation_fencing(repo_root: Path) -> None:
    """D4 — workflows guide documents generation fencing."""
    workflows = (repo_root / "docs/guides/workflows.md").read_text(encoding="utf-8")
    assert "D4" in workflows
    assert "generation" in workflows.lower()
    assert "fencing" in workflows.lower()


def test_decision_local_common_dir_scope(repo_root: Path) -> None:
    """D5 — workflows guide documents local common-dir lease scope."""
    workflows = (repo_root / "docs/guides/workflows.md").read_text(encoding="utf-8")
    assert "D5" in workflows
    assert "common-dir" in workflows.lower() or "common dir" in workflows.lower()
