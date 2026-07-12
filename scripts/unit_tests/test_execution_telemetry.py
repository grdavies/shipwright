"""Unit tests for execution_telemetry_lib (PRD 064 R29/R30)."""
from __future__ import annotations

from pathlib import Path

import execution_telemetry_lib as lib


def test_record_pass_persists_metrics(tmp_path: Path):
    result = lib.record_pass(
        tmp_path,
        command="sw-execute",
        phase_slug="demo-phase",
        run_dir=tmp_path / "run",
        iteration_count=2,
        blocker_ledger_size=3,
        time_to_green_ms=120000,
        rca_triggered_count=1,
        green=True,
    )
    assert result["verdict"] == "ok"
    path = Path(result["path"])
    assert path.is_file()
    passes = lib.load_passes(path)
    assert len(passes) == 1
    metrics = passes[0]["metrics"]
    assert metrics["iterationCount"] == 2
    assert metrics["blockerLedgerSize"] == 3
    assert metrics["timeToGreenMs"] == 120000
    assert metrics["rcaTriggeredCount"] == 1
    assert metrics["green"] is True


def test_missing_signals_tolerated(tmp_path: Path):
    record = lib.build_pass_record(
        command="sw-stabilize",
        phase_slug="demo-phase",
        iteration_count=None,
        blocker_ledger_size=1,
        time_to_green_ms=None,
        rca_triggered_count=None,
        green=False,
    )
    assert "iterationCount" in record["missingSignals"]
    assert "timeToGreenMs" in record["missingSignals"]
    assert record["metrics"]["blockerLedgerSize"] == 1


def test_no_telemetry_yields_no_suggestion(tmp_path: Path):
    result = lib.draft_authoring_suggestion(
        tmp_path,
        phase_slug="demo-phase",
        run_dir=tmp_path / "run",
        persist=False,
    )
    assert result["verdict"] == "no-telemetry"
    assert result["autoApply"] is False
    assert result["suggestion"] is None


def test_one_pass_drafts_advisory_suggestion(tmp_path: Path):
    lib.record_pass(
        tmp_path,
        command="sw-execute",
        phase_slug="demo-phase",
        run_dir=tmp_path / "run",
        iteration_count=4,
        blocker_ledger_size=5,
        time_to_green_ms=700000,
        rca_triggered_count=2,
        green=True,
    )
    result = lib.draft_authoring_suggestion(
        tmp_path,
        phase_slug="demo-phase",
        run_dir=tmp_path / "run",
        persist=True,
    )
    assert result["verdict"] == "advisory"
    assert result["autoApply"] is False
    assert result["binding"] is False
    assert result["suggestion"]["category"] == "phase-authoring-improvement"
    assert len(result["suggestion"]["recommendations"]) >= 1
    assert Path(result["path"]).is_file()


def test_cadence_defers_until_every_n_runs(tmp_path: Path):
    run_dir = tmp_path / "run"
    for idx in range(2, 5):
        lib.record_pass(
            tmp_path,
            command="sw-stabilize",
            phase_slug="demo-phase",
            run_dir=run_dir,
            iteration_count=idx,
            blocker_ledger_size=1,
            time_to_green_ms=1000,
            rca_triggered_count=0,
            green=False,
        )
    result = lib.draft_authoring_suggestion(
        tmp_path,
        phase_slug="demo-phase",
        run_dir=run_dir,
        persist=False,
    )
    assert result["verdict"] == "deferred"
