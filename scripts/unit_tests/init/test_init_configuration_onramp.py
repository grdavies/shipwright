"""Configuration on-ramp and layout absorb closeout fixtures (PRD 324 phase 13 / R4, R10, R13)."""

from __future__ import annotations

from pathlib import Path


def test_configuration_greenfield_onramp_section(repo_root: Path) -> None:
    text = (repo_root / "docs/guides/configuration.md").read_text(encoding="utf-8")
    for token in (
        "## Greenfield on-ramp",
        "Credential checklist",
        "Named `tokenEnv`",
        "optional, never primary",
        "ci-stub plan",
        "ci-stub apply --confirm",
        "sw_bootstrap.py init_profile_report.py",
        "core/sw-reference/workflow.config.example.json",
    ):
        assert token in text


def test_layout_prd324_absorb_acceptance_map(repo_root: Path) -> None:
    for rel in ("core/sw-reference/layout.md", ".shipwright/layout.md"):
        text = (repo_root / rel).read_text(encoding="utf-8")
        assert "### PRD 324 greenfield init surfaces" in text
        assert "gap-339-redesign-greenfield-credential-setup-ux-investig" in text
        assert "gap-340-seed-consent-gated-pr-ci-stub-from-sw-init-when-" in text
        assert "gap-341-improve-sw-init-coverage-defaults-and-config-dis" in text
        assert "R1–R4" in text
        assert "R5–R8" in text
        assert "R9–R12" in text
