#!/usr/bin/env python3
"""Thin adapter from reviewer metrics to LearningStore (PRD 273 R13)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from graph.learning_store import (
    LearningEvent,
    LearningStore,
    default_learning_root,
    journal_digest,
)
from graph.reviewer_metrics.persistence import (
    MetadataSchemaError,
    redact_metadata_for_write,
    validate_metadata_payload,
)

AUTHORIZED_ADAPTER = "graph.reviewer_metrics.store_adapter.ReviewerMetricsStoreAdapter"

COHORT_DIMENSION_KEYS = frozenset(
    {"personaId", "modelId", "surface", "attributionWindow"}
)


class ReviewerMetricsStoreAdapter:
    """Append-only thin adapter — sole v1 authority is `.cursor/sw-learning-store`."""

    def __init__(self, repo_root: str | Path, *, may_egress: bool = False) -> None:
        self.repo_root = Path(repo_root)
        self.store_root = default_learning_root(self.repo_root)
        self._store = LearningStore(self.store_root, may_egress=may_egress)

    @property
    def learning_store_path(self) -> Path:
        return self.store_root

    def persist_metadata(
        self,
        metadata: Mapping[str, Any],
        *,
        journal_entry: Mapping[str, Any],
        provenance: str = "live",
        terminally_settled: bool = True,
        kernel_compiled: bool = True,
    ) -> LearningEvent:
        """Map validated metadata to a versioned LearningEvent via append-only LearningStore."""
        validated = validate_metadata_payload(metadata)
        redacted, _residuals = redact_metadata_for_write(
            validated,
            may_egress=self._store.may_egress,
        )
        cohort_dimensions = {
            key: redacted[key]
            for key in COHORT_DIMENSION_KEYS
            if key in redacted
        }
        outcomes = {
            key: value
            for key, value in redacted.items()
            if key not in COHORT_DIMENSION_KEYS and key != "schemaVersion"
        }
        digest = journal_digest(journal_entry)
        enriched_journal = {
            **dict(journal_entry),
            "reviewerMetricsDigest": digest,
            "adapter": AUTHORIZED_ADAPTER,
        }
        return self._store.append_from_journal(
            enriched_journal,
            provenance=provenance,
            cohort_dimensions=cohort_dimensions,
            outcomes=outcomes,
            terminally_settled=terminally_settled,
            kernel_compiled=kernel_compiled,
        )

    def export_metadata_snapshot(self, export_path: str | Path) -> Path:
        redacted_events: list[dict[str, Any]] = []
        for event in self._store.iter_events():
            payload = event.to_dict()
            cohort = dict(payload.get("cohortDimensions") or {})
            outcomes = dict(payload.get("outcomes") or {})
            merged = {"schemaVersion": 1, **cohort, **outcomes}
            redacted, _ = redact_metadata_for_write(
                merged,
                may_egress=self._store.may_egress,
            )
            payload = dict(payload)
            payload["cohortDimensions"] = {
                key: redacted[key] for key in COHORT_DIMENSION_KEYS if key in redacted
            }
            payload["outcomes"] = {
                key: value
                for key, value in redacted.items()
                if key not in COHORT_DIMENSION_KEYS and key != "schemaVersion"
            }
            redacted_events.append(payload)
        destination = Path(export_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        return self._store.export_before_gc(destination)

    def iter_events(self) -> tuple[LearningEvent, ...]:
        return tuple(self._store.iter_events())

    def query_by_cohort(
        self,
        *,
        persona_id: str | None = None,
        model_id: str | None = None,
        surface: str | None = None,
        attribution_window: str | None = None,
    ) -> tuple[LearningEvent, ...]:
        dimensions: dict[str, Any] = {}
        if persona_id is not None:
            dimensions["personaId"] = persona_id
        if model_id is not None:
            dimensions["modelId"] = model_id
        if surface is not None:
            dimensions["surface"] = surface
        if attribution_window is not None:
            dimensions["attributionWindow"] = attribution_window
        return self._store.query_routing_cohort(dimensions=dimensions or None)


def assert_learning_store_authority(repo_root: str | Path) -> Path:
    """Fail closed when the adapter would write outside the learning-store root."""
    root = Path(repo_root)
    authority = default_learning_root(root)
    if authority.name != "sw-learning-store":
        raise MetadataSchemaError("learning store authority path must be sw-learning-store")
    if ".cursor" not in authority.parts:
        raise MetadataSchemaError("learning store authority must live under .cursor")
    return authority
