"""PRD 349 R11–R14: shipwright_paths + handoff reader migration tests."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO_ROOT))

from shipwright_paths import (  # noqa: E402
    STATE_ROOT_LEGACY_CURSOR,
    STATE_ROOT_PRIMARY,
    AllowlistMissingError,
    allowlist_path,
    gate_evidence_path,
    phase_evidence_path,
    require_allowlist_path,
)
from core.handoff import readers  # noqa: E402

ALLOWLIST_BODY = {"rules": ["mock-realism", "sw-guardrails"]}
GATE_BODY = {"verdict": "pass", "gateId": "checks-gate"}
PHASE_BODY = {"phase": "execute", "note": "ok"}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_allowlist_path_neutral_only(tmp_path: Path) -> None:
    neutral = tmp_path / STATE_ROOT_PRIMARY / "memory" / "rule-allowlist.json"
    _write(neutral, ALLOWLIST_BODY)
    assert allowlist_path(tmp_path) == neutral
    assert require_allowlist_path(tmp_path) == neutral


def test_allowlist_path_legacy_only(tmp_path: Path) -> None:
    legacy = tmp_path / STATE_ROOT_LEGACY_CURSOR / "sw-memory-rule-allowlist.json"
    _write(legacy, ALLOWLIST_BODY)
    assert allowlist_path(tmp_path) == legacy


def test_allowlist_path_prefers_neutral_when_both(tmp_path: Path) -> None:
    neutral = tmp_path / STATE_ROOT_PRIMARY / "memory" / "rule-allowlist.json"
    legacy = tmp_path / STATE_ROOT_LEGACY_CURSOR / "sw-memory-rule-allowlist.json"
    _write(neutral, {"rules": ["neutral"]})
    _write(legacy, {"rules": ["legacy"]})
    assert allowlist_path(tmp_path) == neutral


def test_allowlist_path_neither_raises(tmp_path: Path) -> None:
    with pytest.raises(AllowlistMissingError):
        require_allowlist_path(tmp_path)


def test_gate_and_phase_evidence_layouts(tmp_path: Path) -> None:
    run_id = "phase-a"
    neutral_gate = (
        tmp_path / STATE_ROOT_PRIMARY / "deliver-runs" / run_id / "gate-evidence"
    )
    _write(neutral_gate / "checks-gate.status.json", GATE_BODY)
    assert gate_evidence_path(tmp_path, run_id) == neutral_gate

    root2 = tmp_path / "legacy-only"
    legacy_gate = (
        root2
        / STATE_ROOT_LEGACY_CURSOR
        / "sw-deliver-runs"
        / run_id
        / "gate-evidence"
    )
    _write(legacy_gate / "checks-gate.status.json", GATE_BODY)
    assert gate_evidence_path(root2, run_id) == legacy_gate

    phase = "execute"
    neutral_phase = (
        tmp_path
        / STATE_ROOT_PRIMARY
        / "deliver-runs"
        / run_id
        / "phase-evidence"
        / phase
    )
    _write(neutral_phase / "note.json", PHASE_BODY)
    assert phase_evidence_path(tmp_path, run_id, phase) == neutral_phase


def _seed_layout(root: Path, *, legacy: bool) -> None:
    if legacy:
        base = root / STATE_ROOT_LEGACY_CURSOR
        allow = base / "sw-memory-rule-allowlist.json"
        gate = base / "sw-deliver-runs" / "run-1" / "gate-evidence"
        phase = base / "sw-deliver-runs" / "run-1" / "phase-evidence" / "execute"
        status = base / "sw-deliver-runs" / "run-1" / "status.json"
    else:
        base = root / STATE_ROOT_PRIMARY
        allow = base / "memory" / "rule-allowlist.json"
        gate = base / "deliver-runs" / "run-1" / "gate-evidence"
        phase = base / "deliver-runs" / "run-1" / "phase-evidence" / "execute"
        status = base / "deliver-runs" / "run-1" / "status.json"
    _write(allow, ALLOWLIST_BODY)
    _write(gate / "checks-gate.status.json", GATE_BODY)
    _write(phase / "note.json", PHASE_BODY)
    _write(status, {"phase": "execute", "verdict": "pass"})


def test_handoff_readers_migration_consistency(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    _seed_layout(legacy_root, legacy=True)

    before_rules = readers.read_allowlist_rules(legacy_root)
    before_gate = readers.read_gate_evidence(legacy_root, "run-1")
    before_phase = readers.read_phase_evidence(legacy_root, "run-1", "execute")
    before_status = readers.read_deliver_status(legacy_root, "run-1")

    assert before_rules
    assert before_gate
    assert before_phase
    assert before_status

    migrated = tmp_path / "migrated"
    _seed_layout(migrated, legacy=True)
    src_allow = migrated / STATE_ROOT_LEGACY_CURSOR / "sw-memory-rule-allowlist.json"
    dst_allow = migrated / STATE_ROOT_PRIMARY / "memory" / "rule-allowlist.json"
    dst_allow.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_allow), str(dst_allow))
    src_run = migrated / STATE_ROOT_LEGACY_CURSOR / "sw-deliver-runs" / "run-1"
    dst_run = migrated / STATE_ROOT_PRIMARY / "deliver-runs" / "run-1"
    dst_run.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_run), str(dst_run))

    after_rules = readers.read_allowlist_rules(migrated)
    after_gate = readers.read_gate_evidence(migrated, "run-1")
    after_phase = readers.read_phase_evidence(migrated, "run-1", "execute")
    after_status = readers.read_deliver_status(migrated, "run-1")

    assert after_rules == before_rules
    assert [row["gateId"] for row in after_gate] == [row["gateId"] for row in before_gate]
    assert after_phase
    assert after_status == before_status
    assert after_rules != []
    assert after_gate != []


def test_r11_no_cursor_string_literal_in_path_library() -> None:
    text = (SCRIPTS / "shipwright_paths.py").read_text(encoding="utf-8")
    assert '".cursor"' not in text
    assert "'.cursor'" not in text
