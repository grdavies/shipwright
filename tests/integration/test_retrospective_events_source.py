"""TS7: retrospective evidence loading uses read_events (PRD 350 R25–R28)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import retrospective_evidence as retro
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
        "waiting on approval",
        {"tasks": []},
        "phase-3",
        run_id,
        root=root,
    )
    capture._emit_milestone(
        "decision_recorded", "phase-3", run_id, "decision recorded", root=root
    )
    capture.emit_discovery(
        "found undocumented contract",
        "phase-3",
        run_id,
        "tool_output",
        "ref",
        root=root,
    )


def test_retrospective_evidence_loader_calls_read_events(tmp_path: Path) -> None:
    _enable(tmp_path)
    run_id = "retro-ts7-run"
    _seed(tmp_path, run_id)

    with mock.patch.object(retro, "read_events", wraps=capture.read_events) as wrapped:
        events = retro.load_retrospective_evidence(run_id, root=tmp_path)
        assert wrapped.called
        assert {e["eventType"] for e in events} <= {"blocker", "milestone", "discovery"}
        assert all("eventId" in e for e in events)


def test_unresolved_blockers_and_pending_memory_candidates(tmp_path: Path) -> None:
    _enable(tmp_path)
    run_id = "retro-ts7-run-2"
    _seed(tmp_path, run_id)

    md = retro.render_retrospective_markdown(run_id, root=tmp_path)
    assert "### Unresolved Blockers" in md
    assert "waiting on approval" in md
    assert "pending_human_review" in md
    assert "Memory Candidates" in md

    capture._emit_milestone(
        "blocker_resolved",
        "phase-3",
        run_id,
        "blocker resolved waiting on approval",
        root=tmp_path,
    )
    events = retro.load_retrospective_evidence(run_id, root=tmp_path)
    assert retro.unresolved_blockers(events) == []


def test_no_direct_events_file_open_in_retrospective_module() -> None:
    source = Path(retro.__file__).read_text(encoding="utf-8")
    assert "read_events" in source
    # Module must not bypass the typed API with a raw events.jsonl open.
    assert "open(events" not in source
    assert "events.jsonl').open" not in source
