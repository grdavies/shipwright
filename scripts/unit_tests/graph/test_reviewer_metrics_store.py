#!/usr/bin/env python3
"""Reviewer metrics store adapter authority and keying tests (PRD 273 R1, R24)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.learning_store import default_learning_root  # noqa: E402
from graph.reviewer_metrics.persistence import build_metadata_record  # noqa: E402
from graph.reviewer_metrics.store_adapter import (  # noqa: E402
    ReviewerMetricsStoreAdapter,
    assert_learning_store_authority,
)


def _journal(run_id: str = "run-metrics-1") -> dict[str, str]:
    return {"runId": run_id, "verdict": "merge-ready-green"}


def test_reviewer_metrics_persist_persona_model_surface_window() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        adapter = ReviewerMetricsStoreAdapter(tmp)
        metadata = build_metadata_record(
            persona_id="security-reviewer",
            model_id="claude-opus",
            surface="sw-review",
            attribution_window="2026-08-01/2026-08-16",
            finding_id="finding-keyed",
            run_id="run-keyed",
            terminal_status="confirmed",
            match_reason="exogenous-human",
            outcome_kind="label",
            recorded_at="2026-08-16T12:00:00Z",
        )
        event = adapter.persist_metadata(metadata, journal_entry=_journal("run-keyed"))
        assert event.cohort_dimensions["personaId"] == "security-reviewer"
        assert event.cohort_dimensions["modelId"] == "claude-opus"
        assert event.cohort_dimensions["surface"] == "sw-review"
        assert event.cohort_dimensions["attributionWindow"] == "2026-08-01/2026-08-16"
        matches = adapter.query_by_cohort(
            persona_id="security-reviewer",
            model_id="claude-opus",
            surface="sw-review",
            attribution_window="2026-08-01/2026-08-16",
        )
        assert len(matches) == 1
        assert matches[0].run_id == "run-keyed"


def test_adapter_uses_learning_store_append_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        adapter = ReviewerMetricsStoreAdapter(repo)
        metadata = build_metadata_record(
            persona_id="panel-a",
            model_id="model-a",
            surface="phase-review",
            attribution_window="window-a",
            finding_id="finding-a",
            run_id="run-a",
            terminal_status="confirmed",
            match_reason="exogenous-ci",
            outcome_kind="label",
            recorded_at="2026-08-16T00:00:00Z",
        )
        adapter.persist_metadata(metadata, journal_entry=_journal("run-a"))
        events_path = adapter.learning_store_path / "events.jsonl"
        assert events_path.is_file()
        assert not (repo / ".cursor" / "sw-memory").exists()
        assert adapter.iter_events()[0].writer == "graph.learning_store.LearningStore"


def test_v1_authority_is_learning_store_path_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        authority = assert_learning_store_authority(repo)
        expected = default_learning_root(repo)
        assert authority == expected
        assert authority == repo / ".cursor" / "sw-learning-store"
        adapter = ReviewerMetricsStoreAdapter(repo)
        assert adapter.learning_store_path == expected
