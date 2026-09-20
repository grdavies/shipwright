"""PRD 365 phase 5 — dist skill/synthesis emit lockstep and Linear wording (R4, R6)."""

from __future__ import annotations

import re
from pathlib import Path

from _sw.vendor_paths import repo_root

REPO_ROOT = repo_root(__file__)
CORE_SKILL = REPO_ROOT / "core/skills/doc-review/SKILL.md"
CORE_SYNTHESIS = REPO_ROOT / "core/skills/doc-review/references/synthesis.md"
DIST_PLATFORMS = ("cursor", "codex", "opencode", "claude-code")

FACADE_OPS = ("post", "open", "read", "verify", "close")


def test_dist_skill_synthesis_lockstep() -> None:
    """R4 — packaged dist copies match canonical core bodies."""
    skill = CORE_SKILL.read_text(encoding="utf-8")
    synthesis = CORE_SYNTHESIS.read_text(encoding="utf-8")
    for platform in DIST_PLATFORMS:
        dist_skill = REPO_ROOT / f"dist/{platform}/skills/doc-review/SKILL.md"
        dist_synthesis = REPO_ROOT / f"dist/{platform}/skills/doc-review/references/synthesis.md"
        assert dist_skill.is_file(), f"missing dist skill: {dist_skill}"
        assert dist_synthesis.is_file(), f"missing dist synthesis: {dist_synthesis}"
        assert dist_skill.read_text(encoding="utf-8") == skill
        assert dist_synthesis.read_text(encoding="utf-8") == synthesis


def test_linear_support_and_five_ops() -> None:
    """R6 — Linear support sentences unchanged; facade exposes five public round ops."""
    text = CORE_SKILL.read_text(encoding="utf-8")
    assert "GitHub" in text and "Linear" in text
    assert "docReviewComments" in text
    match = re.search(
        r"doc-review-round-\{([^}]+)\}",
        text,
    )
    assert match is not None, "facade op list missing from SKILL.md"
    listed = [part.strip() for part in match.group(1).split(",")]
    assert listed == list(FACADE_OPS)
