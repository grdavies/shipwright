"""Unit tests for memory_playbook_lib (PRD 064 R26-R28, R33)."""
from __future__ import annotations

from pathlib import Path

import memory_playbook_lib as lib

FIX = Path(__file__).resolve().parents[1] / "test" / "fixtures" / "memory-playbook"
STORE = FIX / "store"
ROOT = Path(__file__).resolve().parents[2]


def test_playbook_struct_parses_steps():
    records = lib.load_playbook_records(STORE)
    active = next(r for r in records if r["id"] == "20260711-ship-stabilize-playbook")
    struct = lib.playbook_struct(active)
    assert struct["playbookStatus"] == "active"
    assert "stabilize" in struct["triggerKeywords"]
    assert struct["steps"][0]["command"] == "python3 scripts/check-gate.py"


def test_primary_inject_selects_active_high_confidence_match():
    signals = {"command": "sw-stabilize", "keywords": ["ci"]}
    blocks = lib.primary_inject_blocks(STORE, signal_context=signals, root=ROOT)
    assert len(blocks) == 1
    assert "primary-playbook:20260711-ship-stabilize-playbook" in blocks[0]["label"]
    assert "check-gate" in blocks[0]["text"]


def test_draft_playbook_not_injected():
    signals = {"command": "sw-debug", "keywords": ["debug"]}
    blocks = lib.primary_inject_blocks(STORE, signal_context=signals, root=ROOT)
    assert blocks == []


def test_promotion_requires_audit_and_skeptic():
    records = lib.load_playbook_records(STORE)
    draft = next(r for r in records if r["id"] == "20260711-draft-playbook")
    cfg = lib.load_playbook_config(ROOT)
    eligible, reason = lib.promotion_eligible(ROOT, draft["fields"], cfg)
    assert eligible is False
    assert reason == "skeptic-not-pass"


def test_reconcile_confidence_promotes_on_success_rate():
    cfg = lib.PlaybookConfig(
        enabled=True,
        inject_min_confidence=0.75,
        active_min_confidence=0.6,
        promote_min_success_rate=0.8,
        promote_min_usage=5,
        demote_max_success_rate=0.4,
        demote_min_usage=5,
        confidence_step=0.05,
    )
    fields = {
        "category": "learning",
        "confidence": 0.7,
        "usage_count": 6,
        "success_count": 5,
    }
    updated, actions = lib.reconcile_confidence_fields(fields, cfg)
    assert "promote-confidence" in actions
    assert updated["confidence"] == 0.75


def test_audit_telemetry_valid_reads_fixture():
    ref = "scripts/test/fixtures/memory-playbook/claims-audit-pass.json"
    assert lib.audit_telemetry_valid(ROOT, ref) is True
