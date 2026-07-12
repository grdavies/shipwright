"""Unit tests for terminal acceptance + halt-resume (PRD 065 R14–R15, R24–R25, R30)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from halt_resume import (
    build_halt_resume,
    enrich_legitimate_halt,
    validate_halt_resume,
)
from merge_ready_enforcement import seed_mandatory_pass_records
from wave_acceptance import (
    TERMINAL_MERGED_STATUSES,
    build_acceptance_record,
    embed_validated_acceptance,
    validate_acceptance_record,
)


def _seed_phase_gates(repo_root: Path, *slugs: str) -> None:
    for slug in slugs:
        seed_mandatory_pass_records(repo_root, slug)


def _minimal_state(**overrides):
    state = {
        "source_task_list": "docs/prds/065-turn-independent-ship-loop-and-gate-evidence/tasks-065-turn-independent-ship-loop-and-gate-evidence.md",
        "target": {"branch": "feat/turn-independent-ship-loop-and-gate-evidence"},
        "phases": {
            "1": {"slug": "phase-one", "status": "green-merged"},
            "2": {"slug": "phase-two", "status": "teardown-pending"},
        },
        "mergedPhases": [
            {
                "phaseId": "1",
                "phaseSlug": "phase-one",
                "mergeCommit": "a" * 40,
                "mergedAt": "2026-07-12T00:00:00Z",
                "pr": 1,
            },
            {
                "phaseId": "2",
                "phaseSlug": "phase-two",
                "mergeCommit": "b" * 40,
                "mergedAt": "2026-07-12T01:00:00Z",
                "pr": 2,
            },
        ],
        "terminalPr": {"number": 99},
        "legitimateHaltCount": 0,
    }
    state.update(overrides)
    return state


def test_halt_resume_requires_core_fields(repo_root: Path) -> None:
    block = build_halt_resume(repo_root, _minimal_state(), halt_cause="conductor:no-progress")
    ok, errors = validate_halt_resume(block)
    assert ok, errors
    assert block["resumeCommand"].startswith("/sw-deliver run")
    assert block["autonomyDirective"]


def test_halt_resume_missing_field_rejected() -> None:
    ok, errors = validate_halt_resume({"resumeCommand": "/sw-deliver run"})
    assert not ok
    assert any("haltCause" in e for e in errors)


def test_acceptance_teardown_statuses_tolerated(repo_root: Path) -> None:
    _seed_phase_gates(repo_root, "phase-one", "phase-two")
    state = _minimal_state()
    record = build_acceptance_record(
        repo_root,
        state,
        terminal_gate={"verdict": "green"},
        gate_exit_code=0,
    )
    validation = validate_acceptance_record(repo_root, record, state)
    assert validation["verdict"] == "pass"
    statuses = {p["mergeState"] for p in record["phases"]}
    assert statuses <= TERMINAL_MERGED_STATUSES


def test_acceptance_fails_unmerged_phase(repo_root: Path) -> None:
    state = _minimal_state()
    state["phases"]["3"] = {"slug": "phase-three", "status": "pending"}
    record = build_acceptance_record(repo_root, state)
    validation = validate_acceptance_record(repo_root, record, state)
    assert validation["verdict"] == "fail"
    assert any("unmerged" in e for e in validation["errors"])


def test_acceptance_fails_non_green_terminal_gate(repo_root: Path) -> None:
    state = _minimal_state()
    record = build_acceptance_record(
        repo_root,
        state,
        terminal_gate={"verdict": "blocked"},
        gate_exit_code=1,
    )
    validation = validate_acceptance_record(repo_root, record, state)
    assert validation["verdict"] == "fail"
    assert any("terminal-gate" in e for e in validation["errors"])


def test_embed_writes_record(repo_root: Path, tmp_path: Path) -> None:
    _seed_phase_gates(repo_root, "phase-one", "phase-two")
    state = _minimal_state()
    report: dict = {}
    embed_validated_acceptance(
        repo_root,
        state,
        report,
        terminal_gate={"verdict": "green"},
        gate_exit_code=0,
    )
    assert report["terminalAcceptance"]["validation"]["verdict"] == "pass"
    path = Path(report["terminalAcceptancePath"])
    assert path.is_file()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["interactionCount"] == 0


def test_enrich_legitimate_halt_increments_interaction(repo_root: Path) -> None:
    state = _minimal_state()
    payload: dict = {}
    enrich_legitimate_halt(
        payload,
        repo_root,
        state,
        halt_cause="budget:exhausted",
        phase_slug="phase-one",
    )
    assert "haltResume" in payload
    assert state["legitimateHaltCount"] == 1
