"""PRD 067 Wave C — docs quality mechanical checks (R15–R23)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUIDES = ROOT / "docs" / "guides"
# Public docs/guides paths are durable redirect stubs; canonical bodies live here.
CANON = ROOT / "core" / "documentation"
PROVENANCE = re.compile(r"\bPRD\s*\d+|\bR\d+\b|\bGAP-\d+", re.I)


def _guide(name: str) -> Path:
    """Prefer canonical core/documentation body; require public stub still present."""
    stub = GUIDES / name
    assert stub.is_file(), f"missing public stub: {stub}"
    canon = CANON / name
    assert canon.is_file(), f"missing canonical guide: {canon}"
    return canon


def test_style_guide_exists_with_diataxis_and_naming() -> None:
    text = _guide("style-guide.md").read_text()
    assert re.search(r"Di[aá]taxis", text, re.I)
    assert "Google" in text
    assert "slug" in text.lower()
    assert "Conventional Commits" in text


def test_glossary_and_decision_tree_exist() -> None:
    gloss = _guide("glossary.md").read_text()
    for term in ("unit", "gap", "freeze", "deliver", "wave", "phase", "conductor"):
        assert term in gloss.lower()
    tree = _guide("decision-tree.md").read_text()
    assert "```mermaid" in tree


def test_documentation_dir_absent() -> None:
    assert not (ROOT / "documentation").exists()


def test_user_guides_free_of_prd_tokens() -> None:
    # Adopter-facing bodies are under core/documentation; docs/guides are stubs.
    paths = list(CANON.glob("*.md")) + [ROOT / "README.md"]
    offenders: list[str] = []
    for path in paths:
        if PROVENANCE.search(path.read_text()):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_configuration_documents_delegation_mode() -> None:
    text = _guide("configuration.md").read_text()
    assert "delegation.mode" in text
    assert "bind-only" in text
    assert "heuristic" in text


def test_getting_started_has_adoption_arc() -> None:
    text = _guide("getting-started.md").read_text()
    assert "First session" in text
    assert "Week two" in text
    assert "After a month" in text or "after a month" in text.lower()

def test_guide_token_strip_preserves_blank_lines() -> None:
    from docs_guide_token_strip import strip_guide_text

    sample = "Intro line with PRD 068 token\n\nSecond   line   R12 note\n"
    stripped = strip_guide_text(sample)
    assert stripped == "Intro line with token\n\nSecond line note\n"
    assert "\n\n" in stripped

