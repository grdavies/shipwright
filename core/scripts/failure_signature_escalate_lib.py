"""Threshold escalation to captured root-cause records (PRD 041 R22/R23/R24)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import failure_signature_record_lib as fsr
import sw_state_write_lib as writer

WRITER_NAME = "failure_signature_escalate_lib"
DEFAULT_THRESHOLD = 3
MIN_DISTINCT_RUNS = 2

FLAKE_HINTS = re.compile(r"\b(flake|flaky|intermittent|timeout|retry)\b", re.I)
INFRA_HINTS = re.compile(r"\b(infra|runner|network|dns|quota)\b", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_recurrence_config(cfg: dict[str, Any] | None) -> tuple[int, bool]:
    if not cfg:
        return DEFAULT_THRESHOLD, False
    recurrence = cfg.get("recurrence")
    if not isinstance(recurrence, dict):
        return DEFAULT_THRESHOLD, False
    enabled = recurrence.get("enabled")
    if enabled is False:
        return DEFAULT_THRESHOLD, False
    threshold = recurrence.get("threshold")
    if threshold is None:
        return DEFAULT_THRESHOLD, False
    try:
        value = int(threshold)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD, False
    if value < 1:
        return DEFAULT_THRESHOLD, False
    return value, True


def resolve_catalog_path(root: Path) -> Path:
    for base in (root, root / "core", writer.SCRIPT_DIR.parent):
        candidate = base / "core/sw-reference/anomaly-patterns.json"
        if candidate.is_file():
            return candidate
    raise writer.StateWriteError(
        "anomaly-patterns.json missing",
        halt="schema-missing",
    )


def load_anomaly_catalog(root: Path) -> dict[str, Any]:
    path = resolve_catalog_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise writer.StateWriteError(f"invalid anomaly catalog: {exc}", halt="schema-invalid") from exc
    if not isinstance(data, dict) or not isinstance(data.get("patterns"), list):
        raise writer.StateWriteError("anomaly catalog patterns invalid", halt="schema-invalid")
    return data


def empty_root_cause_store() -> dict[str, Any]:
    return {"version": 1, "records": []}


def load_root_cause_store(root: Path) -> dict[str, Any]:
    path = writer.resolve_store_path(root, "root-cause-records")
    doc = writer.load_store(path)
    if not doc:
        return empty_root_cause_store()
    writer.validate_root_cause_records(doc)
    return doc


def record_id_for_key(key: dict[str, Any]) -> str:
    digest = hashlib.sha256(writer.key_token(key).encode("utf-8")).hexdigest()[:16]
    return f"rca-{digest}"


def escalated_key_tokens(root: Path) -> set[str]:
    doc = load_root_cause_store(root)
    tokens: set[str] = set()
    for rec in doc.get("records") or []:
        key = rec.get("signatureKey")
        if isinstance(key, dict):
            tokens.add(writer.key_token(key))
    return tokens


def classify_signature_class(key: dict[str, Any], failure_text: str) -> str:
    blob = " ".join(
        [
            str(key.get("checkId") or ""),
            str(key.get("jobId") or ""),
            failure_text,
        ]
    )
    if FLAKE_HINTS.search(blob):
        return "flake"
    if INFRA_HINTS.search(blob):
        return "infra"
    return "regression"


def run_debug_entry_rca(failure_text: str, key: dict[str, Any]) -> dict[str, Any]:
    redacted = writer.redact_text(failure_text)
    check_id = str(key.get("checkId") or "unknown")
    exit_code = int(key.get("exitCode") or 0)
    return {
        "entry": "debug",
        "hypotheses": [
            f"Recurring host-attested failure on {check_id} (exit {exit_code})",
            "Surface fix attempted without addressing underlying cause",
        ],
        "rootCause": (
            f"Cross-run recurrence on {check_id} indicates root cause not resolved by surface fixes"
        ),
        "recommendedFix": (
            "Consult rca-core debug-entry; file gap unit or debug handoff — do not repeat surface fix"
        ),
        "verification": f"Confirm resolution across ≥{MIN_DISTINCT_RUNS} distinct runs after fix",
        "failureTextRedacted": redacted,
    }


def recognize_anomaly_patterns(
    root: Path,
    failure_text: str,
    *,
    prd_a_flags: list[str] | None = None,
) -> list[dict[str, Any]]:
    catalog = load_anomaly_catalog(root)
    normalized = failure_text.lower()
    annotations: list[dict[str, Any]] = []
    for pattern in catalog.get("patterns") or []:
        if not isinstance(pattern, dict):
            continue
        matched = any(
            isinstance(sig, str) and sig.lower() in normalized
            for sig in (pattern.get("signals") or [])
        )
        if not matched:
            continue
        annotations.append(
            {
                "patternId": str(pattern.get("id") or ""),
                "matched": True,
                "annotation": str(pattern.get("annotation") or ""),
                "autoAct": False,
            }
        )
    excluded = catalog.get("excluded") if isinstance(catalog.get("excluded"), dict) else {}
    tamper = excluded.get("test-tampering") if isinstance(excluded, dict) else {}
    flags = [f.lower() for f in (prd_a_flags or [])]
    if any("test-tamper" in f or "test_tamper" in f for f in flags):
        note = str((tamper or {}).get("note") or "PRD A R9 test-tamper flag present")
        annotations.append(
            {
                "patternId": "test-tampering",
                "matched": True,
                "annotation": note,
                "autoAct": False,
            }
        )
    return annotations


def is_loop_closed(record: dict[str, Any]) -> bool:
    if record.get("status") == "closed":
        return True
    if record.get("signatureClass") == "flake":
        waiver = record.get("flakeWaiver") or {}
        return bool(waiver.get("acknowledged"))
    return False


def is_eligible_signature(record: dict[str, Any], threshold: int) -> bool:
    count = int(record.get("count") or 0)
    runs = list(record.get("runs") or [])
    distinct = len({r for r in runs if r})
    return count >= threshold and distinct >= MIN_DISTINCT_RUNS


def escalate_record(
    root: Path,
    signature_record: dict[str, Any],
    *,
    failure_text: str = "",
    prd_a_flags: list[str] | None = None,
) -> dict[str, Any]:
    key = signature_record.get("key")
    if not isinstance(key, dict):
        raise writer.StateWriteError("signature record missing key", halt="schema-invalid")
    token = writer.key_token(key)
    if token in escalated_key_tokens(root):
        existing = next(
            (
                r
                for r in load_root_cause_store(root).get("records") or []
                if writer.key_token(r.get("signatureKey") or {}) == token
            ),
            None,
        )
        if existing:
            return existing
    message_class = str(key.get("messageClass") or "")
    text = failure_text or message_class
    signature_class = classify_signature_class(key, text)
    rca = run_debug_entry_rca(text, key)
    patterns = recognize_anomaly_patterns(root, text, prd_a_flags=prd_a_flags)
    record = {
        "id": record_id_for_key(key),
        "signatureKey": key,
        "status": "escalated",
        "signatureClass": signature_class,
        "escalatedAt": utc_now(),
        "source": "recurrence-threshold",
        "writer": WRITER_NAME,
        "failureText": rca.get("failureTextRedacted") or writer.redact_text(text),
        "rca": {
            "entry": rca["entry"],
            "hypotheses": rca.get("hypotheses") or [],
            "rootCause": rca["rootCause"],
            "recommendedFix": rca["recommendedFix"],
            "verification": rca["verification"],
        },
        "anomalyPatterns": patterns,
        "flakeWaiver": {
            "acknowledged": False,
            "acknowledgedAt": None,
            "acknowledgedBy": None,
        },
        "loopClosed": False,
    }
    record["loopClosed"] = is_loop_closed(record)
    doc = load_root_cause_store(root)
    records: list[dict[str, Any]] = list(doc.get("records") or [])
    records.append(record)
    doc["records"] = sorted(records, key=lambda r: str(r.get("id") or ""))
    writer.cmd_write(root, store="root-cause-records", data=doc)
    return record


def scan_and_escalate(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    failure_text: str = "",
    prd_a_flags: list[str] | None = None,
) -> list[dict[str, Any]]:
    threshold, enabled = load_recurrence_config(cfg)
    if not enabled:
        return []
    doc = fsr.load_failure_store(root)
    escalated: list[dict[str, Any]] = []
    already = escalated_key_tokens(root)
    for rec in doc.get("records") or []:
        if not isinstance(rec, dict):
            continue
        key = rec.get("key")
        if not isinstance(key, dict):
            continue
        if writer.key_token(key) in already:
            continue
        if not is_eligible_signature(rec, threshold):
            continue
        escalated.append(
            escalate_record(root, rec, failure_text=failure_text, prd_a_flags=prd_a_flags)
        )
    return escalated


def maybe_escalate_threshold(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    failure_text: str = "",
    prd_a_flags: list[str] | None = None,
) -> None:
    try:
        scan_and_escalate(root, cfg, failure_text=failure_text, prd_a_flags=prd_a_flags)
    except Exception:
        return


def acknowledge_flake_waiver(
    root: Path,
    record_id: str,
    *,
    acknowledged_by: str = "human",
) -> dict[str, Any]:
    doc = load_root_cause_store(root)
    records: list[dict[str, Any]] = list(doc.get("records") or [])
    target: dict[str, Any] | None = None
    for rec in records:
        if rec.get("id") == record_id:
            target = rec
            break
    if target is None:
        raise writer.StateWriteError(f"root-cause record not found: {record_id}", halt="not-found")
    if target.get("signatureClass") != "flake":
        raise writer.StateWriteError(
            "flake waiver only applies to signatureClass flake",
            halt="policy-violation",
        )
    target["flakeWaiver"] = {
        "acknowledged": True,
        "acknowledgedAt": utc_now(),
        "acknowledgedBy": acknowledged_by,
    }
    target["loopClosed"] = is_loop_closed(target)
    writer.cmd_write(root, store="root-cause-records", data=doc)
    return target
