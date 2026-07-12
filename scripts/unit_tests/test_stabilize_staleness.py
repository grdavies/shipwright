"""Unit tests for stabilize_same_stage_lib and phase_staleness_lib (PRD 064 R31/R32)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import phase_staleness_lib as staleness
import stabilize_same_stage_lib as same_stage

ROOT = Path(__file__).resolve().parents[2]


def test_same_stage_counter_increments_without_sha_advance():
    state = same_stage.empty_state()
    state = same_stage.record_same_stage_outcome(
        state,
        head_sha="abc123",
        stage="stabilize",
        failure_set={"check:lint"},
        progressed=False,
    )
    state = same_stage.record_same_stage_outcome(
        state,
        head_sha="abc123",
        stage="stabilize",
        failure_set={"check:lint"},
        progressed=False,
    )
    assert state["failureCount"] == 2
    sig = same_stage.no_progress_signature_fields(state)
    assert "failureCount" not in sig


def test_same_stage_resets_on_progress():
    state = same_stage.record_same_stage_outcome(
        {},
        head_sha="abc123",
        stage="stabilize",
        failure_set={"check:lint"},
        progressed=False,
    )
    state = same_stage.record_same_stage_outcome(
        state,
        head_sha="def456",
        stage="stabilize",
        failure_set={"check:lint"},
        progressed=True,
    )
    assert state["failureCount"] == 0


def test_escalation_steps_tier_then_persona():
    cfg = same_stage.SameStageConfig(True, 2, "adversarial")
    low = same_stage.resolve_escalation(ROOT, failure_count=1, current_tier="build", cfg=cfg)
    assert low["escalated"] is False

    mid = same_stage.resolve_escalation(ROOT, failure_count=2, current_tier="build", cfg=cfg)
    assert mid["escalated"] is True
    assert mid["chosenTier"] == "mid"

    top = same_stage.resolve_escalation(ROOT, failure_count=3, current_tier="deep", cfg=cfg)
    assert top["escalated"] is True
    assert top["persona"] == "adversarial"


def test_staleness_waiting_on_human_with_pending_reply():
    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    cfg = staleness.StalenessConfig(True, 30.0, 5.0, 0.35)
    result = staleness.classify_staleness(
        {
            "now": now.isoformat().replace("+00:00", "Z"),
            "lastToolCallAt": "2026-07-11T11:58:00Z",
            "lastCommitAt": "2026-07-11T11:57:00Z",
            "lastStatusWriteAt": "2026-07-11T11:59:00Z",
            "pendingHumanReply": True,
        },
        cfg=cfg,
    )
    assert result["classification"] == "waiting-on-human"
    assert result["confidenceTier"] in {"high", "medium"}


def test_staleness_genuinely_stuck():
    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    cfg = staleness.StalenessConfig(True, 30.0, 5.0, 0.35)
    result = staleness.classify_staleness(
        {
            "now": now.isoformat().replace("+00:00", "Z"),
            "lastToolCallAt": "2026-07-11T10:00:00Z",
            "lastCommitAt": "2026-07-11T10:00:00Z",
            "lastStatusWriteAt": "2026-07-11T10:00:00Z",
            "pendingHumanReply": False,
        },
        cfg=cfg,
    )
    assert result["classification"] == "genuinely-stuck"
    assert staleness.should_defer_phase_timeout(result) is False


def test_staleness_actively_working():
    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    cfg = staleness.StalenessConfig(True, 30.0, 5.0, 0.35)
    result = staleness.classify_staleness(
        {
            "now": now.isoformat().replace("+00:00", "Z"),
            "lastToolCallAt": "2026-07-11T11:58:30Z",
            "lastCommitAt": None,
            "lastStatusWriteAt": None,
            "pendingHumanReply": False,
        },
        cfg=cfg,
    )
    assert result["classification"] == "actively-working"
