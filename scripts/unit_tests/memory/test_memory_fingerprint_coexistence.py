"""PRD 082 R29 — fingerprint allowlist and v1/v2 coexistence fixtures."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_envelope_v2 as env  # noqa: E402
import memory_envelope_upgrade as upgrade  # noqa: E402
import memory_fingerprint as fp  # noqa: E402


def _v1_record(**overrides) -> dict:
    doc = {
        "schemaVersion": 1,
        "id": "mem-coexist-001",
        "project": "shipwright",
        "category": "decision",
        "status": "active",
        "content": "Always run memory-preflight before writes.",
        "customVendorTag": "preserve-me",
    }
    doc.update(overrides)
    return doc


def _v1_corpus() -> list[dict]:
    return [
        _v1_record(),
        _v1_record(
            id="mem-coexist-002",
            category="learning",
            content="Broker-only secret access.",
        ),
    ]


def test_fingerprint_excludes_envelope_evolution_fields() -> None:
    base = env.new_envelope(
        stable_id="mem-evolve",
        project_id="shipwright",
        category="decision",
        payload={"summary": "stable semantic body"},
    )
    mutated = copy.deepcopy(base)
    mutated["schemaVersion"] = 99
    mutated["contentHash"] = "f" * 64
    mutated["validUntil"] = "2099-01-01T00:00:00Z"
    mutated["status"] = "superseded"
    mutated["sensitivity"] = "secret"
    mutated["evidenceRefs"] = ["docs/evidence.md"]
    mutated["supersedes"] = ["mem-old"]
    mutated["appliedRedaction"] = {
        "applied": True,
        "profile": "strict",
        "redactedAt": "2026-01-01T00:00:00Z",
        "redactionScript": "scripts/memory-redact.py",
    }

    assert fp.note_fingerprint(base) == fp.note_fingerprint(mutated)


def test_v1_and_upgraded_v2_share_fingerprint() -> None:
    v1 = _v1_record()
    v2 = upgrade.upgrade_v1_to_v2(v1)
    assert fp.note_fingerprint(v1) == fp.note_fingerprint(v2)


def test_import_upgrade_reimport_zero_remaps_and_zero_new_records() -> None:
    store: dict[str, dict] = {}
    remaps: list[str] = []
    created: list[str] = []

    for raw in _v1_corpus():
        outcome = fp.import_record(store, raw, upgrade=False)
        if outcome.remapped:
            remaps.append(outcome.stable_id)
        if outcome.created:
            created.append(outcome.stable_id)

    for sid, record in list(store.items()):
        store[sid] = upgrade.upgrade_v1_to_v2(record)

    for raw in _v1_corpus():
        outcome = fp.import_record(store, raw, upgrade=True)
        if outcome.remapped:
            remaps.append(outcome.stable_id)
        if outcome.created:
            created.append(outcome.stable_id)

    assert remaps == []
    assert created == ["mem-coexist-001", "mem-coexist-002"]
    assert len(store) == 2
    for record in store.values():
        assert record.get("schemaVersion") == env.SCHEMA_VERSION


def test_same_identity_different_schema_versions_upgrade_in_place() -> None:
    store: dict[str, dict] = {}

    v1_a = _v1_record()
    first = fp.import_record(store, v1_a, upgrade=True)
    assert first.created is True
    assert first.remapped is False

    v1_b = _v1_record(schemaVersion=1, status="active")
    second = fp.import_record(store, v1_b, upgrade=True)
    assert second.remapped is False
    assert second.created is False
    assert second.stable_id == "mem-coexist-001"
    assert len(store) == 1

    v2_evolved = copy.deepcopy(store["mem-coexist-001"])
    v2_evolved["validUntil"] = "2099-12-31T23:59:59Z"
    v2_evolved["contentHash"] = "a" * 64
    assert fp.note_fingerprint(store["mem-coexist-001"]) == fp.note_fingerprint(v2_evolved)

    third = fp.import_record(store, v1_b, upgrade=True)
    assert third.remapped is False
    assert third.created is False
    assert len(store) == 1


def test_semantic_drift_remaps_on_id_collision() -> None:
    store: dict[str, dict] = {}
    fp.import_record(store, _v1_record(), upgrade=True)
    conflicting = _v1_record(content="Different semantic body.")
    outcome = fp.import_record(store, conflicting, upgrade=True)
    assert outcome.remapped is True
    assert outcome.created is True
    assert outcome.stable_id != "mem-coexist-001"
    assert len(store) == 2


def test_allowlist_and_exclusions_are_named_constants() -> None:
    assert "stableId" in fp.NOTE_FINGERPRINT_ALLOWLIST
    assert "schemaVersion" in fp.FINGERPRINT_EXCLUDED
    assert "contentHash" in fp.FINGERPRINT_EXCLUDED
    assert "appliedRedaction" in fp.FINGERPRINT_EXCLUDED


def test_interchange_note_fingerprint_ignores_timestamps() -> None:
    left = {
        "id": "rule/mock-realism",
        "category": "rule",
        "body": "Mocks must behave like production.",
        "fields": {"updatedAt": "2026-01-01", "tier": "internal"},
    }
    right = {
        "id": "rule/mock-realism",
        "category": "rule",
        "body": "Mocks must behave like production.",
        "fields": {"updatedAt": "2026-06-01", "tier": "internal"},
    }
    assert fp.note_fingerprint(left) == fp.note_fingerprint(right)
