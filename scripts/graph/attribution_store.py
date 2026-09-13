#!/usr/bin/env python3
"""Atomic attribution record store — schema v1.0.0 (PRD 351 R1–R5, R28, TR3)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal, Mapping, MutableMapping, Optional, TypedDict

# Allow `python scripts/graph/attribution_store.py ...` without PYTHONPATH.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

ATTRIBUTION_SCHEMA_VERSION = "1.0.0"

VerificationResult = Literal["pass", "fail", "partial", "unknown"]

# Sentinel strings historically substituted for missing dimensions (R6) — never write these.
KNOWN_DIMENSION_SENTINELS = frozenset({"python", "build", "medium"})

NULLABLE_DIMENSION_FIELDS = (
    "task_type",
    "effort_hint",
    "complexity_indicators",
    "requested_model",
    "actual_model",
    "host_version",
    "tokens_input",
    "tokens_output",
    "rework_required",
    "failed_tokens_null_count",
)


class AttributionWriteError(RuntimeError):
    """Raised when an attribution record cannot be persisted atomically."""


class AttributionRecord(TypedDict, total=False):
    """Attribution record schema v1.0.0 (R1 table).

    All nullable fields are Optional. ``post_merge_defects`` is always null in
    this release — # sw:deferred-defect-linkage
    """

    task_record_id: str
    attribution_schema_version: str
    requested_model: Optional[str]
    actual_model: Optional[str]
    host_version: Optional[str]
    effort_hint: Optional[str]
    task_type: Optional[str]
    complexity_indicators: Optional[Any]
    attempt_count: int
    failed_attempt_count: Optional[int]
    failed_tokens_null_count: Optional[int]
    tokens_input: Optional[int]
    tokens_output: Optional[int]
    verification_result: VerificationResult
    rework_required: Optional[bool]
    post_merge_defects: None  # sw:deferred-defect-linkage — always null in schema v1.0.0
    zero_tokens_attested: bool
    telemetry_suspect: bool
    legacy: bool


def make_task_record_id() -> str:
    """Stable UUID for a new attribution record (R5)."""
    return str(uuid.uuid4())


def build_attribution_record(
    *,
    requested_model: Optional[str] = None,
    actual_model: Optional[str] = None,
    host_version: Optional[str] = None,
    effort_hint: Optional[str] = None,
    task_type: Optional[str] = None,
    complexity_indicators: Optional[Any] = None,
    attempt_count: int = 1,
    failed_attempt_count: Optional[int] = None,
    failed_tokens_null_count: Optional[int] = None,
    tokens_input: Optional[int] = None,
    tokens_output: Optional[int] = None,
    verification_result: VerificationResult = "unknown",
    rework_required: Optional[bool] = None,
    zero_tokens_attested: bool = False,
    telemetry_suspect: bool = False,
    task_record_id: Optional[str] = None,
    attribution_schema_version: Optional[str] = None,
    legacy: Optional[bool] = None,
) -> AttributionRecord:
    """Construct a validated AttributionRecord (R1–R5, R28).

    Raises ValueError when ``attempt_count < 1``.
    """
    if attempt_count < 1:
        raise ValueError("attempt_count must be >= 1")

    schema_version = attribution_schema_version
    is_legacy = legacy
    if schema_version is None:
        # Absent schema version → legacy marker (R28 / TS9).
        is_legacy = True if is_legacy is None else is_legacy
        schema_version = ATTRIBUTION_SCHEMA_VERSION
    else:
        is_legacy = False if is_legacy is None else is_legacy

    record: AttributionRecord = {
        "task_record_id": task_record_id or make_task_record_id(),
        "attribution_schema_version": schema_version,
        "requested_model": requested_model,
        "actual_model": actual_model,
        "host_version": host_version,
        "effort_hint": effort_hint,
        "task_type": task_type,
        "complexity_indicators": complexity_indicators,
        "attempt_count": attempt_count,
        "failed_attempt_count": failed_attempt_count,
        "failed_tokens_null_count": failed_tokens_null_count,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "verification_result": verification_result,
        "rework_required": rework_required,
        "post_merge_defects": None,  # sw:deferred-defect-linkage
        "zero_tokens_attested": bool(zero_tokens_attested),
        "telemetry_suspect": bool(telemetry_suspect),
        "legacy": bool(is_legacy),
    }
    return record


def mark_legacy_if_unversioned(record: MutableMapping[str, Any]) -> None:
    """Set ``legacy: true`` when ``attribution_schema_version`` is absent (TS9)."""
    if "attribution_schema_version" not in record or record.get("attribution_schema_version") in (
        None,
        "",
    ):
        record["legacy"] = True


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def write_attribution_record(record: AttributionRecord, run_dir: Path) -> None:
    """Persist ``record`` under ``<run_dir>/attribution/<task_record_id>.json``.

    Uses write-to-tempfile-then-``os.replace`` (same pattern as workflow_intelligence
    ``_atomic_write``). Does **not** route through ``planning_gap_capture.py`` (TR3).
    """
    task_id = str(record.get("task_record_id") or "").strip()
    if not task_id:
        raise AttributionWriteError("task_record_id required")

    destination = Path(run_dir) / "attribution" / f"{task_id}.json"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            dir=str(destination.parent),
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(_canonical_json(dict(record)))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    except AttributionWriteError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as typed write error
        raise AttributionWriteError(str(exc)) from exc


def audit_null_purity(run_dir: Path) -> dict[str, Any]:
    """Scan attribution JSON for sentinel substitution violations (SC-M1/SC-M2).

    Also loads records into ``workflow_intelligence.filter_comparison_group`` and
    asserts every retained group member has fully known dimension values (R6/R7).
    """
    # Local import keeps store usable without intelligence module at import time.
    from workflow_intelligence import (
        ATTRIBUTION_DIMENSION_KEYS,
        dimension_record_complete,
        filter_comparison_group,
    )

    attribution_dir = Path(run_dir) / "attribution"
    violations: list[str] = []
    scanned = 0
    loaded: list[dict[str, Any]] = []
    if attribution_dir.is_dir():
        for path in sorted(attribution_dir.glob("*.json")):
            scanned += 1
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            record_id = str(payload.get("task_record_id") or path.stem)
            for field in NULLABLE_DIMENSION_FIELDS:
                value = payload.get(field)
                if isinstance(value, str) and value.strip().lower() in KNOWN_DIMENSION_SENTINELS:
                    violations.append(record_id)
                    break
            loaded.append(payload)

    comparison_group = filter_comparison_group(loaded)
    incomplete_members: list[str] = []
    for member in comparison_group:
        dims = member.get("dimensions") if isinstance(member.get("dimensions"), dict) else member
        if not dimension_record_complete(dims):
            incomplete_members.append(str(member.get("task_record_id") or ""))
        # Explicit known-dimension assertion for SC-M2.
        for key in ATTRIBUTION_DIMENSION_KEYS:
            if dims.get(key) is None:
                rid = str(member.get("task_record_id") or "")
                if rid and rid not in incomplete_members:
                    incomplete_members.append(rid)
                break

    return {
        "substitution_violations": len(violations),
        "records_scanned": scanned,
        "violation_record_ids": violations,
        "comparison_group_size": len(comparison_group),
        "comparison_group_incomplete_members": incomplete_members,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Attribution store utilities (PRD 351)")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit-null-purity", help="Scan for sentinel dimension substitutions")
    audit.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "audit-null-purity":
        print(json.dumps(audit_null_purity(args.run_dir), indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
