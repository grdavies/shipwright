"""PRD 082 R29 — memory envelope v2 codec and v1 upgrader fixtures."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_envelope_upgrade as upgrade  # noqa: E402
import memory_envelope_v2 as env  # noqa: E402


def _sample_v2(**overrides) -> dict:
    doc = env.new_envelope(
        stable_id="mem-auth-jwt",
        project_id="shipwright",
        category="decision",
        evidence_refs=["docs/decisions/042-auth-jwt.md"],
        confidence=0.9,
        sensitivity="internal",
        payload={"summary": "Use JWT for session auth"},
    )
    doc.update(overrides)
    doc["contentHash"] = env.compute_content_hash(doc)
    return doc


def test_schema_validation_rejects_malformed_envelope() -> None:
    with pytest.raises(env.EnvelopeError):
        env.parse_envelope({"stableId": "x"})

    bad = _sample_v2()
    bad["contentHash"] = "0" * 64
    with pytest.raises(env.EnvelopeError):
        env.parse_envelope(bad)


def test_supersession_chain_resolves_to_active_tip() -> None:
    first = _sample_v2(stableId="mem-v1", status="active")
    second = env.new_envelope(
        stable_id="mem-v2",
        project_id="shipwright",
        category="decision",
        supersedes=["mem-v1"],
        payload={"summary": "Rotate to session cookies"},
    )
    first_superseded = dict(first)
    first_superseded["status"] = "superseded"
    first_superseded["contentHash"] = env.compute_content_hash(first_superseded)

    envelopes = {
        "mem-v1": first_superseded,
        "mem-v2": second,
    }
    assert env.resolve_supersession_chain(envelopes, "mem-v1") == "mem-v2"


def test_supersede_replaces_mutation_in_place() -> None:
    active = _sample_v2()
    superseded, replacement = env.supersede(active, replacement_id="mem-auth-session")
    assert superseded["status"] == "superseded"
    assert replacement["status"] == "active"
    assert replacement["stableId"] == "mem-auth-session"
    assert active["stableId"] in replacement["supersedes"]
    env.parse_envelope(superseded)
    env.parse_envelope(replacement)


def test_v1_corpus_upgrades_with_unknown_fields_preserved() -> None:
    v1 = {
        "schemaVersion": 1,
        "id": "legacy-note",
        "project": "shipwright",
        "category": "learning",
        "status": "active",
        "content": "Always run memory-preflight first.",
        "customVendorTag": "keep-me",
        "nested": {"opaque": True},
    }
    v2 = upgrade.upgrade_v1_to_v2(v1)
    env.parse_envelope(v2)
    assert v2["stableId"] == "legacy-note"
    assert v2["schemaVersion"] == env.SCHEMA_VERSION
    assert v2["v1Preserved"]["customVendorTag"] == "keep-me"
    assert v2["v1Preserved"]["nested"] == {"opaque": True}
    assert v2["payload"]["content"] == v1["content"]


def test_planning_body_payload_accepted_without_envelope() -> None:
    planning_body = {
        "unitId": "prd-082-planning-authority-memory-integrity",
        "body": "# PRD\n\nPlanning unit body text.",
        "projectKey": "shipwright",
    }
    assert env.is_planning_body_payload(planning_body)
    assert not env.envelope_required(planning_body)

    explicit = {
        "domain": "planning-body",
        "unitId": "gap-001",
        "body": "gap text",
    }
    assert env.is_planning_body_payload(explicit)


def test_alias_merge_ledger_records_identity_mappings(tmp_path: Path) -> None:
    ledger = upgrade.empty_alias_ledger()
    ledger = upgrade.record_alias(ledger, from_id="old-id", to_id="canonical-id", reason="merge")
    upgrade.save_alias_ledger(tmp_path, ledger)
    loaded = upgrade.load_alias_ledger(tmp_path)
    assert upgrade.resolve_stable_id(loaded, "old-id") == "canonical-id"
    assert upgrade.resolve_stable_id(loaded, "canonical-id") == "canonical-id"


def test_upgrade_if_needed_is_idempotent_for_v2() -> None:
    doc = _sample_v2()
    again = upgrade.upgrade_if_needed(copy.deepcopy(doc))
    assert again["stableId"] == doc["stableId"]
    assert again["contentHash"] == doc["contentHash"]
