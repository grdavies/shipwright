#!/usr/bin/env python3
"""Workflow intelligence cohort store — ingest, aggregate, cohort keys (PRD 280 R6–R8)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

STORE_VERSION = 1
RECORD_SCHEMA_VERSION = 1
AGGREGATE_SCHEMA_VERSION = 1
ARTIFACT_ROOT = ".cursor/sw-workflow-intelligence"

COHORT_DIMENSION_KEYS = (
    "workflowType",
    "riskClass",
    "modelTier",
    "language",
    "repoSize",
    "planPolicy",
)


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


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


def store_root(repo_root: Path) -> Path:
    return repo_root / ARTIFACT_ROOT


def normalize_cohort_dimensions(dimensions: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize cohort dimension tuple for stable content-addressed keys (R6)."""
    normalized: dict[str, Any] = {}
    for key in COHORT_DIMENSION_KEYS:
        value = dimensions.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            normalized[key] = value.strip().lower()
        else:
            normalized[key] = value
    return normalized


def cohort_key(dimensions: Mapping[str, Any]) -> str:
    """SHA-256 content-addressed cohort key from normalized dimensions (R6)."""
    normalized = normalize_cohort_dimensions(dimensions)
    return hashlib.sha256(_canonical(normalized)).hexdigest()


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _safe_run_id(run_id: str) -> str:
    cleaned = run_id.strip()
    if not cleaned or "/" in cleaned or "\\" in cleaned or ".." in cleaned:
        raise ValueError(f"invalid run id: {run_id!r}")
    return cleaned


@dataclass(frozen=True)
class CohortMetrics:
    node_count: int
    total_tokens: int
    total_latency_ms: int
    latency_p50_ms: float
    latency_p95_ms: float
    ready_without_rework: bool
    human_rework: bool
    rework_contribution: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeCount": self.node_count,
            "totalTokens": self.total_tokens,
            "totalLatencyMs": self.total_latency_ms,
            "latencyP50Ms": round(self.latency_p50_ms, 3),
            "latencyP95Ms": round(self.latency_p95_ms, 3),
            "readyWithoutRework": self.ready_without_rework,
            "humanRework": self.human_rework,
            "reworkContribution": round(self.rework_contribution, 6),
        }


def metrics_from_graph_snapshot(
    receipts: Iterable[Mapping[str, Any]],
    telemetry: Mapping[str, Any] | None,
) -> CohortMetrics:
    """Derive per-run intelligence metrics from graph receipt snapshots (R7)."""
    receipt_list = list(receipts)
    latencies = [float(item.get("durationMs") or 0) for item in receipt_list]
    total_tokens = sum(int(item.get("tokens") or 0) for item in receipt_list)
    total_latency = sum(int(item.get("durationMs") or 0) for item in receipt_list)
    telemetry_payload = dict(telemetry or {})
    human_rework = bool(telemetry_payload.get("humanRework"))
    terminal_ready = str(telemetry_payload.get("terminalVerdict") or "") == "ready"
    ready_without_rework = terminal_ready and not human_rework
    failed = sum(1 for item in receipt_list if str(item.get("verdict") or "") != "pass")
    rework_contribution = failed / len(receipt_list) if receipt_list else 0.0
    return CohortMetrics(
        node_count=len(receipt_list),
        total_tokens=total_tokens,
        total_latency_ms=total_latency,
        latency_p50_ms=_percentile(latencies, 50.0),
        latency_p95_ms=_percentile(latencies, 95.0),
        ready_without_rework=ready_without_rework,
        human_rework=human_rework,
        rework_contribution=rework_contribution,
    )


