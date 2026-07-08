"""Tests for planning-doctor.py privacy-ack + key-naming reconciliation (PRD 057 R15, gap-046)."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

MODULE_NAME = "planning-doctor"


def _load_doctor():
    return importlib.import_module(MODULE_NAME)


def test_privacy_ack_required_when_not_recorded():
    doc = _load_doctor()
    cfg = {"planning": {"privacyAck": {"required": True, "recordedAt": None, "reason": "public-origin-remote"}}}
    finding = doc.privacy_ack_required_finding(cfg)
    assert finding is not None
    assert finding["check"] == "privacy-ack-required"
    assert finding["remediation"] == "python3 scripts/planning_visibility.py --root . record-privacy-ack"


def test_privacy_ack_not_required_once_recorded():
    doc = _load_doctor()
    cfg = {"planning": {"privacyAck": {"required": True, "recordedAt": "2026-07-07T00:00:00Z"}}}
    assert doc.privacy_ack_required_finding(cfg) is None


def test_privacy_ack_not_required_when_flag_false():
    doc = _load_doctor()
    cfg = {"planning": {"privacyAck": {"required": False, "recordedAt": None}}}
    assert doc.privacy_ack_required_finding(cfg) is None


def test_deprecated_visibility_key_finding():
    doc = _load_doctor()
    cfg = {"planning": {"visibilityProfile": "all-public"}}
    finding = doc.planning_visibility_deprecation_finding(cfg)
    assert finding is not None
    assert finding["check"] == "visibility-tier-key-deprecated"


def test_no_deprecated_visibility_key_finding_when_new_key_only():
    doc = _load_doctor()
    cfg = {"planning": {"visibilityTier": "all-public"}}
    assert doc.planning_visibility_deprecation_finding(cfg) is None


def test_privacy_notice_reconciliation_flags_stale_doc(tmp_path: Path):
    doc = _load_doctor()
    notice = tmp_path / "core" / "sw-reference" / "planning-privacy-notice.md"
    notice.parent.mkdir(parents=True)
    notice.write_text("Acknowledge by setting `planning.privacyAck.ackedAt`.", encoding="utf-8")
    finding = doc.privacy_notice_key_reconciliation_finding(tmp_path)
    assert finding is not None
    assert finding["check"] == "privacy-notice-key-stale"


def test_privacy_notice_reconciliation_passes_current_doc(repo_root: Path):
    doc = _load_doctor()
    assert doc.privacy_notice_key_reconciliation_finding(repo_root) is None


def test_doctor_surfaces_privacy_ack_finding_for_file_store_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end doctor() run against an in-repo-public (file-store) root — no network
    calls are made, matching R23 file-store parity."""
    doc = _load_doctor()
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    cfg = {
        "planning": {
            "store": {"backend": "in-repo-public"},
            "privacyAck": {"required": True, "recordedAt": None, "reason": "public-origin-remote"},
        }
    }
    (cursor_dir / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def fake_run_json(cmd):
        if "resolve-backend" in cmd:
            return {"verdict": "ok", "backend": "in-repo-public", "effective": "in-repo-public"}
        if "exists" in cmd:
            return {"verdict": "missing"}
        return {"verdict": "ok"}

    monkeypatch.setattr(doc, "run_json", fake_run_json)
    monkeypatch.setattr(doc, "parked_frontier_finding", lambda root: None)
    monkeypatch.setattr(doc, "wave_regression_check", lambda root: None)

    out = doc.doctor(tmp_path, sweep=False)
    checks = {c["check"] for c in out["checks"]}
    assert "privacy-ack-required" in checks
    assert "privacy-ack-required" in out["warnings"]
    assert out["verdict"] == "degraded"
