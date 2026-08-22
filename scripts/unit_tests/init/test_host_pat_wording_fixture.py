"""Fine-grained PAT wording doc fixture (PRD 324 phase 12 / R3, R14)."""

from __future__ import annotations

from pathlib import Path


REQUIRED_PERMISSION_MARKERS = (
    "Actions: Read",
    "Workflows: Write",
    "Contents: Read",
    "Pull requests: Read",
)

SOLE_CHECKS_FRAGMENTS = ("Checks: Read** as the sole", "Checks** as the sole")


def _read_provider_doc(repo_root: Path, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


def test_github_provider_names_current_permissions(repo_root: Path) -> None:
    text = _read_provider_doc(repo_root, "core/providers/host/github.md")
    for marker in REQUIRED_PERMISSION_MARKERS:
        assert marker in text
    assert "does not expose a standalone **Checks** permission" in text
    assert any(fragment in text for fragment in SOLE_CHECKS_FRAGMENTS)


def test_remediation_checks_matches_github_permission_naming(repo_root: Path) -> None:
    text = _read_provider_doc(repo_root, "core/providers/host/remediation-checks.md")
    for marker in REQUIRED_PERMISSION_MARKERS:
        assert marker in text
    assert "do not treat **Checks** as the sole" in text
    assert "instruction" in text
    assert "Unblocks checklist step:" in text
