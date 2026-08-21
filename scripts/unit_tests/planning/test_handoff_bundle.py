#!/usr/bin/env python3
"""Unit tests for HandoffBundle@v1 export/import (PRD 280 gap-324)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from handoff_bundle import (  # noqa: E402
    SCHEMA_VERSION,
    build_workflow_digest,
    digest_payload,
    export_bundle,
    import_bundle,
    is_stale,
    validate_bundle,
)


def _minimal_bundle(**overrides: object) -> dict:
    bundle = {
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": "2026-08-20T12:00:00Z",
        "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "goal": "Continue workflow extensions phase 2",
        "currentState": {"summary": "phase=test", "phaseStatus": "in-progress"},
        "resolvedDecisions": [],
        "unresolvedDecisions": [],
        "activeNode": None,
        "blockers": [],
        "evidence": [],
        "changedFiles": ["scripts/handoff_bundle.py"],
        "relevantRules": [],
        "nextAction": {"action": "review-handoff", "detail": "Import on target harness"},
    }
    bundle.update(overrides)
    bundle["workflowDigest"] = build_workflow_digest(bundle)
    bundle["bundleDigest"] = digest_payload(bundle)
    return bundle


def test_validate_bundle_fail_closed_on_missing_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core" / "sw-reference").mkdir(parents=True)
    schema_src = _SCRIPTS.parent / "core" / "sw-reference" / "handoff-bundle.schema.json"
    (repo / "core" / "sw-reference" / "handoff-bundle.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = validate_bundle({"schemaVersion": SCHEMA_VERSION}, root=repo)
    assert result["verdict"] == "fail"
    assert result["error"] == "handoff:missing-keys"


def test_validate_bundle_passes_minimal_round_trip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core" / "sw-reference").mkdir(parents=True)
    schema_src = _SCRIPTS.parent / "core" / "sw-reference" / "handoff-bundle.schema.json"
    (repo / "core" / "sw-reference" / "handoff-bundle.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bundle = _minimal_bundle()
    assert validate_bundle(bundle, root=repo)["verdict"] == "pass"


def test_import_rejects_stale_bundle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core" / "sw-reference").mkdir(parents=True)
    schema_src = _SCRIPTS.parent / "core" / "sw-reference" / "handoff-bundle.schema.json"
    (repo / "core" / "sw-reference" / "handoff-bundle.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bundle = _minimal_bundle(expiresAt="2020-01-01T00:00:00Z")
    bundle["workflowDigest"] = build_workflow_digest(bundle)
    bundle["bundleDigest"] = digest_payload(bundle)
    assert is_stale(bundle) is True
    result = import_bundle(repo, bundle)
    assert result["verdict"] == "halt"
    assert result["error"] == "handoff:stale"
    assert result["foreignHarnessResumeForbidden"] is True


def test_import_forbids_foreign_deliver_resume(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core" / "sw-reference").mkdir(parents=True)
    schema_src = _SCRIPTS.parent / "core" / "sw-reference" / "handoff-bundle.schema.json"
    (repo / "core" / "sw-reference" / "handoff-bundle.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bundle = _minimal_bundle(runId="deliver-test-run")
    result = import_bundle(repo, bundle)
    assert result["verdict"] == "pass"
    assert result["foreignHarnessResumeForbidden"] is True


def test_export_degraded_without_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core" / "sw-reference").mkdir(parents=True)
    schema_src = _SCRIPTS.parent / "core" / "sw-reference" / "handoff-bundle.schema.json"
    (repo / "core" / "sw-reference" / "handoff-bundle.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / ".git").mkdir()
    monkeypatch.setenv("SW_UNIT_ID", "tasks-280-workflow-extensions")
    result = export_bundle(repo, unit_id="tasks-280-workflow-extensions", handoff_degraded=True)
    assert result["verdict"] == "pass"
    bundle = result["bundle"]
    assert bundle["handoffDegraded"] is True
    assert bundle["schemaVersion"] == SCHEMA_VERSION
