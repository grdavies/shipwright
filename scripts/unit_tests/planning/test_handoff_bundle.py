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
    attach_transition_provenance,
    build_transition_provenance,
    build_workflow_digest,
    classify_model_transition,
    digest_payload,
    export_bundle,
    export_for_transition,
    import_bundle,
    import_cross_harness,
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


def _repo_with_schema(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "core" / "sw-reference").mkdir(parents=True)
    schema_src = _SCRIPTS.parent / "core" / "sw-reference" / "handoff-bundle.schema.json"
    (repo / "core" / "sw-reference" / "handoff-bundle.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / ".git").mkdir()
    return repo


CROSS_HARNESS_MATRIX = [
    ("cursor", "cursor", "resume", "same", "composer-2.5", "composer-2.5"),
    ("cursor", "cursor", "switch", "changed", "composer-2.5", "claude-opus-5-thinking-high"),
    ("cursor", "claude-code", "resume", "same", "composer-2.5", "composer-2.5"),
    ("cursor", "claude-code", "switch", "changed", "composer-2.5", "claude-opus-5-thinking-high"),
    ("claude-code", "cursor", "resume", "same", "claude-opus-5-thinking-high", "claude-opus-5-thinking-high"),
    ("claude-code", "cursor", "switch", "changed", "claude-opus-5-thinking-high", "composer-2.5"),
    ("claude-code", "claude-code", "resume", "same", "claude-opus-5-thinking-high", "claude-opus-5-thinking-high"),
    ("claude-code", "claude-code", "switch", "changed", "claude-opus-5-thinking-high", "composer-2.5"),
]


def test_cross_harness_completion_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_schema(tmp_path)
    monkeypatch.setenv("SW_UNIT_ID", "tasks-333-eval-corpus-handoff-and-platform-providers")
    for source, destination, session, model_transition, source_model, destination_model in CROSS_HARNESS_MATRIX:
        monkeypatch.setenv("CURSOR_PLUGIN_ROOT", "/tmp/cursor")
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        exported = export_for_transition(
            repo,
            source_harness=source,
            destination_harness=destination,
            session_transition=session,
            source_model=source_model,
            destination_model=destination_model,
            model_transition=model_transition,
            unit_id="tasks-333-eval-corpus-handoff-and-platform-providers",
            phase_slug="handoffbundle-cross-harness-runtime-completion",
            handoff_degraded=True,
        )
        assert exported["verdict"] == "pass", exported
        bundle = exported["bundle"]
        provenance = bundle["transitionProvenance"]
        assert provenance["sourceHarness"] == source
        assert provenance["destinationHarness"] == destination
        assert provenance["sessionTransition"] == session
        assert provenance["modelTransition"] == model_transition
        assert validate_bundle(bundle, root=repo)["verdict"] == "pass"
        if destination == "cursor":
            monkeypatch.setenv("CURSOR_PLUGIN_ROOT", "/tmp/cursor")
            monkeypatch.delenv("CLAUDE_CODE", raising=False)
        else:
            monkeypatch.delenv("CURSOR_PLUGIN_ROOT", raising=False)
            monkeypatch.setenv("CLAUDE_CODE", "1")
        monkeypatch.setenv("SW_ACTIVE_MODEL", destination_model)
        imported = import_cross_harness(repo, bundle, destination_harness=destination, destination_model=destination_model)
        assert imported["verdict"] == "pass", imported
        assert imported["transitionAccepted"] is True
        assert imported["foreignHarnessResumeForbidden"] is True


def test_required_failure_cells(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_schema(tmp_path)
    monkeypatch.setenv("SW_UNIT_ID", "tasks-333-eval-corpus-handoff-and-platform-providers")

    stale = _minimal_bundle(expiresAt="2020-01-01T00:00:00Z")
    stale = attach_transition_provenance(
        stale,
        build_transition_provenance(
            stale,
            source_harness="cursor",
            destination_harness="claude-code",
            session_transition="switch",
            source_model="composer-2.5",
            destination_model="claude-opus-5-thinking-high",
        ),
    )
    stale_result = import_cross_harness(repo, stale, destination_harness="claude-code", allow_stale=False)
    assert stale_result["verdict"] == "halt"
    assert stale_result["error"] == "handoff:stale"

    tampered = _minimal_bundle()
    tampered = attach_transition_provenance(
        tampered,
        build_transition_provenance(
            tampered,
            source_harness="cursor",
            destination_harness="cursor",
            session_transition="resume",
            source_model="composer-2.5",
            destination_model="composer-2.5",
        ),
    )
    tampered["goal"] = "tampered goal"
    tampered_result = import_cross_harness(repo, tampered, destination_harness="cursor")
    assert tampered_result["verdict"] == "fail"
    assert tampered_result["error"] == "handoff:digest-mismatch"

    (tmp_path / "empty").mkdir()
    missing_state = export_for_transition(
        tmp_path / "empty",
        source_harness="cursor",
        destination_harness="cursor",
        session_transition="resume",
    )
    assert missing_state["verdict"] == "fail"
    assert missing_state["error"] == "handoff:missing-durable-state"

    unsupported = _minimal_bundle(schemaVersion="HandoffBundle@v0")
    unsupported["workflowDigest"] = build_workflow_digest(unsupported)
    unsupported["bundleDigest"] = digest_payload(unsupported)
    unsupported_result = validate_bundle(unsupported, root=repo)
    assert unsupported_result["verdict"] == "fail"
    assert unsupported_result["error"] == "handoff:schema-version"

    partial = _minimal_bundle()
    partial_result = import_cross_harness(
        repo,
        partial,
        destination_harness="cursor",
        require_transition=True,
    )
    assert partial_result["verdict"] == "halt"
    assert partial_result["error"] == "handoff:missing-transition-provenance"

    exported = export_for_transition(
        repo,
        source_harness="cursor",
        destination_harness="claude-code",
        session_transition="switch",
        source_model="composer-2.5",
        destination_model="claude-opus-5-thinking-high",
        model_transition="changed",
        unit_id="tasks-333-eval-corpus-handoff-and-platform-providers",
        handoff_degraded=True,
    )
    assert exported["verdict"] == "pass"
    mismatch = import_cross_harness(
        repo,
        exported["bundle"],
        destination_harness="cursor",
        destination_model="claude-opus-5-thinking-high",
    )
    assert mismatch["verdict"] == "halt"
    assert mismatch["error"] == "handoff:destination-harness-mismatch"

    model_mismatch = import_cross_harness(
        repo,
        exported["bundle"],
        destination_harness="claude-code",
        destination_model="composer-2.5",
    )
    assert model_mismatch["verdict"] == "halt"
    assert model_mismatch["error"] == "handoff:model-transition-mismatch"


def test_classify_model_transition() -> None:
    assert classify_model_transition("composer-2.5", "composer-2.5") == "same"
    assert classify_model_transition("composer-2.5", "claude-opus-5-thinking-high") == "changed"
    assert classify_model_transition("", "composer-2.5") == "unknown"
