"""PRD 358 R11 — named provider/skill docs name reconstruct-before-ok, --root, and asterisk RID."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"missing named docs surface: {rel}"
    return path.read_text(encoding="utf-8")


def test_linear_md_names_single_owner_reconstruct_before_ok() -> None:
    """O — linear.md chunking names facade-owned split, UUID head budget, reconstruct-before-ok, skip-on-manifest."""
    text = _read("core/providers/issues/linear.md")
    lowered = text.lower()
    assert "reconstruct-before-ok" in lowered
    assert "skip-on-manifest" in lowered or "skip on manifest" in lowered
    assert "sw-chunk-manifest" in lowered
    assert "facade" in lowered
    assert "uuid" in lowered
    assert "60,000" in text or "60000" in text or "60_000" in text


def test_canonical_serialization_names_overflow_reconstruct_before_ok() -> None:
    """B — overflow reconstruct-before-ok plus writeToken/authorship bind (not stale head-only concat)."""
    text = _read("core/sw-reference/canonical-serialization.md")
    lowered = text.lower()
    assert "reconstruct-before-ok" in lowered
    assert "writetoken" in lowered
    assert "authorship" in lowered


def test_layout_names_installed_freshness_dual_mode() -> None:
    """S — capability-index freshness distinguishes source core/ vs installed/emitted bundle."""
    for rel in ("core/sw-reference/layout.md", ".shipwright/layout.md"):
        text = _read(rel)
        lowered = text.lower()
        assert "capability-index" in lowered or "capability index" in lowered
        assert "freshness" in lowered
        assert "dual-mode" in lowered or "dual mode" in lowered
        assert "source-tree" in lowered or "source `core/`" in lowered or "source-tree `core/`" in lowered
        assert "installed/emitted" in lowered or "installed bundle" in lowered or "emitted bundle" in lowered


SKILL_SURFACES = (
    "core/skills/spec-rigor/SKILL.md",
    "core/commands/sw-freeze.md",
    "core/skills/brainstorm/SKILL.md",
    "core/skills/tasks/SKILL.md",
    "core/skills/prd/SKILL.md",
)


@pytest.mark.parametrize("rel", SKILL_SURFACES)
def test_skills_name_consumer_root_and_asterisk_rid(rel: str) -> None:
    """I — spec-rigor / freeze / brainstorm / tasks / prd name consumer --root and * RID markers."""
    text = _read(rel)
    assert "--root" in text
    lowered = text.lower()
    assert "asterisk" in lowered or "* **r" in lowered or "`* **" in text
    assert "rid" in lowered or "r-id" in lowered or "requirement" in lowered


def test_all_named_docs_exist() -> None:
    """M — every R11 named surface is present (E: no silent skip)."""
    required = (
        "core/providers/issues/linear.md",
        "core/sw-reference/canonical-serialization.md",
        "core/sw-reference/layout.md",
        ".shipwright/layout.md",
        *SKILL_SURFACES,
    )
    missing = [rel for rel in required if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"silent docs skip: {missing}"
