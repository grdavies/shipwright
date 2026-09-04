"""PRD 082 R26 — planning authority and guardrail documentation currency fixtures."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from docs_currency_planning import PLANNING_DOC_BINDINGS, check_planning_doc_currency


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".sw").mkdir(parents=True)
    (root / "core/sw-reference").mkdir(parents=True)
    (root / "core/providers/planning-store").mkdir(parents=True)
    (root / "core/rules").mkdir(parents=True)
    (root / "docs/guides").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    for binding in PLANNING_DOC_BINDINGS:
        for rel in binding["sources"]:
            src = root / rel
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(f"# source for {binding['id']}\n", encoding="utf-8")
    time.sleep(0.02)
    for binding in PLANNING_DOC_BINDINGS:
        doc = root / str(binding["doc"])
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("\n".join(binding["markers"]) + "\n", encoding="utf-8")
    return root


def test_planning_doc_currency_passes_when_current(repo: Path) -> None:
    assert check_planning_doc_currency(repo) == []


def test_planning_doc_currency_fails_when_doc_stale(repo: Path) -> None:
    binding = PLANNING_DOC_BINDINGS[0]
    source = repo / str(binding["sources"][0])
    time.sleep(0.02)
    source.write_text("# touched\n", encoding="utf-8")
    drift = check_planning_doc_currency(repo)
    assert any(
        row.get("kind") == "planning-doc-stale" and row.get("id") == binding["id"] for row in drift
    )


def test_planning_doc_currency_fails_when_marker_missing(repo: Path) -> None:
    doc = repo / ".shipwright/layout.md"
    doc.write_text("# incomplete\n", encoding="utf-8")
    drift = check_planning_doc_currency(repo)
    assert any(row.get("kind") == "planning-doc-marker-missing" for row in drift)


def test_docs_currency_gate_imports_planning_check() -> None:
    text = (SCRIPT_DIR / "docs-currency-gate.py").read_text(encoding="utf-8")
    assert "from docs_currency_planning import check_planning_doc_currency" in text
    assert "check_planning_doc_currency(root)" in text
