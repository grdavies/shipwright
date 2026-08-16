#!/usr/bin/env python3
"""Historical learning/analytics store derived from receipts (PRD 272 R11–R14)."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from memory_redact import redact_with_postcondition

LEARNING_STORE_VERSION = 1
LEARNING_EVENT_SCHEMA_VERSION = 1
AUTHORIZED_WRITER = "graph.learning_store.LearningStore"

PROVENANCE_VALUES = frozenset({"live", "shadow", "benchmark", "replay"})
ROUTING_COHORT_PROVENANCE = frozenset({"live"})
DEFAULT_RETENTION_SECONDS = 90 * 24 * 60 * 60


class LearningStoreError(RuntimeError):
    """Base class for learning store failures."""


class ProvenanceRejected(LearningStoreError):
    """Raised when provenance or journal integrity fails validation on read."""


class ProvenanceKind(str, Enum):
    LIVE = "live"
    SHADOW = "shadow"
    BENCHMARK = "benchmark"
    REPLAY = "replay"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_learning_root(repo_root: str | Path) -> Path:
    """Gitignored append-only learning store — distinct from receipt authority (R11)."""
    return Path(repo_root) / ".cursor" / "sw-learning-store"


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _atomic_append_line(path: Path, line: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def journal_digest(journal_entry: Mapping[str, Any]) -> str:
    """Integrity binding to the authoritative run journal entry (R12)."""
    return hashlib.sha256(_canonical(journal_entry)).hexdigest()


def redact_derivation_payload(payload: Mapping[str, Any], *, may_egress: bool) -> dict[str, Any]:
    """Redact on the derivation write path when the store may leave the boundary (R14)."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    destination = "external" if may_egress else "local"
    redacted_text, residuals = redact_with_postcondition(serialized, destination=destination)
    redacted = json.loads(redacted_text)
    applied = {
        "destination": destination,
        "substitutionCount": max(0, len(serialized) - len(redacted_text)),
        "residualDetectors": residuals,
    }
    if isinstance(redacted, dict):
        redacted["appliedRedaction"] = applied
        return redacted
    return {"value": redacted, "appliedRedaction": applied}


@dataclass(frozen=True)
class LearningEvent:
    """Versioned analytics event schema (R11/R14)."""

    schema_version: int
    event_id: str
    run_id: str
    provenance: str
    journal_digest: str
    cohort_dimensions: dict[str, Any]
    outcomes: dict[str, Any]
    recorded_at: str
    writer: str = AUTHORIZED_WRITER
    applied_redaction: dict[str, Any] | None = None
    terminally_settled: bool = True
    kernel_compiled: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "eventId": self.event_id,
            "runId": self.run_id,
            "provenance": self.provenance,
            "journalDigest": self.journal_digest,
            "cohortDimensions": self.cohort_dimensions,
            "outcomes": self.outcomes,
            "recordedAt": self.recorded_at,
            "writer": self.writer,
            "terminallySettled": self.terminally_settled,
            "kernelCompiled": self.kernel_compiled,
        }
        if self.applied_redaction is not None:
            payload["appliedRedaction"] = self.applied_redaction
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LearningEvent:
        provenance = str(payload.get("provenance", ""))
        if provenance not in PROVENANCE_VALUES:
            raise ProvenanceRejected(f"invalid provenance: {provenance!r}")
        digest = str(payload.get("journalDigest", ""))
        if len(digest) != 64 or not all(ch in "0123456789abcdef" for ch in digest):
            raise ProvenanceRejected("journal digest missing or invalid")
        writer = str(payload.get("writer", ""))
        if writer != AUTHORIZED_WRITER:
            raise ProvenanceRejected(f"unauthorized writer: {writer!r}")
        return cls(
            schema_version=int(payload.get("schemaVersion", 0)),
            event_id=str(payload.get("eventId", "")),
            run_id=str(payload.get("runId", "")),
            provenance=provenance,
            journal_digest=digest,
            cohort_dimensions=dict(payload.get("cohortDimensions") or {}),
            outcomes=dict(payload.get("outcomes") or {}),
            recorded_at=str(payload.get("recordedAt", "")),
            writer=writer,
            applied_redaction=(
                dict(payload["appliedRedaction"])
                if isinstance(payload.get("appliedRedaction"), dict)
                else None
            ),
            terminally_settled=bool(payload.get("terminallySettled", False)),
            kernel_compiled=bool(payload.get("kernelCompiled", False)),
        )


def validate_admission(
    *,
    provenance: str,
    terminally_settled: bool,
    kernel_compiled: bool,
    for_routing_cohort: bool = False,
) -> None:
    """Admission rules for routing cohorts vs partitioned populations (R12)."""
    if provenance not in PROVENANCE_VALUES:
        raise ProvenanceRejected(f"invalid provenance: {provenance!r}")
    if for_routing_cohort:
        if provenance not in ROUTING_COHORT_PROVENANCE:
            raise ProvenanceRejected(
                f"provenance {provenance!r} excluded from routing cohorts"
            )
        if not terminally_settled:
            raise ProvenanceRejected("non-terminal run cannot enter routing cohort")
        if not kernel_compiled:
            raise ProvenanceRejected("non-kernel-compiled run cannot enter routing cohort")


