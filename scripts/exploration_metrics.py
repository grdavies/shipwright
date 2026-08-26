#!/usr/bin/env python3
"""First-release exploration quality metrics (PRD 331 R33, R40, R43)."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from exploration_security import assert_secret_free

METRIC_VERSION = 1

EVENT_PREMATURE_DOC = "premature_doc_attempt"
EVENT_RESUME_SUCCESS = "resume_success"
EVENT_RESUME_FAILURE = "resume_failure"
EVENT_AUTHORITY_VIOLATION = "authority_boundary_violation"
EVENT_SESSION_START = "exploration_session_start"

ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_PREMATURE_DOC,
        EVENT_RESUME_SUCCESS,
        EVENT_RESUME_FAILURE,
        EVENT_AUTHORITY_VIOLATION,
        EVENT_SESSION_START,
    }
)

SECRET_PATTERN = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|apiKey|password\s*=)",
    re.IGNORECASE,
)


class ExplorationMetricsError(ValueError):
    """Invalid exploration metric event or aggregation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    return Path(__file__).resolve().parent.parent


def _redact_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    redacted = deepcopy(dict(metadata))
    for key, value in list(redacted.items()):
        if SECRET_PATTERN.search(str(key)) or (
            isinstance(value, str) and SECRET_PATTERN.search(value)
        ):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = _redact_metadata(value)
    try:
        assert_secret_free(redacted)
    except Exception:
        return {"redacted": True}
    return redacted


def deterministic_event_id(
    event_type: str,
    map_id: str,
    *,
    sequence: int = 0,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Stable event identity for replay-safe aggregation (R33)."""
    payload = json.dumps(
        {
            "eventType": event_type,
            "mapId": map_id,
            "sequence": sequence,
            "metadata": _redact_metadata(metadata),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"evt-{digest}"


def build_event(
    event_type: str,
    map_id: str,
    *,
    sequence: int = 0,
    metadata: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Create a redacted, schema-stable metric event."""
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ExplorationMetricsError(f"unknown-event-type:{event_type}")
    cleaned_map = str(map_id or "").strip()
    if not cleaned_map:
        raise ExplorationMetricsError("missing-map-id")
    redacted = _redact_metadata(metadata)
    event = {
        "version": METRIC_VERSION,
        "id": deterministic_event_id(
            event_type, cleaned_map, sequence=sequence, metadata=redacted
        ),
        "eventType": event_type,
        "mapId": cleaned_map,
        "recordedAt": recorded_at or utc_now(),
        "metadata": redacted,
    }
    assert_secret_free(event)
    return event


def aggregate_metrics(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute premature-doc rate, resume success rate, and authority violations (R40)."""
    premature = 0
    resume_success = 0
    resume_failure = 0
    authority_violations = 0
    sessions = 0

    for raw in events:
        event_type = str(raw.get("eventType") or "")
        if event_type == EVENT_SESSION_START:
            sessions += 1
        elif event_type == EVENT_PREMATURE_DOC:
            premature += 1
        elif event_type == EVENT_RESUME_SUCCESS:
            resume_success += 1
        elif event_type == EVENT_RESUME_FAILURE:
            resume_failure += 1
        elif event_type == EVENT_AUTHORITY_VIOLATION:
            authority_violations += 1

    resume_attempts = resume_success + resume_failure
    premature_doc_rate = premature / sessions if sessions else 0.0
    resume_success_rate = resume_success / resume_attempts if resume_attempts else 1.0

    return {
        "version": METRIC_VERSION,
        "counts": {
            "sessions": sessions,
            "prematureDocAttempts": premature,
            "resumeSuccess": resume_success,
            "resumeFailure": resume_failure,
            "authorityBoundaryViolations": authority_violations,
        },
        "rates": {
            "prematureDocRate": round(premature_doc_rate, 6),
            "resumeSuccessRate": round(resume_success_rate, 6),
        },
        "authorityBoundaryViolations": authority_violations,
    }


def evaluate_against_thresholds(
    metrics: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare aggregated metrics to exploration-acceptance thresholds."""
    failures: list[str] = []
    rates = metrics.get("rates") if isinstance(metrics.get("rates"), Mapping) else {}
    counts = metrics.get("counts") if isinstance(metrics.get("counts"), Mapping) else {}

    premature_cfg = thresholds.get("prematureDocRate") or {}
    if isinstance(premature_cfg, Mapping):
        maximum = premature_cfg.get("max")
        if maximum is not None and float(rates.get("prematureDocRate", 0.0)) > float(maximum):
            failures.append("premature-doc-rate-exceeded")

    resume_cfg = thresholds.get("resumeSuccessRate") or {}
    if isinstance(resume_cfg, Mapping):
        minimum = resume_cfg.get("min")
        if minimum is not None and float(rates.get("resumeSuccessRate", 1.0)) < float(minimum):
            failures.append("resume-success-rate-below-minimum")

    authority_cfg = thresholds.get("authorityBoundaryViolations") or {}
    if isinstance(authority_cfg, Mapping):
        maximum = authority_cfg.get("max", 0)
        violations = int(
            counts.get("authorityBoundaryViolations", metrics.get("authorityBoundaryViolations", 0))
        )
        if violations > int(maximum):
            failures.append("authority-boundary-violations-nonzero")

    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "metrics": dict(metrics),
    }


def load_acceptance_thresholds(root: Path | None = None) -> dict[str, Any]:
    path = _repo_root(root) / "core" / "sw-reference" / "exploration-acceptance.json"
    if not path.is_file():
        raise ExplorationMetricsError("acceptance-config-missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ExplorationMetricsError("acceptance-config-invalid")
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        raise ExplorationMetricsError("acceptance-metrics-missing")
    return metrics


def emit_metrics_report(events: Sequence[Mapping[str, Any]], *, root: Path | None = None) -> dict[str, Any]:
    """Aggregate events and evaluate against the acceptance checklist thresholds."""
    aggregated = aggregate_metrics(events)
    thresholds = load_acceptance_thresholds(root)
    evaluation = evaluate_against_thresholds(aggregated, thresholds)
    return {
        "version": METRIC_VERSION,
        "aggregated": aggregated,
        "thresholdEvaluation": evaluation,
    }
