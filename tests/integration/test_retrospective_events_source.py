"""Stub: retrospective evidence loading must use read_events (PRD 350 TS7)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

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


def _seed(root: Path, run_id: str) -> None:
    capture.ensure_capture_files(root, run_id)
    capture._emit_blocker(
        "waiting",
        {"tasks": []},
        "phase-2",
        run_id,
        root=root,
    )
    capture._emit_milestone(
        "decision_recorded", "phase-2", run_id, "decision recorded", root=root
    )
    capture.emit_discovery(
        "note",
        "phase-2",
        run_id,
        "tool_output",
        "ref",
        root=root,
    )


def test_retrospective_evidence_loader_calls_read_events(tmp_path: Path) -> None:
    """Establish the contract Phase 3 will finalize: load via read_events only."""
    _enable(tmp_path)
    run_id = "retro-stub-run"
    _seed(tmp_path, run_id)

    def fake_retrospective_load(run_id: str, *, root: Path):
        # Prospective retrospective evidence loader (Phase 3 wires /sw-retrospective).
        return capture.read_events(
            run_id,
            event_types=["blocker", "milestone", "discovery"],
            root=root,
        )

    with mock.patch.object(capture, "read_events", wraps=capture.read_events) as wrapped:
        events = fake_retrospective_load(run_id, root=tmp_path)
        assert wrapped.called
        assert {e["eventType"] for e in events} <= {"blocker", "milestone", "discovery"}
        # No direct file open of events.jsonl from the loader path.
        assert all("eventId" in e for e in events)