class LearningStore:
    """Append-only derived analytics store with export-before-GC (R11/R14)."""

    def __init__(self, root: str | Path, *, may_egress: bool = False) -> None:
        self.root = Path(root)
        self.may_egress = may_egress
        self.events_path = self.root / "events.jsonl"
        self.meta_path = self.root / "meta.json"

    def _ensure_meta(self) -> dict[str, Any]:
        if self.meta_path.is_file():
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        meta = {
            "storeVersion": LEARNING_STORE_VERSION,
            "eventSchemaVersion": LEARNING_EVENT_SCHEMA_VERSION,
            "authorizedWriter": AUTHORIZED_WRITER,
            "createdAt": utc_now_iso(),
        }
        _atomic_write(self.meta_path, meta)
        return meta

    def append_from_journal(
        self,
        journal_entry: Mapping[str, Any],
        *,
        provenance: str,
        cohort_dimensions: Mapping[str, Any],
        outcomes: Mapping[str, Any],
        terminally_settled: bool = True,
        kernel_compiled: bool = True,
        for_routing_cohort: bool = False,
    ) -> LearningEvent:
        validate_admission(
            provenance=provenance,
            terminally_settled=terminally_settled,
            kernel_compiled=kernel_compiled,
            for_routing_cohort=for_routing_cohort,
        )
        self._ensure_meta()
        digest = journal_digest(journal_entry)
        raw = {
            "schemaVersion": LEARNING_EVENT_SCHEMA_VERSION,
            "eventId": str(uuid.uuid4()),
            "runId": str(journal_entry.get("runId", journal_entry.get("run_id", ""))),
            "provenance": provenance,
            "journalDigest": digest,
            "cohortDimensions": dict(cohort_dimensions),
            "outcomes": dict(outcomes),
            "recordedAt": utc_now_iso(),
            "writer": AUTHORIZED_WRITER,
            "terminallySettled": terminally_settled,
            "kernelCompiled": kernel_compiled,
        }
        redacted = redact_derivation_payload(raw, may_egress=self.may_egress)
        applied = redacted.pop("appliedRedaction", None)
        event = LearningEvent.from_dict({**redacted, "appliedRedaction": applied})
        _atomic_append_line(self.events_path, _canonical(event.to_dict()))
        return event

    def iter_events(self) -> Iterable[LearningEvent]:
        if not self.events_path.is_file():
            return
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            yield LearningEvent.from_dict(payload)

    def query_routing_cohort(
        self,
        *,
        dimensions: Mapping[str, Any] | None = None,
    ) -> tuple[LearningEvent, ...]:
        """Default routing cohort excludes shadow/benchmark/replay (R12)."""
        matches: list[LearningEvent] = []
        for event in self.iter_events():
            try:
                validate_admission(
                    provenance=event.provenance,
                    terminally_settled=event.terminally_settled,
                    kernel_compiled=event.kernel_compiled,
                    for_routing_cohort=True,
                )
            except ProvenanceRejected:
                continue
            if dimensions:
                cohort = event.cohort_dimensions
                if any(cohort.get(key) != value for key, value in dimensions.items()):
                    continue
            matches.append(event)
        return tuple(matches)

    def export_before_gc(self, export_path: str | Path) -> Path:
        """Export full store snapshot before receipt GC (R14)."""
        destination = Path(export_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "exportedAt": utc_now_iso(),
            "storeVersion": LEARNING_STORE_VERSION,
            "events": [event.to_dict() for event in self.iter_events()],
        }
        _atomic_write(destination, snapshot)
        return destination

    def gc_older_than(self, *, retention_seconds: int = DEFAULT_RETENTION_SECONDS) -> int:
        """Garbage-collect stale events after export — append-only rewrite."""
        if not self.events_path.is_file():
            return 0
        cutoff = datetime.now(timezone.utc).timestamp() - retention_seconds
        kept: list[dict[str, Any]] = []
        removed = 0
        for event in self.iter_events():
            recorded = datetime.fromisoformat(
                event.recorded_at.replace("Z", "+00:00")
            ).timestamp()
            if recorded < cutoff:
                removed += 1
                continue
            kept.append(event.to_dict())
        if removed:
            fd, temporary_name = tempfile.mkstemp(
                prefix=".events.", dir=str(self.events_path.parent)
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    for row in kept:
                        handle.write(_canonical(row))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.events_path)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        return removed


def derive_event_from_receipt(
    receipt_journal: Mapping[str, Any],
    *,
    provenance: str,
    may_egress: bool = False,
) -> dict[str, Any]:
    """Derive a redacted analytics event from an authoritative receipt journal (R11/R14)."""
    run_id = str(receipt_journal.get("runId", ""))
    digest = journal_digest(receipt_journal)
    cohort = {
        "language": receipt_journal.get("language"),
        "repoSize": receipt_journal.get("repoSize"),
        "workflowType": receipt_journal.get("workflowType"),
        "riskClass": receipt_journal.get("riskClass"),
        "modelTier": receipt_journal.get("modelTier"),
    }
    outcomes = {
        "readyWithoutRework": receipt_journal.get("readyWithoutRework"),
        "verdict": receipt_journal.get("verdict"),
    }
    raw = {
        "schemaVersion": LEARNING_EVENT_SCHEMA_VERSION,
        "eventId": str(uuid.uuid4()),
        "runId": run_id,
        "provenance": provenance,
        "journalDigest": digest,
        "cohortDimensions": cohort,
        "outcomes": outcomes,
        "recordedAt": utc_now_iso(),
        "writer": AUTHORIZED_WRITER,
        "terminallySettled": True,
        "kernelCompiled": True,
    }
    return redact_derivation_payload(raw, may_egress=may_egress)
