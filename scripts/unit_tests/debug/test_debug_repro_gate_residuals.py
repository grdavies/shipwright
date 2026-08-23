"""Residual hardening tests for repro-first debug gate (PRD 326 phase 2 / gap 322)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import debug_repro_gate as gate  # noqa: E402
import test_debug_repro_gate as prd323_cases  # noqa: E402

_SECRET_SAMPLE = "ghp_" + "A" * 36


def test_normalize_repro_text_strips_trailing_whitespace() -> None:
    raw = "line one   \nline two\t  \n"
    assert gate.normalize_repro_text(raw) == "line one\nline two"


def test_compute_repro_signature_is_deterministic_across_machine_contexts() -> None:
    machine_a = (
        "Error at 2026-03-15T10:30:45Z in /Users/foo/.sw-worktrees/wt-1/scripts/x.py "
        "pid=12345 port 8080   \n"
    )
    machine_b = (
        "Error at 2026-08-22T14:00:00.123Z in /Volumes/External/foo/.sw-worktrees/wt-2/scripts/x.py "
        "pid=99999 port 3000\n"
    )
    sig_a = gate.compute_repro_signature(machine_a)
    sig_b = gate.compute_repro_signature(machine_b)
    assert sig_a == sig_b
    assert len(sig_a) == 64


def test_compute_repro_signature_empty_payload_raises() -> None:
    with pytest.raises(gate.ReproUnverifiedError):
        gate.compute_repro_signature("   ")


def test_verify_repro_payload_empty_emits_repro_unverified() -> None:
    signal = {"type": "test_failure"}
    state = {"repro": {"verifySignature": True, "reproOutput": ""}}
    result = gate.evaluate_gate(signal, state)
    assert result["verdict"] == "fail"
    assert result["reason"] == "repro-unverified"
    assert result["signal"]["type"] == "test_failure"
    assert gate.exit_code_for_verdict(result["verdict"]) == 20


def test_persist_repro_record_redacts_before_write(tmp_path: Path) -> None:
    signal = {"type": "test_failure"}
    repro = {
        "reproCommand": f"pytest -q --token {_SECRET_SAMPLE}",
        "reproConfirmed": True,
        "reproOutput": "FAILED tests/foo.py::test_bar",
    }
    out = tmp_path / "repro-record.json"
    gate.persist_repro_record(repro, signal, out)
    payload = out.read_text(encoding="utf-8")
    assert _SECRET_SAMPLE not in payload
    assert "[REDACTED" in payload
    assert "reproOutput" not in payload
    assert "transcript" not in payload
    record = json.loads(payload)
    assert record["reproSignature"]


def test_persist_repro_record_refuses_forbidden_transcript_field(tmp_path: Path) -> None:
    signal = {"type": "test_failure"}
    repro = {
        "reproOutput": "AssertionError: boom",
        "transcript": "raw agent transcript must not persist",
    }
    with pytest.raises(gate.RedactionRefusedError):
        gate.persist_repro_record(repro, signal, tmp_path / "repro-record.json")


def test_persist_repro_record_redaction_refusal_blocks_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import memory_redact

    def _fail(_text: str, *, destination: str) -> str:
        raise memory_redact.RedactionError("residual:GITHUB_PAT", detector="GITHUB_PAT")

    monkeypatch.setattr(memory_redact, "redact", _fail)
    signal = {"type": "test_failure"}
    repro = {"reproOutput": "AssertionError: boom"}
    with pytest.raises(gate.RedactionRefusedError):
        gate.persist_repro_record(repro, signal, tmp_path / "repro-record.json")
    assert not (tmp_path / "repro-record.json").exists()


def test_persisted_repro_record_round_trips_signature(tmp_path: Path) -> None:
    signal = {"type": "verify_failure", "reproCommand": "npm test"}
    repro = {
        "reproCommand": "npm test",
        "reproConfirmed": True,
        "reproOutput": "FAIL at 2026-01-01T00:00:00Z pid=42 port 9000",
    }
    out = tmp_path / "repro-record.json"
    gate.persist_repro_record(repro, signal, out)
    record = json.loads(out.read_text(encoding="utf-8"))
    expected = gate.compute_repro_signature(repro["reproOutput"])
    assert record["reproSignature"] == expected


def test_prd323_gate_cases_remain_unchanged() -> None:
    """No-regression guard against scripts/unit_tests/debug/test_debug_repro_gate.py."""
    prd323_cases.test_dev_time_pass_when_repro_confirmed()
    prd323_cases.test_dev_time_blocked_pending_mechanical_repro()
    prd323_cases.test_production_pass_with_evidence_bundle()
    prd323_cases.test_production_blocked_with_pending_evidence()
    prd323_cases.test_production_exhausted_when_required_items_failed()
    prd323_cases.test_hypothesis_refused_while_gate_blocked()
    prd323_cases.test_checklist_metadata_for_production()
