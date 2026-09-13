"""Integration tests for capture trigger flow (PRD 350 TS4)."""
from __future__ import annotations

import json
from pathlib import Path

import wave_journal as capture


def _enable(root: Path) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "capture": {
                    "enabled": True,
                    "gapKeywords": ["undocumented"],
                    "maxSummaryLength": 500,
                    "subAgentSidecarEnabled": True,
                    "maxFileSizeBytes": 52_428_800,
                }
            }
        ),
        encoding="utf-8",
    )


def test_synthetic_run_event_sequence(tmp_path: Path) -> None:
    _enable(tmp_path)
    run_id = "deliver-synth-001"
    capture.ensure_capture_files(tmp_path, run_id)

    capture.transition_task_to_in_progress(
        {"id": "2.1", "title": "Wire task_start", "files": ["scripts/wave_journal.py"], "acceptance": "emits event"},
        run_id,
        root=tmp_path,
        phase_id="phase-2",
    )
    capture._emit_milestone(
        "phase_boundary", "phase-2", run_id, "phase_boundary entered", root=tmp_path
    )
    capture._emit_milestone(
        "decision_recorded", "phase-2", run_id, "decision recorded", root=tmp_path
    )
    capture._emit_milestone(
        "blocker_resolved", "phase-2", run_id, "blocker resolved", root=tmp_path
    )
    # Dedup same milestone sub-trigger
    capture._emit_milestone(
        "phase_boundary", "phase-2", run_id, "phase_boundary entered again", root=tmp_path
    )
    eid = capture.emit_discovery(
        "found undocumented helper",
        "phase-2",
        run_id,
        "tool_output",
        "agent:discovery",
        root=tmp_path,
    )
    assert eid
    capture.emit_verification(
        root=tmp_path,
        run_id=run_id,
        phase_id="phase-2",
        outcome="partial",
        evidence="check-a,check-b",
        provenance_ref="check-gate:1",
    )
    capture._emit_blocker(
        "needs-operator",
        {"tasks": [{"id": "2.1", "status": "in-flight"}]},
        "phase-2",
        run_id,
        root=tmp_path,
    )
    capture._emit_delegation(
        "sw-test-runner:run fixtures",
        "phase-2",
        ["scripts/wave_journal.py"],
        run_id,
        root=tmp_path,
    )
    capture._emit_interruption(
        {"tasks": [{"id": "2.1", "status": "in-flight"}]},
        run_id,
        root=tmp_path,
        phase_id="phase-2",
    )

    events = capture.read_events(run_id, root=tmp_path)
    types = [e["eventType"] for e in events]
    assert types[0] == "task_start"
    assert "milestone" in types
    assert "discovery" in types
    assert "verification" in types
    assert "blocker" in types
    assert "delegation" in types
    assert types[-1] == "interruption"
    # phase_boundary deduped to one
    assert sum(1 for e in events if e["eventType"] == "milestone" and "phase_boundary" in e.get("summary", "")) == 1


def test_sub_agent_sidecar_consolidate_roundtrip(tmp_path: Path) -> None:
    _enable(tmp_path)
    run_id = "deliver-synth-002"
    dispatch_id = "dispatch-9"
    capture.ensure_capture_files(tmp_path, run_id)
    event = {
        "eventId": capture.compute_event_id(run_id, "phase-2", "discovery", "2026-09-12T11:00:00Z"),
        "schemaVersion": "1",
        "eventType": "discovery",
        "runId": run_id,
        "phaseId": "phase-2",
        "agentId": "sub-agent",
        "timestamp": "2026-09-12T11:00:00Z",
        "provenanceKind": "sub_agent_feed",
        "provenanceRef": "sidecar",
        "summary": "sidecar discovery",
        "pendingState": None,
    }
    capture.write_sub_agent_event(
        event, root=tmp_path, run_id=run_id, dispatch_id=dispatch_id
    )
    n1 = capture.consolidate_sub_agent_events(run_id, dispatch_id, root=tmp_path)
    n2 = capture.consolidate_sub_agent_events(run_id, dispatch_id, root=tmp_path)
    assert n1 == 1
    assert n2 == 0
    events = capture.read_events(run_id, root=tmp_path, event_types=["discovery"])
    assert len(events) == 1


def test_interruption_is_last_before_pause(tmp_path: Path) -> None:
    _enable(tmp_path)
    run_id = "deliver-synth-003"
    capture.ensure_capture_files(tmp_path, run_id)
    capture._emit_task_start(
        {"id": "t1", "title": "task"}, run_id, root=tmp_path, phase_id="phase-2"
    )
    capture._emit_interruption(None, run_id, root=tmp_path)
    events = capture.read_events(run_id, root=tmp_path)
    assert events[-1]["eventType"] == "interruption"
