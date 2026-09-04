"""PRD 326 R13 / PRD 330 R4–R5, R10 — architecture doctrine artifact and consumer boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import architecture_assessment as aa

COMMANDS_DIRS = ("core/commands", "commands")
FORBIDDEN_COMMAND_STEMS = frozenset({"sw-codebase-design"})
CONSUMER_VOCABULARY_KEYS = aa.CONSUMER_VOCABULARY_KEYS

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
    for rel in ("core/sw-reference/layout.md", ".shipwright/layout.md"):
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


def test_shipwright_self_separation_in_committed_artifact(repo_root: Path) -> None:
    text = (repo_root / "core/sw-reference/architecture-doctrine.md").read_text(encoding="utf-8")
    assert "Shipwright-self" in text
    assert "consumer" in text.lower()
    assert "ProjectDoctrine@v1" in text
    assert ".sw/project-doctrine.json" in text
    assert "not" in text.lower() and "authority" in text.lower()


def test_consumer_architecture_vocabulary_documented(repo_root: Path) -> None:
    text = (repo_root / "core/sw-reference/architecture-doctrine.md").read_text(encoding="utf-8")
    for term in CONSUMER_VOCABULARY_KEYS:
        assert term in text


def test_excluded_product_org_ops_scope(repo_root: Path) -> None:
    text = (repo_root / "core/sw-reference/architecture-doctrine.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "product roadmap" in lowered or "product-roadmap" in lowered
    assert "org chart" in lowered or "org-chart" in lowered
    assert "runtime runbook" in lowered or "runtime-runbook" in lowered
    assert "excluded" in lowered


def test_codebase_design_is_reference_not_command(repo_root: Path) -> None:
    text = (repo_root / "core/sw-reference/architecture-doctrine.md").read_text(encoding="utf-8")
    assert "codebase-design" in text.lower() or "codebase design" in text.lower()
    assert "/sw-codebase-design" in text
    assert "not" in text.lower() or "no " in text.lower()


def test_no_codebase_design_command_registered(repo_root: Path) -> None:
    found: list[str] = []
    for directory in COMMANDS_DIRS:
        root = repo_root / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.stem in FORBIDDEN_COMMAND_STEMS or "sw-codebase-design" in path.name:
                found.append(str(path.relative_to(repo_root)))
    assert found == [], f"unexpected forbidden command registration: {found}"


def _minimal_consumer_doctrine(**overrides: object) -> dict:
    doc = {
        "id": "consumer-app",
        "version": "ProjectDoctrine@v1",
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "test"},
        "confidence": "high",
        "sourceRefs": [{"uri": "file://fixture"}],
        "architecture": {
            "modules": [{"id": "billing", "name": "Billing"}],
            "interfaces": [{"id": "payments-api", "name": "Payments API"}],
            "seams": [{"id": "provider-seam", "name": "Provider seam"}],
            "adapters": [{"id": "stripe-adapter", "name": "Stripe adapter"}],
            "locality": [{"id": "eu-data", "name": "EU data residency"}],
        },
        "assessment": {
            "entries": [
                {"id": "billing", "verdict": "pass"},
                {"id": "payments-api", "verdict": "manual"},
            ]
        },
    }
    doc.update(overrides)
    return doc


def test_consumer_vocabulary_extraction() -> None:
    doc = _minimal_consumer_doctrine()
    vocabulary = aa.extract_consumer_vocabulary(doc)
    assert set(vocabulary) == set(CONSUMER_VOCABULARY_KEYS)
    assert len(vocabulary["modules"]) == 1
    assert vocabulary["modules"][0]["id"] == "billing"


def test_consumer_assessment_compatibility(tmp_path: Path) -> None:
    doctrine_path = tmp_path / ".sw" / "project-doctrine.json"
    doctrine_path.parent.mkdir(parents=True)
    doctrine_path.write_text(json.dumps(_minimal_consumer_doctrine()), encoding="utf-8")
    result = aa.evaluate_consumer_assessments(tmp_path)
    assert result["verdict"] == "pass"
    assert "billing" in result["entries"]
    assert result["vocabulary"]["modules"] == 1


def test_consumer_forbidden_scope_rejected() -> None:
    doc = _minimal_consumer_doctrine(productRoadmap={"milestones": []})
    errors = aa.validate_consumer_doctrine_document(doc)
    assert any("productRoadmap" in err for err in errors)


def test_consumer_unknown_assessment_entry_fails(tmp_path: Path) -> None:
    doc = _minimal_consumer_doctrine(
        assessment={
            "entries": [
                {"id": "billing", "verdict": "pass"},
                {"id": "unknown-entry", "verdict": "pass"},
            ]
        }
    )
    doctrine_path = tmp_path / ".sw" / "project-doctrine.json"
    doctrine_path.parent.mkdir(parents=True)
    doctrine_path.write_text(json.dumps(doc), encoding="utf-8")
    result = aa.evaluate_consumer_assessments(tmp_path)
    assert result["verdict"] == "fail"
    assert "unknown-entry" in result["failed"]


def test_consumer_doctrine_missing_skips_evaluation(tmp_path: Path) -> None:
    result = aa.evaluate_consumer_assessments(tmp_path)
    assert result["verdict"] == "skip"


def test_bundled_ad_id_rejected_in_consumer_vocabulary() -> None:
    doc = _minimal_consumer_doctrine(
        architecture={
            "modules": [{"id": "AD-1", "name": "Leaked"}],
            "interfaces": [],
            "seams": [],
            "adapters": [],
            "locality": [],
        }
    )
    errors = aa.validate_consumer_doctrine_document(doc)
    assert any("Shipwright-self" in err or "AD-1" in err for err in errors)


def test_codebase_design_is_not_a_command_flag() -> None:
    assert aa.CODEBASE_DESIGN_IS_COMMAND is False


def test_consumer_assessment_artifact_is_read_only(tmp_path: Path) -> None:
    doctrine = _minimal_consumer_doctrine(
        assessment={"artifactPath": ".cursor/consumer-assessment.yaml"}
    )
    (tmp_path / ".sw").mkdir()
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".sw" / "project-doctrine.json").write_text(
        json.dumps(doctrine), encoding="utf-8"
    )
    (tmp_path / ".cursor" / "consumer-assessment.yaml").write_text(
        "entries:\n  - id: billing\n    verdict: pass\n",
        encoding="utf-8",
    )
    before = (tmp_path / ".sw" / "project-doctrine.json").read_text(encoding="utf-8")
    result = aa.evaluate_consumer_assessments(tmp_path)
    after = (tmp_path / ".sw" / "project-doctrine.json").read_text(encoding="utf-8")
    assert result["verdict"] == "pass"
    assert before == after
