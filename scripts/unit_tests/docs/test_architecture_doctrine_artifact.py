"""PRD 326 R13 — architecture doctrine artifact well-formedness."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import architecture_assessment as aa

ONE_STMT = """\
**Version:** 1

## AD-1: Example

- **Rationale:** Example rationale text.
- **Signal:** `true`
"""

MANUAL_STMT = """\
**Version:** 1

## AD-1: Manual only

- **Rationale:** Human review is the only check.
- **manual:** true
"""

DUPLICATE_IDS = """\
**Version:** 1

## AD-1: First

- **Rationale:** one
- **Signal:** `true`

## AD-1: Duplicate

- **Rationale:** two
- **Signal:** `true`
"""

MISSING_ID = """\
**Version:** 1

## AD-1: First

- **Rationale:** one
- **Signal:** `true`

## AD-3: Skipped two

- **Rationale:** three
- **Signal:** `true`
"""


def test_empty_doctrine_rejected() -> None:
    result = aa.parse_doctrine_text("")
    assert result["verdict"] == "fail"
    assert result["error"] == "empty-doctrine-artifact"


def test_one_statement_with_rationale_and_signal() -> None:
    result = aa.parse_doctrine_text(ONE_STMT)
    assert result["verdict"] == "pass"
    assert len(result["statements"]) == 1
    assert result["statements"][0]["id"] == "AD-1"
    assert result["statements"][0]["rationale"]


def test_committed_doctrine_artifact_is_well_formed(repo_root: Path) -> None:
    result = aa.parse_doctrine(repo_root)
    assert result["verdict"] == "pass"
    ids = [stmt["id"] for stmt in result["statements"]]
    assert ids == sorted(ids, key=lambda item: int(item.split("-", 1)[1]))
    assert len(ids) == len(set(ids))


def test_manual_statement_without_signal_allowed() -> None:
    result = aa.parse_doctrine_text(MANUAL_STMT)
    assert result["verdict"] == "pass"
    assert result["statements"][0]["manual"] is True
    assert result["statements"][0]["signal"] is None


def test_duplicate_id_fails() -> None:
    result = aa.parse_doctrine_text(DUPLICATE_IDS)
    assert result["verdict"] == "fail"
    assert result["error"] == "duplicate-doctrine-id"


def test_missing_sequential_id_fails() -> None:
    result = aa.parse_doctrine_text(MISSING_ID)
    assert result["verdict"] == "fail"
    assert result["error"] == "missing-doctrine-id"


def test_layout_registration_present(repo_root: Path) -> None:
    for rel in ("core/sw-reference/layout.md", ".sw/layout.md"):
        text = (repo_root / rel).read_text(encoding="utf-8")
        assert "architecture-doctrine.md" in text
        assert "architecture-assessment.schema.json" in text


def test_parse_is_order_independent() -> None:
    reordered = """\
**Version:** 1

## AD-1: Example

- **Signal:** `true`
- **Rationale:** Example rationale text.
"""
    first = aa.parse_doctrine_text(ONE_STMT)
    second = aa.parse_doctrine_text(reordered)
    assert first["statements"] == second["statements"]