class WorkflowIntelligenceStore:
    """Gitignored cohort store with per-run upsert and incremental aggregation (R7/R8)."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.root = store_root(self.repo_root)
        self.records_dir = self.root / "records"
        self.aggregates_dir = self.root / "aggregates"
        self.meta_path = self.root / "meta.json"

    def _ensure_meta(self) -> dict[str, Any]:
        if self.meta_path.is_file():
            payload = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        meta = {
            "storeVersion": STORE_VERSION,
            "recordSchemaVersion": RECORD_SCHEMA_VERSION,
            "aggregateSchemaVersion": AGGREGATE_SCHEMA_VERSION,
            "aggregateCursorUpdatedAt": "",
            "createdAt": utc_now_iso(),
        }
        _atomic_write(self.meta_path, meta)
        return meta

    def record_path(self, run_id: str) -> Path:
        safe = _safe_run_id(run_id)
        return self.records_dir / f"{safe}.json"

    def load_record(self, run_id: str) -> dict[str, Any] | None:
        path = self.record_path(run_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    def upsert_record(
        self,
        *,
        graph_run_id: str,
        deliver_run_id: str | None,
        cohort_dimensions: Mapping[str, Any],
        metrics: CohortMetrics,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        """Upsert intelligence record keyed by graphRunId with deliver runId binding (R7)."""
        self._ensure_meta()
        safe_graph = _safe_run_id(graph_run_id)
        stamp = updated_at or utc_now_iso()
        existing = self.load_record(safe_graph)
        if existing:
            prior = str(existing.get("updatedAt") or "")
            if prior and prior > stamp:
                return existing
        normalized = normalize_cohort_dimensions(cohort_dimensions)
        record = {
            "schemaVersion": RECORD_SCHEMA_VERSION,
            "graphRunId": safe_graph,
            "deliverRunId": deliver_run_id,
            "cohortKey": cohort_key(normalized),
            "cohortDimensions": normalized,
            "metrics": metrics.to_dict(),
            "updatedAt": stamp,
            "ingestedAt": utc_now_iso(),
        }
        _atomic_write(self.record_path(safe_graph), record)
        return record

    def iter_records(self) -> Iterable[dict[str, Any]]:
        if not self.records_dir.is_dir():
            return
        for path in sorted(self.records_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                yield payload

    def aggregate_path(self, key: str) -> Path:
        if len(key) != 64 or any(ch not in "0123456789abcdef" for ch in key):
            raise ValueError("invalid cohort key")
        return self.aggregates_dir / f"{key}.json"

    def aggregate_cohort(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        if not records:
            fail("no-records-for-cohort")
        sample = records[0]
        latencies: list[float] = []
        tokens: list[int] = []
        rework_rates: list[float] = []
        rwr_hits = 0
        for record in records:
            metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
            latencies.append(float(metrics.get("latencyP50Ms") or 0))
            tokens.append(int(metrics.get("totalTokens") or 0))
            rework_rates.append(float(metrics.get("reworkContribution") or 0))
            if metrics.get("readyWithoutRework"):
                rwr_hits += 1
        return {
            "schemaVersion": AGGREGATE_SCHEMA_VERSION,
            "cohortKey": sample.get("cohortKey"),
            "cohortDimensions": sample.get("cohortDimensions") or {},
            "sampleSize": len(records),
            "readyWithoutReworkRate": rwr_hits / len(records),
            "latencyP50Ms": round(_percentile(latencies, 50.0), 3),
            "latencyP95Ms": round(_percentile(latencies, 95.0), 3),
            "totalTokensP50": int(_percentile([float(v) for v in tokens], 50.0)),
            "reworkContributionP95": round(_percentile(rework_rates, 95.0), 6),
            "updatedAt": utc_now_iso(),
        }

    def aggregate_incremental(self, *, dry_run: bool = True) -> dict[str, Any]:
        """Incremental aggregation cursor by record updatedAt; dry-run by default (R8)."""
        meta = self._ensure_meta()
        cursor = str(meta.get("aggregateCursorUpdatedAt") or "")
        pending = [
            record
            for record in self.iter_records()
            if str(record.get("updatedAt") or "") > cursor
        ]
        by_cohort: dict[str, list[dict[str, Any]]] = {}
        for record in pending:
            key = str(record.get("cohortKey") or "")
            if not key:
                continue
            by_cohort.setdefault(key, []).append(record)

        aggregates: list[dict[str, Any]] = []
        for key, cohort_records in sorted(by_cohort.items()):
            existing_path = self.aggregates_dir / f"{key}.json"
            merged = list(cohort_records)
            if existing_path.is_file():
                try:
                    prior = json.loads(existing_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    prior = None
                if isinstance(prior, dict):
                    merged = [prior, *cohort_records]
            aggregates.append(self.aggregate_cohort(merged))

        max_updated = cursor
        for record in pending:
            stamp = str(record.get("updatedAt") or "")
            if stamp > max_updated:
                max_updated = stamp

        result = {
            "verdict": "pass",
            "dryRun": dry_run,
            "cursorBefore": cursor,
            "cursorAfter": max_updated if not dry_run else cursor,
            "pendingRecordCount": len(pending),
            "cohortCount": len(aggregates),
            "aggregates": aggregates,
        }

        if not dry_run and pending:
            self.aggregates_dir.mkdir(parents=True, exist_ok=True)
            for aggregate in aggregates:
                key = str(aggregate.get("cohortKey") or "")
                if key:
                    _atomic_write(self.aggregate_path(key), aggregate)
            meta["aggregateCursorUpdatedAt"] = max_updated
            meta["lastAggregateAt"] = utc_now_iso()
            _atomic_write(self.meta_path, meta)
            result["cursorAfter"] = max_updated

        return result

    def load_aggregate(self, key: str) -> dict[str, Any] | None:
        path = self.aggregate_path(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def resolve_aggregate(self, key: str) -> dict[str, Any] | None:
        """Load persisted aggregate or compute from ingested records."""
        existing = self.load_aggregate(key)
        if existing:
            return existing
        records = [
            record
            for record in self.iter_records()
            if str(record.get("cohortKey") or "") == key
        ]
        if not records:
            return None
        return self.aggregate_cohort(records)

    def records_for_cohort(self, key: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.iter_records()
            if str(record.get("cohortKey") or "") == key
        ]

    def list_cohort_summaries(self) -> list[dict[str, Any]]:
        summaries: dict[str, dict[str, Any]] = {}
        for record in self.iter_records():
            key = str(record.get("cohortKey") or "")
            if not key:
                continue
            entry = summaries.setdefault(
                key,
                {
                    "cohortKey": key,
                    "cohortDimensions": record.get("cohortDimensions") or {},
                    "recordCount": 0,
                },
            )
            entry["recordCount"] += 1
        for key in sorted(summaries):
            aggregate = self.resolve_aggregate(key)
            if aggregate:
                summaries[key]["aggregate"] = {
                    "sampleSize": aggregate.get("sampleSize"),
                    "latencyP50Ms": aggregate.get("latencyP50Ms"),
                    "latencyP95Ms": aggregate.get("latencyP95Ms"),
                    "reworkContributionP95": aggregate.get("reworkContributionP95"),
                    "readyWithoutReworkRate": aggregate.get("readyWithoutReworkRate"),
                }
        return [summaries[key] for key in sorted(summaries)]


def _resolve_cohort_key(store: WorkflowIntelligenceStore, raw: str | None, dimensions: str | None) -> str:
    if raw:
        key = raw.strip()
        if len(key) != 64:
            fail("invalid cohort key")
        return key
    if not dimensions:
        fail("cohort key or dimensions JSON required")
    parsed = json.loads(dimensions)
    if not isinstance(parsed, dict):
        fail("dimensions must be a JSON object")
    return cohort_key(parsed)


def _metric_slice(aggregate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "latencyP50Ms": aggregate.get("latencyP50Ms"),
        "latencyP95Ms": aggregate.get("latencyP95Ms"),
        "reworkContributionP95": aggregate.get("reworkContributionP95"),
        "readyWithoutReworkRate": aggregate.get("readyWithoutReworkRate"),
        "sampleSize": aggregate.get("sampleSize"),
    }


def cmd_compare(args: argparse.Namespace) -> dict[str, Any]:
    store = WorkflowIntelligenceStore(args.root.resolve())
    left_key = _resolve_cohort_key(store, args.left_key, args.left_dimensions)
    right_key = _resolve_cohort_key(store, args.right_key, args.right_dimensions)
    left = store.resolve_aggregate(left_key)
    right = store.resolve_aggregate(right_key)
    if not left:
        fail("left cohort has no data", leftKey=left_key)
    if not right:
        fail("right cohort has no data", rightKey=right_key)
    left_metrics = _metric_slice(left)
    right_metrics = _metric_slice(right)
    delta: dict[str, Any] = {}
    for field in ("latencyP50Ms", "latencyP95Ms", "reworkContributionP95", "readyWithoutReworkRate"):
        left_val = float(left_metrics.get(field) or 0)
        right_val = float(right_metrics.get(field) or 0)
        delta[field] = round(right_val - left_val, 6)
    return {
        "verdict": "pass",
        "action": "compare",
        "left": {"cohortKey": left_key, "metrics": left_metrics},
        "right": {"cohortKey": right_key, "metrics": right_metrics},
        "delta": delta,
    }


def cmd_trend(args: argparse.Namespace) -> dict[str, Any]:
    store = WorkflowIntelligenceStore(args.root.resolve())
    key = _resolve_cohort_key(store, args.cohort_key, args.dimensions)
    since = str(args.since or "").strip()
    records = store.records_for_cohort(key)
    if since:
        records = [record for record in records if str(record.get("updatedAt") or "") >= since]
    records.sort(key=lambda item: str(item.get("updatedAt") or ""))
    points: list[dict[str, Any]] = []
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        points.append(
            {
                "updatedAt": record.get("updatedAt"),
                "graphRunId": record.get("graphRunId"),
                "latencyP50Ms": metrics.get("latencyP50Ms"),
                "latencyP95Ms": metrics.get("latencyP95Ms"),
                "reworkContribution": metrics.get("reworkContribution"),
                "readyWithoutRework": metrics.get("readyWithoutRework"),
            }
        )
    return {
        "verdict": "pass",
        "action": "trend",
        "cohortKey": key,
        "since": since or None,
        "pointCount": len(points),
        "points": points,
    }


def cmd_top_rework(args: argparse.Namespace) -> dict[str, Any]:
    store = WorkflowIntelligenceStore(args.root.resolve())
    key_filter = str(args.cohort_key or "").strip()
    rows: list[dict[str, Any]] = []
    for record in store.iter_records():
        cohort_key = str(record.get("cohortKey") or "")
        if key_filter and cohort_key != key_filter:
            continue
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        rows.append(
            {
                "graphRunId": record.get("graphRunId"),
                "deliverRunId": record.get("deliverRunId"),
                "cohortKey": cohort_key,
                "updatedAt": record.get("updatedAt"),
                "reworkContribution": float(metrics.get("reworkContribution") or 0),
                "humanRework": bool(metrics.get("humanRework")),
            }
        )
    rows.sort(
        key=lambda item: (
            -float(item.get("reworkContribution") or 0),
            str(item.get("updatedAt") or ""),
        )
    )
    limit = max(1, int(args.limit or 10))
    return {
        "verdict": "pass",
        "action": "top-rework",
        "cohortKey": key_filter or None,
        "limit": limit,
        "contributors": rows[:limit],
    }


def _graph_store_root(repo_root: Path) -> Path:
    return repo_root / ".cursor" / "sw-graph-runs"


def ingest_graph_run(
    repo_root: Path,
    *,
    graph_run_id: str,
    deliver_run_id: str | None = None,
) -> dict[str, Any]:
    from graph.execution_receipts import ExecutionReceiptJournal, default_store_root

    safe_graph = _safe_run_id(graph_run_id)
    journal = ExecutionReceiptJournal.for_run(
        default_store_root(repo_root),
        safe_graph,
        repo_root=repo_root,
    )
    receipts = journal.list_run_receipts(safe_graph)
    telemetry = journal.read_telemetry() or {}
    cohort_dimensions = {
        "workflowType": telemetry.get("workflowType") or "deliver",
        "riskClass": telemetry.get("riskClass") or "standard",
        "modelTier": telemetry.get("modelTier") or "build",
        "language": telemetry.get("language") or "python",
        "repoSize": telemetry.get("repoSize") or "medium",
        "planPolicy": telemetry.get("planPolicy") or "canonical",
    }
    metrics = metrics_from_graph_snapshot(receipts, telemetry)
    store = WorkflowIntelligenceStore(repo_root)
    record = store.upsert_record(
        graph_run_id=safe_graph,
        deliver_run_id=deliver_run_id,
        cohort_dimensions=cohort_dimensions,
        metrics=metrics,
        updated_at=str(telemetry.get("updatedAt") or utc_now_iso()),
    )
    return {
        "verdict": "pass",
        "action": "ingest",
        "graphRunId": safe_graph,
        "deliverRunId": deliver_run_id,
        "record": record,
        "receiptCount": len(receipts),
    }


def optimization_candidates_from_intelligence(
    repo_root: Path,
    *,
    canonical_graph: Mapping[str, Any],
    limit: int = 5,
    cohort_key_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Build advisory optimization candidate proposals from cohort intelligence (R9)."""
    store = WorkflowIntelligenceStore(repo_root)
    records = list(store.iter_records())
    if cohort_key_filter:
        records = [
            record
            for record in records
            if str(record.get("cohortKey") or "") == cohort_key_filter
        ]
    records.sort(
        key=lambda item: (
            -float((item.get("metrics") or {}).get("reworkContribution") or 0),
            str(item.get("updatedAt") or ""),
        )
    )
    candidates: list[dict[str, Any]] = []
    for record in records[: max(1, limit)]:
        candidate = json.loads(json.dumps(dict(canonical_graph)))
        metadata = candidate.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["optimizationSource"] = "workflow-intelligence"
            metadata["cohortKey"] = record.get("cohortKey")
            metadata["graphRunId"] = record.get("graphRunId")
            metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
            metadata["reworkContribution"] = metrics.get("reworkContribution")
            metadata["latencyP95Ms"] = metrics.get("latencyP95Ms")
        candidates.append(candidate)
    return candidates


