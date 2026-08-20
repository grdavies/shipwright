"""Unit tests for repro-first debug gate (PRD 323 phase 1)."""
from __future__ import annotations

import json
from pathlib import Path

import debug_repro_gate as gate


def test_dev_time_pass_when_repro_confirmed() -> None:
    signal = {"type": "test_failure", "reproCommand": "pytest tests/foo.py::test_bar"}
    state = {
        "repro": {
            "reproCommand": "pytest tests/foo.py::test_bar",
            "reproConfirmed": True,
            "reproOutputDigest": "abc123",
        },
        "mechanicalRepro": {"repro_command": "complete"},
    }
    result = gate.evaluate_dev_time(signal, state)
    assert result["verdict"] == "pass"
    assert result["path"] == "mechanical-repro"
    assert result["repro"]["reproConfirmed"] is True


def test_dev_time_blocked_pending_mechanical_repro() -> None:
    signal = {"type": "build_failure", "reproCommand": "npm run build"}
    state = {"mechanicalRepro": {"repro_command": "pending"}}
    result = gate.evaluate_dev_time(signal, state, signal_path="signal.json", state_path="state.json")
    assert result["verdict"] == "blocked"
    assert result["cause"] == "repro-pending"
    assert "repro_command" in result["pending"]
    assert result["resumeCommand"].startswith("python3 scripts/debug_repro_gate.py run")
    assert gate.exit_code_for_verdict(result["verdict"]) == 20


def test_production_pass_with_evidence_bundle() -> None:
    signal = {"type": "sentry", "issueId": "PROJECT-123"}
    state = {
        "evidenceAcquisition": {
            "logs": "complete",
            "traces": "complete",
            "sentry_enrich": "complete",
        },
        "evidenceBundle": {
            "signalClass": "production",
            "artifactPaths": ["/tmp/redacted/logs.txt"],
            "complete": True,
            "checklistState": {
                "logs": "complete",
                "traces": "complete",
                "sentry_enrich": "complete",
            },
        },
    }
    result = gate.evaluate_production(signal, state)
    assert result["verdict"] == "pass"
    assert result["evidenceBundle"]["complete"] is True
    assert result["evidenceBundle"]["signalClass"] == "production"
    assert gate.exit_code_for_verdict(result["verdict"]) == 0


def test_production_blocked_with_pending_evidence() -> None:
    signal = {"type": "deploy_log", "source": "vercel", "excerpt": "redacted"}
    state = {
        "evidenceAcquisition": {"logs": "complete", "traces": "pending"},
    }
    result = gate.evaluate_production(signal, state, signal_path="signal.json")
    assert result["verdict"] == "blocked"
    assert result["cause"] == "evidence-pending"
    assert "traces" in result["pending"]
    assert "evidenceBundle" in result
    assert result["evidenceBundle"]["artifactPaths"] == []


def test_production_exhausted_when_required_items_failed() -> None:
    signal = {"type": "user_report", "description": "checkout fails"}
    state = {
        "evidenceAcquisition": {
            "logs": "failed",
            "traces": "failed",
            "sentry_enrich": "skipped",
        }
    }
    result = gate.evaluate_production(signal, state)
    assert result["verdict"] == "exhausted"
    assert result["cause"] == "evidence-exhausted"
    assert "resumeCommand" in result


def test_hypothesis_refused_while_gate_blocked() -> None:
    signal = {"type": "verify_failure"}
    state = {}
    result = gate.evaluate_gate(signal, state, hypotheses=[{"id": "h1", "summary": "guess"}])
    assert result["verdict"] == "blocked"
    assert result["hypothesisGate"] == "refused"
    assert result["cause"] == "hypothesis-before-gate"


def test_checklist_metadata_for_production() -> None:
    meta = gate.checklist_metadata(signal_class_name="production")
    assert meta["signalClass"] == "production"
    ids = [item["id"] for item in meta["checklist"]]
    assert ids == ["logs", "traces", "replay_bundle", "sentry_enrich"]
    assert "signalClass" in meta["evidenceBundleFields"]


def test_cli_run_writes_out(tmp_path: Path, monkeypatch) -> None:
    signal_path = tmp_path / "signal.json"
    state_path = tmp_path / "state.json"
    out_path = tmp_path / "gate.status.json"
    signal_path.write_text(
        json.dumps({"type": "test_failure", "reproCommand": "pytest -q"}),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "repro": {"reproCommand": "pytest -q", "reproConfirmed": True},
                "mechanicalRepro": {"repro_command": "complete"},
            }
        ),
        encoding="utf-8",
    )
    argv = [
        "run",
        "--signal",
        str(signal_path),
        "--state",
        str(state_path),
        "--out",
        str(out_path),
    ]
    with monkeypatch.context() as ctx:
        ctx.setattr(gate, "emit", lambda obj, code=0: (_ for _ in ()).throw(SystemExit(code)))
        try:
            gate.main(argv)
        except SystemExit as exc:
            assert exc.code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"
