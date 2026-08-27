#!/usr/bin/env python3
"""Context-switch hook replacement tests (PRD 333 R3, R4, R15, R19)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_CORE_HOOKS = _SCRIPTS.parent / "core" / "hooks"
if str(_CORE_HOOKS) not in sys.path:
    sys.path.insert(0, str(_CORE_HOOKS))

from context_switch_handoff import (  # noqa: E402
    BUNDLE_DIR,
    BUNDLE_FILENAME,
    REF_FILENAME,
    export_on_context_switch,
)
from handoff_bundle import (  # noqa: E402
    SCHEMA_VERSION,
    attach_transition_provenance,
    build_transition_provenance,
    build_workflow_digest,
    digest_payload,
    import_cross_harness,
)


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


def test_export_on_context_switch_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_schema(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CURSOR_PLUGIN_ROOT", "/tmp/cursor")
    monkeypatch.delenv("CLAUDE_CODE", raising=False)
    monkeypatch.setenv("SW_UNIT_ID", "tasks-333-eval-corpus-handoff-and-platform-providers")
    monkeypatch.setenv("SW_PHASE_SLUG", "context-switch-hook-replacement")

    payload = export_on_context_switch(repo, trigger="context-switch", destination_harness="claude-code")
    assert payload["verdict"] == "pass", payload
    assert payload["readOnly"] is True
    assert payload["resumeForbidden"] is True
    assert payload["foreignHarnessResumeForbidden"] is True
    assert payload["trigger"] == "context-switch"
    assert payload["sourceHarness"] == "cursor"
    assert payload["destinationHarness"] == "claude-code"

    bundle_ref = payload["bundleReference"]
    assert bundle_ref["trigger"] == "context-switch"
    assert bundle_ref["bundlePath"] == f"{BUNDLE_DIR}/context-switch-latest.json"
    bundle_path = repo / bundle_ref["bundlePath"]
    ref_path = repo / BUNDLE_DIR / REF_FILENAME
    assert bundle_path.is_file()
    assert ref_path.is_file()
    assert bundle_ref["bundleDigest"] == payload["bundleDigest"]

    import_handoff = payload["importHandoff"]
    assert import_handoff["destinationHarness"] == "claude-code"
    assert import_handoff["bundlePath"] == bundle_ref["bundlePath"]
    assert "handoff_bundle.py import" in import_handoff["importCommand"]

    monkeypatch.delenv("CURSOR_PLUGIN_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_CODE", "1")
    imported = import_cross_harness(repo, bundle_path, destination_harness="claude-code")
    assert imported["verdict"] == "pass", imported
    assert imported["transitionAccepted"] is True


def test_named_stub_symbol_and_observable_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_schema(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CLAUDE_CODE", "1")
    monkeypatch.setenv("SW_UNIT_ID", "tasks-333-eval-corpus-handoff-and-platform-providers")

    first = export_on_context_switch(repo, trigger="pause")
    assert first["verdict"] == "pass"
    first_digest = first["bundleDigest"]

    second = export_on_context_switch(repo, trigger="pause")
    assert second["verdict"] == "pass"
    assert second["bundleReference"]["bundlePath"] == f"{BUNDLE_DIR}/{BUNDLE_FILENAME}"
    assert second["bundleDigest"] == first_digest

    hooks_manifest = json.loads((_SCRIPTS.parent / "core" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert hooks_manifest["contextSwitch"]["implementation"].endswith("context_switch_handoff.py")
    assert hooks_manifest["registrations"]["cursor"]["trigger"] == "context-switch"
    assert hooks_manifest["registrations"]["claude-code"]["trigger"] == "context-switch"


def test_context_switch_failure_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_schema(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CURSOR_PLUGIN_ROOT", "/tmp/cursor")
    monkeypatch.setenv("SW_UNIT_ID", "tasks-333-eval-corpus-handoff-and-platform-providers")

    unsupported = export_on_context_switch(repo, destination_harness="codex")
    assert unsupported["verdict"] == "fail"
    assert unsupported["error"] == "handoff:unsupported-destination-harness"
    assert unsupported["readOnly"] is True
    assert unsupported["resumeForbidden"] is True

    missing = export_on_context_switch(tmp_path / "empty")
    assert missing["verdict"] == "fail"
    assert missing["error"] == "handoff:missing-durable-state"

    ok = export_on_context_switch(repo, destination_harness="claude-code", handoff_degraded=True)
    assert ok["verdict"] == "pass"
    bundle_path = repo / ok["bundleReference"]["bundlePath"]
    stale_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    stale_bundle["expiresAt"] = "2020-01-01T00:00:00Z"
    stale_bundle["workflowDigest"] = build_workflow_digest(stale_bundle)
    stale_bundle["bundleDigest"] = digest_payload(stale_bundle)
    stale_bundle = attach_transition_provenance(
        stale_bundle,
        build_transition_provenance(
            stale_bundle,
            source_harness="cursor",
            destination_harness="claude-code",
            session_transition="switch",
            source_model="composer-2.5",
            destination_model="claude-opus-5-thinking-high",
        ),
    )
    bundle_path.write_text(json.dumps(stale_bundle, indent=2) + "\n", encoding="utf-8")
    stale_import = import_cross_harness(repo, bundle_path, destination_harness="claude-code")
    assert stale_import["verdict"] == "halt"
    assert stale_import["error"] == "handoff:stale"

    tampered = json.loads(bundle_path.read_text(encoding="utf-8"))
    tampered["goal"] = "tampered"
    tampered_import = import_cross_harness(repo, tampered, destination_harness="claude-code")
    assert tampered_import["verdict"] == "fail"
    assert tampered_import["error"] == "handoff:digest-mismatch"

    monkeypatch.delenv("SW_UNIT_ID", raising=False)
    exporter_failure = export_on_context_switch(repo, destination_harness="claude-code", handoff_degraded=False)
    assert exporter_failure["verdict"] == "fail"
    assert exporter_failure["resumeForbidden"] is True


def test_expired_bundle_reference_blocks_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_schema(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CURSOR_PLUGIN_ROOT", "/tmp/cursor")
    monkeypatch.setenv("SW_UNIT_ID", "tasks-333-eval-corpus-handoff-and-platform-providers")

    payload = export_on_context_switch(repo, destination_harness="claude-code", handoff_degraded=True)
    bundle_path = repo / payload["bundleReference"]["bundlePath"]
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["expiresAt"] = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle["schemaVersion"] = SCHEMA_VERSION
    bundle = attach_transition_provenance(
        bundle,
        build_transition_provenance(
            bundle,
            source_harness="cursor",
            destination_harness="claude-code",
            session_transition="switch",
            source_model="composer-2.5",
            destination_model="claude-opus-5-thinking-high",
        ),
    )
    bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    result = import_cross_harness(repo, bundle_path, destination_harness="claude-code")
    assert result["verdict"] == "halt"
    assert result["error"] == "handoff:stale"
