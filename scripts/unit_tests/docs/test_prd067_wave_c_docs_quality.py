"""PRD 067 Wave C — docs quality mechanical checks (R15–R23)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUIDES = ROOT / "docs" / "guides"
PROVENANCE = re.compile(r"\bPRD\s*\d+|\bR\d+\b|\bGAP-\d+", re.I)


def test_style_guide_exists_with_diataxis_and_naming() -> None:
    path = GUIDES / "style-guide.md"
    assert path.is_file()
    text = path.read_text()
    assert re.search(r"Di[aá]taxis", text, re.I)
    assert "Google" in text
    assert "slug" in text.lower()
    assert "Conventional Commits" in text


def test_glossary_and_decision_tree_exist() -> None:
    gloss = (GUIDES / "glossary.md").read_text()
    for term in ("unit", "gap", "freeze", "deliver", "wave", "phase", "conductor"):
        assert term in gloss.lower()
    tree = (GUIDES / "decision-tree.md").read_text()
    assert "```mermaid" in tree


def test_documentation_dir_absent() -> None:
    assert not (ROOT / "documentation").exists()


def test_user_guides_free_of_prd_tokens() -> None:
    paths = list(GUIDES.glob("*.md")) + [ROOT / "README.md"]
    offenders: list[str] = []
    for path in paths:
        if PROVENANCE.search(path.read_text()):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_configuration_documents_delegation_mode() -> None:
    text = (GUIDES / "configuration.md").read_text()
    assert "delegation.mode" in text
    assert "bind-only" in text
    assert "heuristic" in text


def test_getting_started_has_adoption_arc() -> None:
    text = (GUIDES / "getting-started.md").read_text()
    assert "First session" in text
    assert "Week two" in text
    assert "After a month" in text or "after a month" in text.lower()
