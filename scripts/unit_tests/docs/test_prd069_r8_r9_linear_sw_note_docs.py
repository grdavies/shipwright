"""PRD 069 R8–R9 — Linear issue-store and /sw-note documentation checks."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUIDES = ROOT / "docs" / "guides"
README = ROOT / "README.md"


def test_configuration_lists_linear_issues_provider() -> None:
    text = (GUIDES / "configuration.md").read_text(encoding="utf-8")
    assert "`linear`" in text
    assert re.search(
        r"planning\.store\.issuesProvider.*linear",
        text,
    )
    assert "planning.store.issues.teamKey" in text
    assert "planning.store.issues.teamId" in text
    assert "planning.store.issues.authMode" in text
    assert "planning.store.operatorProjection.linear" in text
    assert 'issuesProvider": "linear"' in text


def test_commands_document_sw_note_shapes_and_graduate() -> None:
    text = (GUIDES / "commands.md").read_text(encoding="utf-8")
    assert "/sw-note" in text
    assert ".cursor/sw-notebook" in text
    for shape in ("idea", "task", "note"):
        assert f"`{shape}`" in text
    assert "graduate" in text.lower()
    assert "--to gap" in text
    assert "--to brainstorm" in text
    assert "planning_gap_capture.py" in text
    assert "outside the planning store" in text.lower()


def test_readme_discovers_sw_note_and_linear_config() -> None:
    text = README.read_text(encoding="utf-8")
    assert "/sw-note" in text
    assert "Linear" in text
