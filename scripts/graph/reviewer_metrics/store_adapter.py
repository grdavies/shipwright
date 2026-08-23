#!/usr/bin/env python3
"""Thin adapter from reviewer metrics to LearningStore (PRD 273 R13)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import json

from graph.learning_store import (
    LearningEvent,
    LearningStore,
    default_learning_root,
    journal_digest,
)
from graph.reviewer_metrics.persistence import (
    MetadataSchemaError,
    build_harvest_metadata_record,
    redact_harvest_for_write,
    redact_metadata_for_write,
    validate_metadata_payload,
)
from graph.reviewer_metrics.harvest import HARVEST_SCHEMA_VERSION, HarvestRecord
from graph.reviewer_metrics.provenance import HarvestFindingProvenance, build_harvest_provenance

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
        self.harvest_records_path = self.store_root / "harvest-records.jsonl"

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

    def persist_harvest(
        self,
        harvest: HarvestRecord,
        *,
        provenance_rows: Sequence[HarvestFindingProvenance],
        journal_entry: Mapping[str, Any],
        recorded_at: str,
        provenance: str = "live",
    ) -> LearningEvent:
        """Persist harvest metadata and reviewer scores without promotion side effects."""
        summary = ",".join(item.finding_id for item in build_harvest_provenance(provenance_rows)[:5])
        metadata = build_harvest_metadata_record(
            harvested_at=harvest.harvested_at,
            reviewer_count=len(harvest.reviewers),
            finding_count=len(provenance_rows),
            recorded_at=recorded_at,
            provenance_summary=summary,
        )
        redacted, _ = redact_harvest_for_write(metadata, may_egress=self._store.may_egress)
        digest = journal_digest(journal_entry)
        enriched_journal = {
            **dict(journal_entry),
            "reviewerMetricsDigest": digest,
            "adapter": AUTHORIZED_ADAPTER,
            "harvest": harvest.to_dict(),
            "harvestProvenance": [item.to_dict() for item in build_harvest_provenance(provenance_rows)],
        }
        event = self._store.append_from_journal(
            enriched_journal,
            provenance=provenance,
            cohort_dimensions={"surface": "reviewer-harvest"},
            outcomes=redacted,
            terminally_settled=True,
            kernel_compiled=True,
        )
        record = {
            "harvest": harvest.to_dict(),
            "provenance": [item.to_dict() for item in build_harvest_provenance(provenance_rows)],
            "eventId": event.event_id,
        }
        serialized = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        redacted_line, _ = redact_harvest_for_write(
            {
                "schemaVersion": HARVEST_SCHEMA_VERSION,
                "harvestedAt": harvest.harvested_at,
                "reviewerCount": len(harvest.reviewers),
                "findingCount": len(provenance_rows),
                "recordedAt": recorded_at,
                "outcomeKind": "harvest",
                "provenanceSummary": serialized[:120],
            },
            may_egress=self._store.may_egress,
        )
        self.harvest_records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.harvest_records_path.open("a", encoding="utf-8") as handle:
            handle.write(serialized)
            if redacted_line:
                handle.flush()
        return event

    def load_latest_harvest(self) -> HarvestRecord | None:
        if not self.harvest_records_path.is_file():
            return None
        latest: HarvestRecord | None = None
        latest_at = ""
        for line in self.harvest_records_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            harvest_payload = payload.get("harvest")
            if not isinstance(harvest_payload, Mapping):
                continue
            harvested_at = str(harvest_payload.get("harvestedAt", ""))
            if harvested_at >= latest_at:
                latest_at = harvested_at
                latest = HarvestRecord.from_dict(harvest_payload)
        return latest


def assert_learning_store_authority(repo_root: str | Path) -> Path:
    """Fail closed when the adapter would write outside the learning-store root."""
    root = Path(repo_root)
    authority = default_learning_root(root)
    if authority.name != "sw-learning-store":
        raise MetadataSchemaError("learning store authority path must be sw-learning-store")
    if ".cursor" not in authority.parts:
        raise MetadataSchemaError("learning store authority must live under .cursor")
    return authority