def export_shadow_candidates(
    repo_root: Path,
    *,
    canonical_graph: Mapping[str, Any],
    shadow_enabled: bool = True,
    limit: int = 5,
    cohort_key: str | None = None,
) -> dict[str, Any]:
    """Export workflow-intelligence optimization candidates to shadow inputs (R9)."""
    from graph.dynamic_proposal import export_shadow_evaluation_inputs

    candidates = optimization_candidates_from_intelligence(
        repo_root,
        canonical_graph=canonical_graph,
        limit=limit,
        cohort_key_filter=cohort_key,
    )
    return export_shadow_evaluation_inputs(
        candidates,
        canonical_graph=canonical_graph,
        shadow_enabled=shadow_enabled,
    )


def cmd_shadow_export(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    if not args.canonical_graph:
        fail("--canonical-graph required")
    canonical_path = Path(args.canonical_graph)
    if not canonical_path.is_file():
        fail("canonical graph file not found", path=str(canonical_path))
    canonical_graph = json.loads(canonical_path.read_text(encoding="utf-8"))
    if not isinstance(canonical_graph, dict):
        fail("canonical graph must be a JSON object")
    return export_shadow_candidates(
        root,
        canonical_graph=canonical_graph,
        shadow_enabled=not bool(args.disabled),
        limit=int(args.limit or 5),
        cohort_key=str(args.cohort_key or "").strip() or None,
    )


def cmd_cohort_key(args: argparse.Namespace) -> dict[str, Any]:
    raw = json.loads(args.dimensions)
    if not isinstance(raw, dict):
        fail("dimensions must be a JSON object")
    normalized = normalize_cohort_dimensions(raw)
    return {
        "verdict": "pass",
        "action": "cohort-key",
        "cohortDimensions": normalized,
        "cohortKey": cohort_key(normalized),
    }


def cmd_ingest(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    if not args.graph_run_id:
        fail("--graph-run-id required")
    return ingest_graph_run(
        root,
        graph_run_id=args.graph_run_id,
        deliver_run_id=args.deliver_run_id,
    )


def cmd_aggregate(args: argparse.Namespace) -> dict[str, Any]:
    store = WorkflowIntelligenceStore(args.root.resolve())
    dry_run = not bool(args.write)
    return store.aggregate_incremental(dry_run=dry_run)


def cmd_list_records(args: argparse.Namespace) -> dict[str, Any]:
    store = WorkflowIntelligenceStore(args.root.resolve())
    records = list(store.iter_records())
    return {
        "verdict": "pass",
        "action": "list-records",
        "count": len(records),
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Workflow intelligence cohort store (PRD 280)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    key_cmd = sub.add_parser("cohort-key", help="Compute content-addressed cohort key")
    key_cmd.add_argument("dimensions", help="JSON object of cohort dimensions")

    ingest_cmd = sub.add_parser("ingest", help="Ingest graph receipt snapshot for a run")
    ingest_cmd.add_argument("--graph-run-id", required=True)
    ingest_cmd.add_argument("--deliver-run-id")

    aggregate_cmd = sub.add_parser(
        "aggregate",
        help="Incremental cohort aggregation (dry-run default)",
    )
    aggregate_cmd.add_argument(
        "--write",
        action="store_true",
        help="Persist aggregates and advance cursor (default is dry-run)",
    )

    sub.add_parser("list-records", help="List ingested intelligence records")

    compare_cmd = sub.add_parser("compare", help="Compare cohort p50/p95 metrics (R8)")
    compare_cmd.add_argument("--left-key")
    compare_cmd.add_argument("--right-key")
    compare_cmd.add_argument("--left-dimensions", help="JSON object when --left-key omitted")
    compare_cmd.add_argument("--right-dimensions", help="JSON object when --right-key omitted")

    trend_cmd = sub.add_parser("trend", help="Trend cohort metrics over time (R8)")
    trend_cmd.add_argument("--cohort-key")
    trend_cmd.add_argument("--dimensions", help="JSON object when --cohort-key omitted")
    trend_cmd.add_argument("--since", help="ISO timestamp lower bound (inclusive)")

    top_rework_cmd = sub.add_parser("top-rework", help="Top rework contributors (R8)")
    top_rework_cmd.add_argument("--cohort-key", default="")
    top_rework_cmd.add_argument("--limit", type=int, default=10)

    shadow_export_cmd = sub.add_parser(
        "shadow-export",
        help="Export optimization candidates to shadow evaluation inputs (R9)",
    )
    shadow_export_cmd.add_argument(
        "--canonical-graph",
        required=True,
        help="Path to canonical WorkflowGraph JSON",
    )
    shadow_export_cmd.add_argument("--cohort-key", default="")
    shadow_export_cmd.add_argument("--limit", type=int, default=5)
    shadow_export_cmd.add_argument(
        "--disabled",
        action="store_true",
        help="Simulate shadow-disabled export (read-only skipped payload)",
    )

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "cohort-key":
        emit(cmd_cohort_key(args))
    if args.command == "ingest":
        emit(cmd_ingest(args))
    if args.command == "aggregate":
        emit(cmd_aggregate(args))
    if args.command == "list-records":
        emit(cmd_list_records(args))
    if args.command == "compare":
        emit(cmd_compare(args))
    if args.command == "trend":
        emit(cmd_trend(args))
    if args.command == "top-rework":
        emit(cmd_top_rework(args))
    if args.command == "shadow-export":
        emit(cmd_shadow_export(args))
    fail(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    run_module_main(main)
