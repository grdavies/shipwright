"""Unit tests for wave_journal capture API (PRD 350 TS1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _sw.capture_schema_lib import (
    CaptureSchemaError,
    compute_event_id,
)
from wave_journal import (
    CaptureStorageError,
    consolidate_sub_agent_events,
    ensure_capture_files,
    read_events,
    record_event,
    sub_agent_events_path,
)


def _enable_capture(root: Path, **extra) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "capture": {
            "enabled": True,
            "maxFileSizeBytes": extra.get("maxFileSizeBytes", 52_428_800),
            "maxSummaryLength": 500,
            "subAgentSidecarEnabled": True,
            "gapKeywords": ["gap identified"],
        }
    }
    # Prefer legacy candidate path that load_workflow_config resolves.
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _event(run_id: str, event_type: str = "task_start", **overrides) -> dict:
    ts = overrides.pop("timestamp", "2026-09-12T21:00:00Z")
    phase_id = overrides.pop("phaseId", "1")
    base = {
        "eventId": compute_event_id(run_id, phase_id, event_type, ts),
        "schemaVersion": "1",
        "eventType": event_type,
        "runId": run_id,
        "phaseId": phase_id,
        "agentId": "agent-a",
        "timestamp": ts,
        "provenanceKind": "tool_output",
        "provenanceRef": "tool:test",
        "summary": f"{event_type}: ok",
        "pendingState": None,
    }
    base.update(overrides)
    if "eventId" not in overrides:
        base["eventId"] = compute_event_id(
            base["runId"], base["phaseId"], base["eventType"], base["timestamp"]
        )
    return base


def test_record_event_appends_valid_event(tmp_path: Path) -> None:
    _enable_capture(tmp_path)
    run_id = "deliver-test-1"
    ensure_capture_files(tmp_path, run_id)
    record_event(_event(run_id), run_id=run_id, root=tmp_path)
    rows = read_events(run_id, root=tmp_path)
    assert len(rows) == 1
    assert rows[0]["eventType"] == "task_start"


def test_schema_violation_logs_error_and_raises(tmp_path: Path) -> None:
    _enable_capture(tmp_path)
    run_id = "deliver-test-2"
    ensure_capture_files(tmp_path, run_id)
    bad = _event(run_id)
    del bad["summary"]
    with pytest.raises(CaptureSchemaError):
        record_event(bad, run_id=run_id, root=tmp_path)
    err = (tmp_path / ".cursor" / "sw-deliver-runs" / run_id / "capture-errors.jsonl")
    # path may use shipwright primary state root — locate via ensure return
    from wave_journal import capture_errors_path

    err_path = capture_errors_path(tmp_path, run_id)
    assert err_path.is_file()
    assert "CaptureSchemaError" in err_path.read_text(encoding="utf-8")


def test_duplicate_event_id_first_write_wins(tmp_path: Path) -> None:
    _enable_capture(tmp_path)
    run_id = "deliver-test-3"
    ensure_capture_files(tmp_path, run_id)
    first = _event(run_id, summary="task: first")
    second = dict(first)
    second["summary"] = "task: second"
    record_event(first, run_id=run_id, root=tmp_path)
    record_event(second, run_id=run_id, root=tmp_path)
    rows = read_events(run_id, root=tmp_path)
    assert len(rows) == 1
    assert rows[0]["summary"] == "task: first"


def test_storage_limit_raises(tmp_path: Path) -> None:
    _enable_capture(tmp_path, maxFileSizeBytes=64)
    run_id = "deliver-test-4"
    paths = ensure_capture_files(tmp_path, run_id)
    # Pre-fill events.jsonl near the limit so the next append trips storage.
    events_path = paths["events"]
    events_path.write_text('{"eventId":"prefill"}\n', encoding="utf-8")
    # Pad without credential-like tokens.
    events_path.write_bytes(events_path.read_bytes() + (b"#" * 40))
    with pytest.raises(CaptureStorageError):
        record_event(_event(run_id, summary="task: pad"), run_id=run_id, root=tmp_path)


def test_read_events_filters(tmp_path: Path) -> None:
    _enable_capture(tmp_path)
    run_id = "deliver-test-5"
    ensure_capture_files(tmp_path, run_id)
    record_event(
        _event(run_id, "task_start", timestamp="2026-09-12T21:00:00Z"),
        run_id=run_id,
        root=tmp_path,
    )
    record_event(
        _event(run_id, "milestone", timestamp="2026-09-12T22:00:00Z", phaseId="2"),
        run_id=run_id,
        root=tmp_path,
    )
    assert len(read_events(run_id, event_types=["milestone"], root=tmp_path)) == 1
    assert len(read_events(run_id, phase_id="2", root=tmp_path)) == 1
    assert len(read_events(run_id, after="2026-09-12T21:30:00Z", root=tmp_path)) == 1


def test_consolidate_sub_agent_events_idempotent(tmp_path: Path) -> None:
    _enable_capture(tmp_path)
    run_id = "deliver-test-6"
    ensure_capture_files(tmp_path, run_id)
    dispatch_id = "dispatch-a"
    sidecar = sub_agent_events_path(tmp_path, run_id, dispatch_id)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    ev = _event(run_id, "discovery", provenanceKind="sub_agent_feed")
    sidecar.write_text(json.dumps(ev) + "\n", encoding="utf-8")
    assert consolidate_sub_agent_events(run_id, dispatch_id=dispatch_id, root=tmp_path) == 1
    assert consolidate_sub_agent_events(run_id, dispatch_id=dispatch_id, root=tmp_path) == 0
    assert len(read_events(run_id, root=tmp_path)) == 1


def test_missing_sidecar_returns_zero(tmp_path: Path) -> None:
    _enable_capture(tmp_path)
    run_id = "deliver-test-7"
    ensure_capture_files(tmp_path, run_id)
    assert consolidate_sub_agent_events(run_id, dispatch_id="missing", root=tmp_path) == 0
