"""PRD 337 R8 — terminal acceptance record + standardized halt payloads."""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import wave_terminal as wt  # noqa: E402
from halt_resume import validate_halt_resume  # noqa: E402
from merge_ready_enforcement import seed_mandatory_pass_records  # noqa: E402
from wave_acceptance import build_acceptance_record, validate_acceptance_record  # noqa: E402


@pytest.fixture(autouse=True)
def shipwright_scripts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(SCRIPT_DIR.resolve()))
    monkeypatch.delenv("SW_DELIVER_RUN_ID", raising=False)
    monkeypatch.delenv("SW_RUN_ID", raising=False)
    monkeypatch.setattr(
        "wave_failure.resume_deliver_command",
        lambda _root, _state: (
            "/sw-deliver run "
            "docs/prds/337-workflow-runtime-autonomy-lifecycle/"
            "tasks-337-workflow-runtime-autonomy-lifecycle.md"
        ),
    )


def _deliver_state(**overrides) -> dict:
    state = {
        "runId": "deliver-test-terminal-acceptance",
        "source_task_list": (
            "docs/prds/337-workflow-runtime-autonomy-lifecycle/"
            "tasks-337-workflow-runtime-autonomy-lifecycle.md"
        ),
        "target": {"branch": "feat/workflow-runtime-autonomy-lifecycle", "type": "feat"},
        "phases": {
            "1": {"slug": "phase-one", "status": "green-merged"},
            "2": {"slug": "phase-two", "status": "green-merged"},
        },
        "mergedPhases": [
            {
                "phaseId": "1",
                "phaseSlug": "phase-one",
                "mergeCommit": "a" * 40,
                "mergedAt": "2026-08-30T00:00:00Z",
                "pr": 101,
            },
            {
                "phaseId": "2",
                "phaseSlug": "phase-two",
                "mergeCommit": "b" * 40,
                "mergedAt": "2026-08-30T01:00:00Z",
                "pr": 102,
            },
        ],
        "terminalPr": {"number": 999, "url": "https://example.test/pull/999"},
        "legitimateHaltCount": 0,
    }
    state.update(overrides)
    return state


def _seed_phase_gates(repo_root: Path) -> None:
    seed_mandatory_pass_records(repo_root, "phase-one")
    seed_mandatory_pass_records(repo_root, "phase-two")


def test_acceptance_schema_rejects_missing_ledger_fields() -> None:
    ok, errors = wt.validate_acceptance_schema({})
    assert not ok
    assert any("missing-schemaVersion" in e for e in errors)
    assert any("missing-gatesRunRollup" in e for e in errors)


def test_terminal_acceptance_record_complete(repo_root: Path) -> None:
    """I/S — green terminal gate emits validated acceptance with gates-run ledger."""
    _seed_phase_gates(repo_root)
    state = _deliver_state()
    gate = {"verdict": "green", "head": "c" * 40}
    record = build_acceptance_record(
        repo_root,
        state,
        terminal_gate=gate,
        gate_exit_code=0,
    )
    ok, schema_errors = wt.validate_acceptance_schema(record)
    assert ok, schema_errors
    validation = validate_acceptance_record(repo_root, record, state)
    assert validation["verdict"] == "pass"
    assert record["terminalPr"]["number"] == 999
    assert record["gatesRunRollup"]["phases"]["phase-one"]["verdict"] == "pass"


def test_terminal_pr_gate_green_persists_acceptance(repo_root: Path) -> None:
    _seed_phase_gates(repo_root)
    state = _deliver_state()
    gate = {"verdict": "green", "head": "d" * 40}

    with (
        patch.object(wt, "load_state", return_value=state),
        patch.object(wt, "run_docs_currency_gate"),
        patch.object(wt, "run_check_gate", return_value=(0, gate)),
        patch.object(wt, "save_state"),
        pytest.raises(wt.TerminalExit) as excinfo,
    ):
        with wt.terminal_root_context(repo_root), wt.terminal_library_mode():
            wt.cmd_terminal_pr_gate(repo_root, [])

    payload = excinfo.value.outcome.payload
    assert payload["verdict"] == "pass"
    assert payload["terminalAcceptance"]["validation"]["verdict"] == "pass"
    path = Path(payload["terminalAcceptancePath"])
    assert path.is_file()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    ok, errors = wt.validate_acceptance_schema(persisted)
    assert ok, errors


def test_ack_check_halt_emits_stable_resume_command(repo_root: Path) -> None:
    state = _deliver_state()
    state["ackPending"] = True
    with ExitStack() as stack:
        stack.enter_context(patch.object(wt, "load_state", return_value=state))
        stack.enter_context(patch.object(wt, "phase_ack_cadence", return_value=1))
        stack.enter_context(patch.object(wt, "save_state"))
        with wt.terminal_root_context(repo_root), wt.terminal_library_mode():
            with pytest.raises(wt.TerminalExit) as excinfo:
                wt.cmd_ack_check(repo_root, [])
    _assert_halt_resume(excinfo.value.outcome.payload, "need-ack", state)


def test_terminal_checkpoint_halt_emits_stable_resume_command(repo_root: Path) -> None:
    state = _deliver_state()
    with ExitStack() as stack:
        stack.enter_context(patch.object(wt, "load_state", return_value=state))
        stack.enter_context(patch.object(wt, "all_phases_green", return_value=True))
        stack.enter_context(patch.object(wt, "terminal_autonomy_mode", return_value="supervised"))
        stack.enter_context(patch.object(wt, "has_flag", return_value=False))
        stack.enter_context(patch.object(wt, "save_state"))
        with wt.terminal_root_context(repo_root), wt.terminal_library_mode():
            with pytest.raises(wt.TerminalExit) as excinfo:
                wt.cmd_terminal_checkpoint(repo_root, [])
    _assert_halt_resume(excinfo.value.outcome.payload, "supervised-checkpoint", state)


def _assert_halt_resume(payload: dict, expected_cause: str, state: dict) -> None:
    assert payload["verdict"] == "halt"
    assert payload.get("halt") == expected_cause
    halt = payload["haltResume"]
    ok, errors = validate_halt_resume(halt)
    assert ok, errors
    assert halt["haltCause"] == expected_cause
    assert halt["resumeCommand"].startswith("/sw-deliver run")
    assert halt["runId"] == state["runId"]


def test_fail_paths_include_halt_resume(repo_root: Path) -> None:
    state = _deliver_state()
    with (
        patch.object(wt, "load_state", return_value=state),
        pytest.raises(wt.TerminalExit) as excinfo,
    ):
        with wt.terminal_root_context(repo_root), wt.terminal_library_mode():
            wt.fail(
                "terminal merge unverified",
                exit_code=10,
                halt="finalize:merge-unverified",
            )

    payload = excinfo.value.outcome.payload
    assert payload["verdict"] == "fail"
    halt = payload["haltResume"]
    ok, errors = validate_halt_resume(halt)
    assert ok, errors
    assert halt["haltCause"] == "finalize:merge-unverified"
    assert halt["resumeCommand"].startswith("/sw-deliver run")
