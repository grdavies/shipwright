#!/usr/bin/env python3
"""Redact-before-write gate for reviewer metrics metadata (PRD 273 R20)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.persistence import (  # noqa: E402
    MetadataSchemaError,
    build_metadata_record,
    redact_metadata_for_write,
    validate_metadata_payload,
)
from graph.reviewer_metrics.store_adapter import ReviewerMetricsStoreAdapter  # noqa: E402

_SECRET_SAMPLE = "ghp_" + "A" * 36


def test_metadata_schema_rejects_transcript_and_secrets() -> None:
    base = build_metadata_record(
        persona_id="persona",
        model_id="model",
        surface="surface",
        attribution_window="window",
        finding_id="finding",
        run_id="run",
        terminal_status="confirmed",
        match_reason="exogenous-human",
        outcome_kind="label",
        recorded_at="2026-08-16T00:00:00Z",
    )
    for forbidden in ("transcript", "findingBody", "prompt", "patch", "secret"):
        payload = dict(base)
        payload[forbidden] = "blocked-content"
        with pytest.raises(MetadataSchemaError):
            validate_metadata_payload(payload)


def test_redact_before_write_substitutes_secret_in_summary() -> None:
    metadata = build_metadata_record(
        persona_id="persona",
        model_id="model",
        surface="surface",
        attribution_window="window",
        finding_id="finding",
        run_id="run",
        terminal_status="confirmed",
        match_reason="exogenous-human",
        outcome_kind="label",
        recorded_at="2026-08-16T00:00:00Z",
        provenance_summary=f"operator:{_SECRET_SAMPLE}",
    )
    redacted, residuals = redact_metadata_for_write(metadata, may_egress=True)
    assert _SECRET_SAMPLE not in redacted["provenanceSummary"]
    assert "[REDACTED" in redacted["provenanceSummary"]


def test_adapter_redacts_on_export_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        adapter = ReviewerMetricsStoreAdapter(tmp, may_egress=True)
        metadata = build_metadata_record(
            persona_id="persona",
            model_id="model",
            surface="surface",
            attribution_window="window",
            finding_id="finding",
            run_id="run-export",
            terminal_status="confirmed",
            match_reason="exogenous-human",
            outcome_kind="label",
            recorded_at="2026-08-16T00:00:00Z",
            provenance_summary=f"token:{_SECRET_SAMPLE}",
        )
        adapter.persist_metadata(
            metadata,
            journal_entry={"runId": "run-export", "verdict": "merge-ready-green"},
        )
        export_path = Path(tmp) / "export.json"
        adapter.export_metadata_snapshot(export_path)
        text = export_path.read_text(encoding="utf-8")
        assert _SECRET_SAMPLE not in text
