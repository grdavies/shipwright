"""Unit tests for wave_journal capture write/read APIs (PRD 350 TS1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _sw.capture_schema_lib import (
    CaptureSchemaError,
    compute_event_id,
    validate_event,
)
from wave_journal import (
    CaptureStorageError,
    consolidate_sub_agent_events,
    ensure_capture_files,
    read_events,
    record_event,
    sub_agent_events_path,
)
from wave_run_paths import events_path


def _write_enabled_config(root: Path, *, enabled: bool = True, max_bytes: int = 52_428_800) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "capture": {
                    "enabled": enabled,
                    "gapKeywords": ["undocumented"],
                    "maxSummaryLength": 500,
                    "subAgentSidecarEnabled": True,
                    "maxFileSizeBytes": max_bytes,
                }
            }
        ),
        encoding="utf-8",
    )


def _event(
    *,
    run_id: str,
    phase_id: str = "phase-1",
    event_type: str = "task_start",
    timestamp: str = "2026-09-12T12:00:00Z",
    agent_id: str = "agent-1",
    summary: str = "test event",
    **extra: object,
) -> dict:
    event = {
        "eventId": compute_event_id(run_id, phase_id, event_type, timestamp),
        "schemaVersion": "1",
        "eventType": event_type,
        "runId": run_id,
        "phaseId": phase_id,
        "agentId": agent_id,
        "timestamp": timestamp,
        "provenanceKind": "tool_output",
        "provenanceRef": "tool-1",
        "summary": summary,
        "pendingState": None,
    }
    event.update(extra)
    validate_event(event)
    return event


def test_ensure_capture_files_creates_empty_journals(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=False)
    paths = ensure_capture_files(tmp_path, "run-init")
    assert paths["events"].is_file()
    assert paths["errors"].is_file()
    assert paths["events"].read_text(encoding="utf-8") == ""
    # Resume leaves content intact.
    paths["events"].write_text("{}\n", encoding="utf-8")
    ensure_capture_files(tmp_path, "run-init")
    assert paths["events"].read_text(encoding="utf-8") == "{}\n"


def test_record_event_noop_when_disabled(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=False)
    run_id = "run-disabled"
    ensure_capture_files(tmp_path, run_id)
    record_event(_event(run_id=run_id), run_id=run_id, root=tmp_path)
    assert events_path(tmp_path, run_id).read_text(encoding="utf-8") == ""


def test_record_event_appends_valid_event(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=True)
    run_id = "run-ok"
    event = _event(run_id=run_id)
    record_event(event, run_id=run_id, root=tmp_path)
    lines = events_path(tmp_path, run_id).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["eventId"] == event["eventId"]


def test_schema_violation_logs_and_raises(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=True)
    run_id = "run-bad"
    ensure_capture_files(tmp_path, run_id)
    bad = _event(run_id=run_id)
    del bad["summary"]
    with pytest.raises(CaptureSchemaError):
        record_event(bad, run_id=run_id, root=tmp_path)
    errors = (tmp_path / ".cursor" / "sw-deliver-runs" / run_id / "capture-errors.jsonl").read_text(
        encoding="utf-8"
    )
    assert "CaptureSchemaError" in errors
    assert events_path(tmp_path, run_id).read_text(encoding="utf-8") == ""


def test_duplicate_event_id_first_write_wins(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=True)
    run_id = "run-dedup"
    first = _event(run_id=run_id, summary="first")
    second = dict(first)
    second["summary"] = "second-should-not-write"
    # Same eventId (composite key unchanged).
    record_event(first, run_id=run_id, root=tmp_path)
    record_event(second, run_id=run_id, root=tmp_path)
    lines = events_path(tmp_path, run_id).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["summary"] == "first"
    errors = (
        tmp_path / ".cursor" / "sw-deliver-runs" / run_id / "capture-errors.jsonl"
    ).read_text(encoding="utf-8")
    assert "duplicate_event_id" in errors
    assert "duplicate_skipped" in errors


def test_storage_limit_raises_and_logs(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=True, max_bytes=64)
    run_id = "run-limit"
    ensure_capture_files(tmp_path, run_id)
    # Pre-fill near limit.
    events_path(tmp_path, run_id).write_bytes(b"x" * 60)
    with pytest.raises(CaptureStorageError):
        record_event(_event(run_id=run_id), run_id=run_id, root=tmp_path)
    errors = (tmp_path / ".cursor" / "sw-deliver-runs" / run_id / "capture-errors.jsonl").read_text(
        encoding="utf-8"
    )
    assert "CaptureStorageError" in errors


def test_consolidate_sub_agent_events_idempotent(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=True)
    run_id = "run-sidecar"
    dispatch_id = "dispatch-1"
    event = _event(run_id=run_id, event_type="discovery", timestamp="2026-09-12T13:00:00Z")
    sidecar = sub_agent_events_path(tmp_path, run_id, dispatch_id)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(event) + "\n", encoding="utf-8")

    assert consolidate_sub_agent_events(run_id, dispatch_id, root=tmp_path) == 1
    assert consolidate_sub_agent_events(run_id, dispatch_id, root=tmp_path) == 0
    lines = events_path(tmp_path, run_id).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_consolidate_missing_sidecar_returns_zero(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=True)
    assert consolidate_sub_agent_events("run-missing", "nope", root=tmp_path) == 0


def test_read_events_filters(tmp_path: Path) -> None:
    _write_enabled_config(tmp_path, enabled=True)
    run_id = "run-read"
    events = [
        _event(
            run_id=run_id,
            event_type="task_start",
            timestamp="2026-09-12T12:00:00Z",
            phase_id="p1",
            summary="a",
        ),
        _event(
            run_id=run_id,
            event_type="discovery",
            timestamp="2026-09-12T12:10:00Z",
            phase_id="p1",
            summary="b",
        ),
        _event(
            run_id=run_id,
            event_type="blocker",
            timestamp="2026-09-12T12:20:00Z",
            phase_id="p2",
            summary="c",
            blockerCondition="need-input",
        ),
    ]
    for event in events:
        record_event(event, run_id=run_id, root=tmp_path)

    by_type = read_events(run_id, event_types=["discovery"], root=tmp_path)
    assert [e["summary"] for e in by_type] == ["b"]

    by_phase = read_events(run_id, phase_id="p2", root=tmp_path)
    assert [e["summary"] for e in by_phase] == ["c"]

    by_time = read_events(
        run_id,
        after="2026-09-12T12:05:00Z",
        before="2026-09-12T12:15:00Z",
        root=tmp_path,
    )
    assert [e["summary"] for e in by_time] == ["b"]


def test_prd352_r13_same_second_emit_discovery_both_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRD 352 R13 — two same-second emit_discovery calls must both persist.

    Current compute_event_id is second-granular, so same-second discoveries
    collide and first-write-wins drops the second. Expected red until R10.
    """
    from wave_journal import emit_discovery, read_events, ensure_capture_files

    _write_enabled_config(tmp_path, enabled=True)
    run_id = "run-collision"
    ensure_capture_files(tmp_path, run_id)
    frozen = "2026-09-14T04:00:00Z"
    monkeypatch.setattr("wave_journal._utc_now", lambda: frozen)

    first = emit_discovery(
        "first discovery",
        "phase-1",
        run_id,
        "tool_output",
        "tool-a",
        root=tmp_path,
    )
    second = emit_discovery(
        "second discovery",
        "phase-1",
        run_id,
        "tool_output",
        "tool-b",
        root=tmp_path,
    )
    events = read_events(run_id, event_types=["discovery"], root=tmp_path)
    summaries = {e.get("summary") for e in events}
    assert first != second, "same-second discoveries must receive distinct eventIds"
    assert summaries == {"first discovery", "second discovery"}
    assert len(events) == 2
