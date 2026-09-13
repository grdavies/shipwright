"""Unit tests for stdlib HandoffBundle validation (PRD 349 R7–R8, R10)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from core.handoff.validate_bundle import run_self_test, validate_bundle  # noqa: E402
from handoff_bundle import SCHEMA_VERSION, digest_payload, build_workflow_digest  # noqa: E402

FIXTURES = REPO / "core" / "tests" / "fixtures" / "bundle_self_test"


def _minimal(**overrides: object) -> dict:
    bundle = {
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": "2026-08-20T12:00:00Z",
        "expiresAt": "2099-01-01T00:00:00Z",
        "goal": "unit",
        "currentState": {"summary": "ok", "phaseStatus": "in-progress"},
        "resolvedDecisions": [],
        "unresolvedDecisions": [],
        "activeNode": None,
        "blockers": [],
        "evidence": [],
        "changedFiles": ["a.py"],
        "relevantRules": [],
        "nextAction": {"action": "continue", "detail": "x"},
    }
    bundle.update(overrides)
    bundle["workflowDigest"] = build_workflow_digest(bundle)
    bundle["bundleDigest"] = digest_payload(bundle)
    return bundle


def test_valid_bundle_passes() -> None:
    assert validate_bundle(_minimal())["verdict"] == "pass"


def test_tampered_digest_fails() -> None:
    bundle = _minimal()
    bundle["bundleDigest"] = "sha256:" + ("a" * 64)
    result = validate_bundle(bundle)
    assert result["verdict"] == "digest_failure"


def test_current_node_integer_schema_failure() -> None:
    bundle = _minimal(current_node=42)
    result = validate_bundle(bundle)
    assert result["verdict"] == "schema_failure"
    assert "current_node" in result.get("fields", [])


def test_missing_required_field() -> None:
    bundle = _minimal()
    del bundle["goal"]
    result = validate_bundle(bundle)
    assert result["verdict"] == "schema_failure"
    assert "goal" in (result.get("fields") or result.get("missing") or [])


def test_no_jsonschema_import_in_module() -> None:
    source = (REPO / "core" / "handoff" / "validate_bundle.py").read_text(encoding="utf-8")
    assert "import jsonschema" not in source and "from jsonschema" not in source
    assert "importlib" in source


def test_self_test_suite_green() -> None:
    payload = run_self_test()
    assert payload["verdict"] == "pass"
    assert payload["unexpected"] == 0


@pytest.mark.parametrize(
    "name,expected",
    [
        ("pass.json", "pass"),
        ("digest_failure.json", "digest_failure"),
        ("schema_failure.json", "schema_failure"),
        ("field_type_mismatch.json", "schema_failure"),
        ("missing_required.json", "schema_failure"),
    ],
)
def test_fixture_verdicts(name: str, expected: str) -> None:
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert validate_bundle(document)["verdict"] == expected
