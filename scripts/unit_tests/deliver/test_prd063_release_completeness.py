"""PRD 063 R17 — doc surface completeness for deliver autonomy."""

from __future__ import annotations

from pathlib import Path

import pytest

DOC_SURFACES: tuple[tuple[str, str], ...] = (
    ("core/commands/sw-deliver.md", "Testing / Rollout (PRD 063 R17)"),
    ("core/commands/sw-deliver.md", "Re-adopt gate (R6)"),
    ("core/commands/sw-deliver.md", "shipChain"),
    ("docs/guides/workflows.md", "Deliver autonomy"),
    ("docs/guides/commands.md", "Deliver autonomy"),
    (".sw/layout.md", "harness-roots-manifest.json"),
    (".sw/layout.md", "dispatch lease"),
    ("core/skills/conductor/SKILL.md", "DELIVER_WAKE_"),
)


@pytest.mark.parametrize("rel,needle", DOC_SURFACES)
def test_doc_surfaces_document_prd063(repo_root: Path, rel: str, needle: str) -> None:
    path = repo_root / rel
    assert path.is_file(), f"missing doc surface: {rel}"
    assert needle in path.read_text(encoding="utf-8"), f"{rel} missing: {needle}"
