"""PRD 330 R11, R13 — Shipwright-self leakage detection and migration fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_doctrine_leakage import (  # noqa: E402
    evaluate_doctrine,
    is_valid_shipwright_self_pointer,
    migrate_doctrine,
    run_scan,
    validate_leakage_green,
)


def _minimal_doctrine(**overrides: object) -> dict:
    doc = {
        "id": "consumer-doctrine",
        "version": "ProjectDoctrine@v1",
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "operator-review",
        },
        "confidence": "high",
        "sourceRefs": [{"uri": "file://repo/README.md"}],
        "architecture": {
            "modules": [{"id": "mod-api", "name": "API layer"}],
        },
    }
    doc.update(overrides)
    return doc


def test_clean_consumer_doctrine_passes() -> None:
    result = evaluate_doctrine(_minimal_doctrine())
    assert result["verdict"] == "pass"
    assert result["findingCount"] == 0


def test_valid_pointer_is_allowed() -> None:
    doc = _minimal_doctrine(
        shipwrightSelfRef={
            "uri": "shipwright-self:core/sw-reference/architecture-doctrine.md",
            "kind": "pointer",
            "label": "Bundled reference",
        }
    )
    result = evaluate_doctrine(doc)
    assert result["verdict"] == "pass"


def test_reject_fixture_with_shipwright_self_marker_fails() -> None:
    doc = _minimal_doctrine(
        shipwrightSelf={
            "statements": ["Broker-only credential access"],
        }
    )
    result = evaluate_doctrine(doc)
    assert result["verdict"] == "fail"
    assert any(f["rule"] == "forbidden-embed-key" for f in result["findings"])


def test_reject_fixture_with_bundled_ad_id_fails() -> None:
    doc = _minimal_doctrine(
        architecture={
            "modules": [
                {
                    "id": "AD-1",
                    "name": "Python-first workflow logic",
                    "rationale": "Workflow automation must stay stdlib-first Python",
                }
            ]
        }
    )
    result = evaluate_doctrine(doc)
    assert result["verdict"] == "fail"
    rules = {finding["rule"] for finding in result["findings"]}
    assert "bundled-ad-id" in rules


def test_reject_fixture_with_copied_law_snippet_fails() -> None:
    doc = _minimal_doctrine(
        architecture={
            "modules": [
                {
                    "id": "consumer-mod",
                    "name": "Payments",
                    "rationale": "CI readiness gate authority must stay centralized",
                }
            ]
        }
    )
    result = evaluate_doctrine(doc)
    assert result["verdict"] == "fail"
    assert any(f["rule"] == "bundled-architecture-field" for f in result["findings"])


def test_pointer_migration_turns_green() -> None:
    doc = _minimal_doctrine(
        shipwrightSelf={"statements": ["Broker-only credential access"]},
        architecture={
            "modules": [
                {
                    "id": "AD-2",
                    "name": "CI readiness gate authority",
                }
            ]
        },
    )
    migrated = migrate_doctrine(doc, mode="pointer")
    after = evaluate_doctrine(migrated)
    assert after["verdict"] == "pass"
    assert is_valid_shipwright_self_pointer(migrated.get("shipwrightSelfRef"))
    assert "shipwrightSelf" not in migrated


def test_replace_migration_turns_green_without_pointer() -> None:
    doc = _minimal_doctrine(
        shipwrightSelfLaw={"text": "sw- command namespace"},
    )
    migrated = migrate_doctrine(doc, mode="replace")
    after = evaluate_doctrine(migrated)
    assert after["verdict"] == "pass"
    assert "shipwrightSelfRef" not in migrated


def test_adoption_requires_green_leakage_verdict(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    leaked = _minimal_doctrine(shipwrightSelf={"statements": ["Worktree-isolated delivery"]})
    doctrine_path = root / ".cursor" / "project-doctrine.json"
    doctrine_path.parent.mkdir(parents=True)
    doctrine_path.write_text(json.dumps(leaked), encoding="utf-8")
    assert validate_leakage_green(root) is not None

    migrated = migrate_doctrine(leaked, mode="pointer")
    doctrine_path.write_text(json.dumps(migrated), encoding="utf-8")
    assert validate_leakage_green(root) is None
    scan = run_scan(root)
    assert scan["verdict"] == "pass"


def test_invalid_pointer_kind_fails() -> None:
    doc = _minimal_doctrine(
        shipwrightSelfRef={
            "uri": "shipwright-self:core/sw-reference/architecture-doctrine.md",
            "kind": "copied-law",
        }
    )
    result = evaluate_doctrine(doc)
    assert result["verdict"] == "fail"
    assert any(f["rule"] == "invalid-shipwright-self-ref" for f in result["findings"])
